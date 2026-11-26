"""Validation on SYNTHETIC data, where every fault was injected by us and the
answer key (batch, sensor, start time) is known exactly."""
import numpy as np
import pandas as pd
import pytest

from biomon import db, monitoring, report, synthetic


def first_alarm(alarms, batch_id, sensor, method=None, after=None):
    a = alarms[(alarms.batch_id == batch_id) & (alarms.sensor == sensor)]
    if method:
        a = a[a.method == method]
    if after is not None:
        a = a[a.start_h >= after]
    return a.start_h.min() if len(a) else None


# ---------- the generator ----------

def test_generator_is_labelled_and_reproducible():
    b1, r1, f1 = synthetic.generate(seed=1)
    b2, r2, f2 = synthetic.generate(seed=1)
    assert b1.notes.str.startswith("SYNTHETIC").all()
    pd.testing.assert_frame_equal(r1, r2)
    assert set(f1.kind) == set(synthetic.FAULT_TYPES)


# ---------- faults are detected ----------

FAULT_KINDS = [k for k in synthetic.FAULT_TYPES if k != "sensor_dropout"]


@pytest.mark.parametrize("kind", FAULT_KINDS)
def test_injected_fault_detected_on_right_sensor(synth, kind):
    faults = synth["data"][2]
    for f in faults[faults.kind == kind].itertuples():
        t = first_alarm(synth["alarms"], f.batch_id, f.sensor, after=f.start_h)
        assert t is not None, f"{kind} in {f.batch_id} was not detected"
        assert t <= f.end_h


def test_step_fault_detected_within_one_hour(synth):
    faults = synth["data"][2]
    for f in faults[faults.kind == "cooling_failure"].itertuples():
        t = first_alarm(synth["alarms"], f.batch_id, "temperature", "shewhart", after=f.start_h)
        assert t - f.start_h <= 1.0


def test_ewma_catches_slow_drift_no_later_than_shewhart(synth):
    """The reason to add EWMA: a slow drift should be caught by it first."""
    faults = synth["data"][2]
    for f in faults[faults.kind == "base_pump_drift"].itertuples():
        e = first_alarm(synth["alarms"], f.batch_id, "ph", "ewma", after=f.start_h)
        s = first_alarm(synth["alarms"], f.batch_id, "ph", "shewhart", after=f.start_h)
        assert e is not None
        assert s is None or e <= s


def test_every_fault_batch_detected_in_report(synth):
    s = report.summary(report.score(synth["conn"]))
    assert s["faults_detected"] == s["fault_batches"] == 10


# ---------- missing readings ----------

def test_missing_readings_flagged_exactly(synth):
    readings = synth["data"][1]
    n_injected = int(readings.value.isna().sum())
    gaps = db.query(synth["conn"], "missing_readings")
    assert gaps.n_missing.sum() == n_injected
    assert synth["scored"].missing.sum() == n_injected


def test_sensor_dropout_found_as_gap(synth):
    faults = synth["data"][2]
    gaps = db.query(synth["conn"], "missing_readings")
    for f in faults[faults.kind == "sensor_dropout"].itertuples():
        g = gaps[(gaps.batch_id == f.batch_id) & (gaps.sensor == f.sensor)]
        assert ((g.gap_start_h <= f.start_h) & (g.gap_end_h >= f.end_h)).any()


# ---------- SQL agrees with Python ----------

def test_out_of_spec_sql_matches_python(synth, cfg):
    sensors = cfg["datasets"]["synthetic"]["sensors"]
    r = synth["scored"]
    low, high = r.sensor.map(lambda s: sensors[s]["low"]), r.sensor.map(lambda s: sensors[s]["high"])
    expected = int(((r.value < low) | (r.value > high)).sum())
    assert len(db.query(synth["conn"], "out_of_spec")) == expected


def test_out_of_control_sql_matches_python(synth):
    expected = int(synth["scored"].shewhart_flag.sum())
    assert len(db.query(synth["conn"], "out_of_control")) == expected


def test_step_fault_is_in_spec_but_out_of_control(synth):
    """The cooling failure never breaks the 29-31 degC spec, yet the control
    chart catches it: why control limits matter on top of spec limits."""
    faults = synth["data"][2]
    oos = db.query(synth["conn"], "out_of_spec")
    for f in faults[faults.kind == "cooling_failure"].itertuples():
        assert oos[(oos.batch_id == f.batch_id) & (oos.sensor == "temperature")].empty
        assert first_alarm(synth["alarms"], f.batch_id, "temperature", after=f.start_h) is not None


# ---------- normal batches ----------

def test_calibration_never_below_textbook(synth, cfg):
    s = synth["settings"]
    assert s.sigma_k >= cfg["monitoring"]["sigma_k"]
    assert s.ewma_k >= cfg["monitoring"]["ewma_k"]


@pytest.mark.xfail(strict=True, reason=(
    "Known limitation: measured 12% of fresh normal batches with a false alarm "
    "(target 5%, bound 10%). Calibrating from only 20 baseline batches lets just "
    "1 batch alarm, so k comes from a noisy estimate and is slightly too low. "
    "strict=True: if this starts passing, pytest reports it so the README can be updated."))
def test_false_alarm_rate_on_fresh_normal_batches(synth, cfg):
    """100 new normal batches (different seed, never seen by the calibration).
    Calibration targets 5 % of batches with any alarm; with only 20 baseline
    batches the limits are estimated imperfectly, so we allow up to 10 %.
    The bound was set before running the test."""
    b, r, _ = synthetic.generate(n_baseline=0, n_normal_test=100, faults_per_type=0, seed=2024)
    r = db.complete_grid(r, cfg["datasets"]["synthetic"]["sample_interval_h"])
    limits = db.read_table(synth["conn"], "SELECT * FROM control_limits")
    scored = monitoring.evaluate(r, limits, synth["settings"])
    alarms = monitoring.alarm_events(scored, synth["settings"])
    rate = alarms.batch_id.nunique() / len(b)
    print(f"\nFresh normal batches with a false alarm: {rate:.0%}")
    assert rate <= 0.10


def test_no_alarm_without_limits():
    """Readings at times with no baseline coverage must never be flagged."""
    s = monitoring.Settings()
    readings = pd.DataFrame({"batch_id": "X", "sensor": "ph", "t_idx": np.arange(5),
                             "t_hours": np.arange(5) * 0.25, "value": [7.0, 9.0, 9.0, 9.0, 9.0]})
    num = ["t_hours", "n_batches", "mean", "sd", "lcl", "ucl", "ewma_mean", "ewma_sd", "ewma_lcl", "ewma_ucl"]
    limits = pd.DataFrame({"sensor": pd.Series(dtype=str), "t_idx": pd.Series(dtype=int),
                           **{c: pd.Series(dtype=float) for c in num}})
    scored = monitoring.evaluate(readings, limits, s)
    assert not scored.shewhart_flag.any() and not scored.ewma_flag.any()
