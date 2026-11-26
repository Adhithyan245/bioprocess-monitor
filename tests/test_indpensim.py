"""Checks on the IndPenSim extract. Skipped if the extract file isn't present."""
import pandas as pd
import pytest

from biomon import indpensim

pytestmark = pytest.mark.skipif(not indpensim.EXTRACT.exists(), reason="IndPenSim extract not built")


@pytest.fixture(scope="module")
def ips():
    return indpensim.load()


def test_batches_and_split(ips):
    batches, readings, faults = ips
    assert len(batches) == 100
    assert (batches.true_status == "fault").sum() == 10
    assert (batches.role == "baseline").sum() == 45
    # faulted batches are never used to learn the limits
    assert not ((batches.role == "baseline") & (batches.true_status == "fault")).any()
    assert set(faults.batch_id) == set(batches.loc[batches.true_status == "fault", "batch_id"])


def test_units_converted(ips):
    r = ips[1]
    t = r[r.sensor == "temperature"].value
    assert 20 < t.median() < 30  # degC, not kelvin


def test_aeration_and_pressure_loaded(ips):
    r = ips[1]
    assert {"aeration", "pressure"} <= set(r.sensor)
    assert r[r.sensor == "aeration"].value.between(0, 200).all()   # L/h
    assert r[r.sensor == "pressure"].value.between(0, 3).all()     # bar


def test_step_signals_not_smoothed_so_normal_batches_unflagged(ips):
    """Aeration/pressure follow recipe steps; smoothing the band would put a
    stray flag at every step. With smoothing_window 1 normal batches stay clean."""
    from biomon import db, monitoring
    batches, r, _ = ips
    cfg = db.load_config()
    sensors = cfg["datasets"]["indpensim"]["sensors"]
    s = monitoring.Settings.from_config(cfg)
    r = r[r.sensor.isin(["aeration", "pressure"])]
    base = batches.loc[batches.role == "baseline", "batch_id"]
    lim = monitoring.control_limits(
        r, base, {k: v["min_sigma"] for k, v in sensors.items()}, s,
        {k: v["smoothing_window"] for k, v in sensors.items() if "smoothing_window" in v})
    normal = batches.loc[batches.true_status == "normal", "batch_id"]
    scored = monitoring.evaluate(r[r.batch_id.isin(normal)], lim, s)
    assert scored.shewhart_flag.sum() == 0


def test_documented_finding_normal_upsets_as_deep_as_faults(ips):
    """README finding: some 'normal' batches have pH dips as deep as the
    faulted ones, which is why univariate limits can't separate them."""
    batches, r, _ = ips
    ph = r[r.sensor == "ph"].groupby("batch_id").value.min()
    status = batches.set_index("batch_id").true_status
    assert ph[status == "normal"].min() <= ph[status == "fault"].min()
