"""IndPenSim: extract the four monitored sensors from the public dataset.

Source: Goldrick et al., IndPenSim 100-batch dataset, Mendeley Data,
doi:10.17632/pdnjz7zz5x.2, licensed CC BY 4.0.

The raw zip (~504 MB, ~2.5 GB unzipped, mostly Raman spectra) is not kept in
the repo. `extract()` streams it once and writes a small gzipped CSV,
data/indpensim_extract.csv.gz, which everything else reads.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_ZIP = ROOT / "data" / "raw" / "100_Batches_IndPenSim.zip"
EXTRACT = ROOT / "data" / "indpensim_extract.csv.gz"
CSV_IN_ZIP = "Mendeley_data/100_Batches_IndPenSim_V3.csv"

# Column POSITION in the data rows -> our short name.
# We read by position, not by name: the CSV header has 2,239 names but each
# data row has 2,237 fields (header "1- No Raman spec, 1-Raman spec recorded"
# was split at its comma, among others), so names after column 32 are shifted.
# Positions 0-32 match the header; 35 (batch number) was identified from the
# data itself (it increments at every time reset).
COLUMNS = {
    0: "t_hours",            # Time (h)
    1: "aeration",           # Aeration rate Fg (L/h)
    2: "agitation",          # Agitator RPM
    9: "pressure",           # Air head pressure (bar)
    12: "dissolved_oxygen",  # Dissolved oxygen concentration (mg/L)
    16: "ph",                # pH
    17: "temperature",       # Temperature (K)
    31: "fault_ref",         # Fault reference (0/1)
    32: "control_ref",       # 0 = recipe driven, 1 = operator controlled
    35: "batch_no",          # Batch reference (1-100)
}
# Note: the column headed "Fault flag" is not a 0/1 flag in the data (it holds
# large counter-like values), so the fault answer key comes from fault_ref.
SENSORS = ["temperature", "ph", "dissolved_oxygen", "agitation", "aeration", "pressure"]


def extract(raw_zip: Path = RAW_ZIP, out: Path = EXTRACT) -> pd.DataFrame:
    """Stream the big CSV, keep only the columns we need, save a small extract."""
    with zipfile.ZipFile(raw_zip) as z, z.open(CSV_IN_ZIP) as fh:
        df = pd.read_csv(fh, header=None, skiprows=1, usecols=list(COLUMNS), dtype=np.float64)
    df = df.rename(columns=COLUMNS)[list(COLUMNS.values())]
    df["temperature"] = df["temperature"] - 273.15  # kelvin -> degC
    df["batch_no"] = df["batch_no"].astype(int)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, float_format="%.6g", compression="gzip")
    return df


def load(path: Path = EXTRACT, dt: float = 0.2):
    """Return (batches, readings, faults) DataFrames in the biomon schema.

    Baseline/test split (decided before looking at detection results):
      * Batches 1-90 are normal (no faults). Odd numbers -> baseline, even -> test.
        That gives 45 baseline and 45 held-out normal batches, covering all
        three control strategies (recipe, operator, Raman APC) in both groups.
      * Batches 91-100 contain process faults -> test.
    """
    df = pd.read_csv(path)
    df["t_idx"] = np.rint(df["t_hours"] / dt).astype(int)
    df["batch_id"] = df["batch_no"].map(lambda n: f"IPS-{n:03d}")

    batches = []
    for n, g in df.groupby("batch_no"):
        is_fault = n >= 91
        strategy = "recipe" if n <= 30 else "operator" if n <= 60 else "Raman APC" if n <= 90 else "faulted"
        batches.append({
            "batch_id": f"IPS-{n:03d}",
            "source": "indpensim",
            "role": "test" if (is_fault or n % 2 == 0) else "baseline",
            "true_status": "fault" if is_fault else "normal",
            "notes": f"Control strategy: {strategy}",
        })
    batches = pd.DataFrame(batches)

    readings = df.melt(
        id_vars=["batch_id", "t_idx", "t_hours"], value_vars=SENSORS,
        var_name="sensor", value_name="value",
    )

    # Fault windows: contiguous stretches where the fault flag is set.
    flag_col = "fault_ref"
    faults = []
    for bid, g in df[df.batch_no >= 91].groupby("batch_id"):
        on = g[flag_col].to_numpy() > 0
        t = g["t_hours"].to_numpy()
        if not on.any():
            faults.append({"batch_id": bid, "sensor": None, "kind": "unlabelled",
                           "start_h": float(t[0]), "end_h": float(t[-1]),
                           "description": "Fault batch with no flagged window"})
            continue
        edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
        for s, e in zip(edges[::2], edges[1::2]):
            faults.append({"batch_id": bid, "sensor": None, "kind": "process_fault",
                           "start_h": float(t[s]), "end_h": float(t[e - 1]),
                           "description": f"IndPenSim labelled fault ({flag_col})"})
    return batches, readings, pd.DataFrame(faults)


if __name__ == "__main__":
    d = extract()
    print(d.shape, d.batch_no.nunique(), "batches ->", EXTRACT)
