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


def test_documented_finding_normal_upsets_as_deep_as_faults(ips):
    """README finding: some 'normal' batches have pH dips as deep as the
    faulted ones, which is why univariate limits can't separate them."""
    batches, r, _ = ips
    ph = r[r.sensor == "ph"].groupby("batch_id").value.min()
    status = batches.set_index("batch_id").true_status
    assert ph[status == "normal"].min() <= ph[status == "fault"].min()
