"""SQLite storage and the SQL analysis queries (kept as .sql files in sql/)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
CONFIG_PATH = ROOT / "config" / "sensor_limits.json"
DATA_DIR = ROOT / "data"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def db_path(source: str) -> Path:
    return DATA_DIR / f"{source}.db"


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def complete_grid(readings: pd.DataFrame, dt: float) -> pd.DataFrame:
    """Give every batch/sensor a row for every sample time from its first to its
    last sample. Rows the data source never sent become value = NaN (missing)."""
    out = []
    for (bid, sensor), g in readings.groupby(["batch_id", "sensor"], sort=False):
        idx = pd.RangeIndex(int(g["t_idx"].min()), int(g["t_idx"].max()) + 1, name="t_idx")
        g = g.drop_duplicates("t_idx").set_index("t_idx").reindex(idx)
        g["batch_id"], g["sensor"] = bid, sensor
        g["t_hours"] = np.round(g.index.to_numpy() * dt, 4)
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)[["batch_id", "sensor", "t_idx", "t_hours", "value"]]


def write_dataset(conn, batches, readings, faults, sensors_cfg: dict) -> None:
    conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    for table in ("alarms", "calibration", "control_limits", "faults", "readings", "batches", "sensor_limits"):
        conn.execute(f"DELETE FROM {table}")
    conn.executemany(
        "INSERT INTO sensor_limits VALUES (?, ?, ?, ?, ?)",
        [(s, c["label"], c["unit"], c.get("low"), c.get("high")) for s, c in sensors_cfg.items()])
    batches[["batch_id", "source", "role", "true_status", "notes"]].to_sql(
        "batches", conn, if_exists="append", index=False)
    readings[["batch_id", "sensor", "t_idx", "t_hours", "value"]].to_sql(
        "readings", conn, if_exists="append", index=False, chunksize=50_000)
    if len(faults):
        faults[["batch_id", "sensor", "kind", "start_h", "end_h", "description"]].to_sql(
            "faults", conn, if_exists="append", index=False)
    conn.commit()


def write_table(conn, name: str, df: pd.DataFrame, columns: list[str]) -> None:
    conn.execute(f"DELETE FROM {name}")
    df[columns].to_sql(name, conn, if_exists="append", index=False, chunksize=50_000)
    conn.commit()


def query(conn, name: str, **params) -> pd.DataFrame:
    """Run sql/<name>.sql. Any :param not given defaults to NULL (= all batches)."""
    sql = (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
    params.setdefault("batch_id", None)
    return pd.read_sql_query(sql, conn, params=params)


def read_table(conn, sql: str, **params) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)
