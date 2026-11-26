"""Build a monitoring database end to end.

    python -m biomon.build synthetic
    python -m biomon.build indpensim

Steps: load data -> fill the time grid (gaps become missing) -> write to SQLite
-> learn control limits from baseline batches -> score every batch -> store
alarm events -> write the detection report to reports/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import db, monitoring, report


def load_source(source: str):
    if source == "synthetic":
        from .synthetic import generate
        return generate()
    if source == "indpensim":
        from .indpensim import load
        return load()
    raise ValueError(f"unknown source {source!r}")


def build(source: str, path: Path | None = None, data=None, cfg: dict | None = None):
    cfg = cfg or db.load_config()
    ds = cfg["datasets"][source]
    settings = monitoring.Settings.from_config(cfg)
    batches, readings, faults = data if data is not None else load_source(source)
    readings = db.complete_grid(readings, ds["sample_interval_h"])

    path = Path(path or db.db_path(source))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = db.connect(path)
    db.write_dataset(conn, batches, readings, faults, ds["sensors"])

    baseline = batches.loc[batches.role == "baseline", "batch_id"]
    min_sigma = {s: c.get("min_sigma", 0.0) for s, c in ds["sensors"].items()}
    if settings.calibrate:
        textbook = settings
        settings, crit = monitoring.calibrate(readings, baseline, min_sigma, settings)
        cal = pd.DataFrame([
            {"method": m, "textbook_k": tk, "calibrated_k": ck, "n_baseline": len(crit),
             "baseline_alarming_at_textbook": int((crit[m] > tk).sum()),
             "target_rate": settings.target_false_alarm_rate}
            for m, tk, ck in (("shewhart", textbook.sigma_k, settings.sigma_k),
                              ("ewma", textbook.ewma_k, settings.ewma_k))])
        db.write_table(conn, "calibration", cal, list(cal.columns))
    limits = monitoring.control_limits(readings, baseline, min_sigma, settings)
    db.write_table(conn, "control_limits", limits,
                   ["sensor", "t_idx", "t_hours", "n_batches", "mean", "sd", "lcl", "ucl",
                    "ewma_mean", "ewma_sd", "ewma_lcl", "ewma_ucl"])

    scored = monitoring.evaluate(readings, limits, settings)
    alarms = monitoring.alarm_events(scored, settings)
    db.write_table(conn, "alarms", alarms, list(alarms.columns))
    return conn, scored, alarms


def settings_from_db(conn, cfg: dict | None = None) -> monitoring.Settings:
    """Monitoring settings with the calibrated thresholds stored in the database."""
    s = monitoring.Settings.from_config(cfg or db.load_config())
    for method, k in conn.execute("SELECT method, calibrated_k FROM calibration"):
        s = monitoring.Settings(**{**s.__dict__, ("sigma_k" if method == "shewhart" else "ewma_k"): k})
    return s


def main(argv=None):
    argv = argv or sys.argv[1:]
    sources = argv or ["synthetic", "indpensim"]
    for source in sources:
        conn, scored, _ = build(source)
        out = report.write_report(conn, scored, source, settings_from_db(conn))
        print(f"{source}: database {db.db_path(source)}  report {out}")


if __name__ == "__main__":
    main()
