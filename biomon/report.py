"""Score alarms against the answer key and write an honest detection report.

Scoring rules (fixed before looking at results):
  * Only TEST batches are scored. Baseline batches taught the limits, so
    scoring them would flatter the results.
  * Normal test batch: any alarm on any sensor = false alarm.
  * Fault batch, sensor known (synthetic): detected if an alarm on that sensor
    STARTS at or after fault onset and no later than the fault's end.
  * Fault batch, sensor unknown (IndPenSim): detected if an alarm on ANY of
    the monitored sensors starts inside a labelled fault window.
  * Sensor dropout fault: detected if the missing-readings query reports a gap
    on that sensor overlapping the dropout window.
  * Alarms that start before the fault's onset count as false alarms.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from . import db, monitoring

REPORT_DIR = db.ROOT / "reports"


def score(conn, alarms: pd.DataFrame | None = None) -> pd.DataFrame:
    batches = db.read_table(conn, "SELECT * FROM batches WHERE role = 'test'")
    faults = db.read_table(conn, "SELECT * FROM faults")
    if alarms is None:
        alarms = db.read_table(conn, "SELECT * FROM alarms")
    gaps = db.query(conn, "missing_readings")
    rows = []
    for b in batches.itertuples():
        a = alarms[alarms.batch_id == b.batch_id]
        f = faults[faults.batch_id == b.batch_id]
        row = {"batch_id": b.batch_id, "true_status": b.true_status, "fault_kind": None,
               "fault_sensor": None, "onset_h": None, "detected": None, "method": None,
               "delay_h": None, "false_alarms": 0}
        if b.true_status == "normal" or f.empty:
            row["false_alarms"] = len(a)
            row["alarm_sensors"] = ", ".join(sorted(a.sensor.unique()))
            rows.append(row)
            continue

        onset, kind, sensor = f.start_h.min(), f.kind.iloc[0], f.sensor.iloc[0]
        row.update(fault_kind=kind, fault_sensor=sensor, onset_h=onset)
        row["false_alarms"] = int((a.start_h < onset).sum())
        row["alarm_sensors"] = ", ".join(sorted(a.sensor.unique()))

        if kind == "sensor_dropout":
            g = gaps[(gaps.batch_id == b.batch_id) & (gaps.sensor == sensor)]
            hit = g[(g.gap_start_h <= f.end_h.max()) & (g.gap_end_h >= onset)]
            row.update(detected=not hit.empty, method="missing-data",
                       delay_h=float(max(hit.gap_start_h.min() - onset, 0)) if not hit.empty else None)
            rows.append(row)
            continue

        cand = a if pd.isna(sensor) or sensor is None else a[a.sensor == sensor]
        in_window = cand[[any(s <= t <= e for s, e in zip(f.start_h, f.end_h)) for t in cand.start_h]]
        if in_window.empty:
            row["detected"] = False
        else:
            first = in_window.sort_values("start_h").iloc[0]
            row.update(detected=True, delay_h=float(first.start_h - onset),
                       method=f"{first.method} ({first.sensor})")
        rows.append(row)
    return pd.DataFrame(rows)


def point_flag_rates(scored: pd.DataFrame, conn) -> dict:
    """Share of readings flagged in held-out normal batches (point-level false flags)."""
    normal = db.read_table(conn, "SELECT batch_id FROM batches WHERE role='test' AND true_status='normal'")
    d = scored[scored.batch_id.isin(normal.batch_id) & scored.has_limits & ~scored.missing]
    return {"readings": len(d),
            "shewhart_flag_rate": float(d.shewhart_flag.mean()) if len(d) else 0.0,
            "ewma_flag_rate": float(d.ewma_flag.mean()) if len(d) else 0.0}


def summary(results: pd.DataFrame) -> dict:
    normal = results[results.true_status == "normal"]
    fault = results[results.true_status == "fault"]
    return {
        "normal_batches": len(normal),
        "normal_with_false_alarm": int((normal.false_alarms > 0).sum()),
        "fault_batches": len(fault),
        "faults_detected": int((fault.detected == True).sum()),  # noqa: E712
        "median_delay_h": float(fault.delay_h.dropna().median()) if fault.delay_h.notna().any() else None,
    }


TRADEOFF_KS = [3, 4, 5, 7, 10, 20, 40, 70, 110]


def tradeoff(conn, scored: pd.DataFrame, settings: monitoring.Settings, ks=TRADEOFF_KS) -> pd.DataFrame:
    """Detection vs false alarms if one k were shared by every sensor and both
    methods. For reporting only: no threshold is chosen from this table."""
    rows = []
    for k in ks:
        s2 = monitoring.Settings(**{**settings.__dict__, "sigma_k": k, "ewma_k": k})
        d = scored.copy()
        d["shewhart_flag"] = d["z"].abs() > k
        d["ewma_flag"] = (d["ewma"] - d["ewma_mean"]).abs() > k * d["ewma_sd"]
        sm = summary(score(conn, monitoring.alarm_events(d, s2)))
        rows.append({"k": k,
                     "faults_detected": f"{sm['faults_detected']}/{sm['fault_batches']}",
                     "normal_batches_false_alarm": f"{sm['normal_with_false_alarm']}/{sm['normal_batches']}"})
    return pd.DataFrame(rows)


def _has_rows(conn, table: str) -> bool:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0


def _md_table(df: pd.DataFrame) -> str:
    df = df.copy().astype(object).where(df.notna(), "")
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(f"{v:.3g}" if isinstance(v, float) else str(v) for v in r) + " |"
            for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def write_report(conn, scored: pd.DataFrame, source: str, settings: monitoring.Settings) -> Path:
    results = score(conn)
    s = summary(results)
    rates = point_flag_rates(scored, conn)
    fault = results[results.true_status == "fault"][
        ["batch_id", "fault_kind", "fault_sensor", "onset_h", "detected", "method", "delay_h", "false_alarms"]]
    normal_fa = results[(results.true_status == "normal") & (results.false_alarms > 0)][
        ["batch_id", "false_alarms", "alarm_sensors"]]

    label = "SYNTHETIC data (generated by biomon/synthetic.py)" if source == "synthetic" \
        else "IndPenSim public dataset (Goldrick et al., CC BY 4.0)"
    lines = [
        f"# Detection results: {source}", "",
        f"Data: {label}. Generated {date.today().isoformat()} by `python -m biomon.build {source}`.", "",
        "Only held-out test batches are scored; baseline batches were used to learn the limits.", "",
        "## Summary", "",
        f"- Faulty batches detected: **{s['faults_detected']} of {s['fault_batches']}**",
        f"- Normal batches with at least one false alarm: **{s['normal_with_false_alarm']} of {s['normal_batches']}**",
        f"- Median detection delay after fault onset: **{s['median_delay_h']:.1f} h**"
        if s["median_delay_h"] is not None else "- Median detection delay: n/a",
        f"- Point-level flag rate on normal test batches: Shewhart {rates['shewhart_flag_rate']:.2%}, "
        f"EWMA {rates['ewma_flag_rate']:.2%} of {rates['readings']:,} readings "
        "(flags are single points; alarms need 3 in a row)", "",
        "## Thresholds used", "",
        "One k per sensor and method, calibrated by leave-one-out on baseline batches only, "
        f"so that across all sensors together at most {settings.target_false_alarm_rate:.0%} of "
        "baseline batches would alarm (never below the textbook value). The last two columns "
        "count baseline batches that would alarm on that sensor at each k.", "",
        _md_table(db.read_table(conn, """
            SELECT method, sensor, textbook_k, calibrated_k,
                   baseline_alarming_at_textbook   AS alarming_at_textbook,
                   baseline_alarming_at_calibrated AS alarming_at_calibrated
            FROM calibration ORDER BY method DESC, sensor""")) if _has_rows(conn, "calibration")
        else "Textbook thresholds (calibration disabled).", "",
        "## Fault batches", "", _md_table(fault), "",
        "## Normal test batches with false alarms", "",
        _md_table(normal_fa) if len(normal_fa) else "None.", "",
        "## Trade-off: what other thresholds would have given", "",
        "If ONE k were shared by every sensor and both methods (the previous approach), "
        "scored on the same test batches. Shown for transparency only; the thresholds "
        "above were NOT chosen from this table.", "",
        _md_table(tradeoff(conn, scored, settings)), "",
    ]
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"detection_{source}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
