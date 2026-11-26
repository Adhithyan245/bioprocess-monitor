"""Statistical monitoring: time-varying Shewhart limits, EWMA drift detection,
missing-reading flags, and grouping of flags into alarm events.

Terms used throughout:
  flag   one reading outside a limit (shown as a marker on the chart)
  alarm  min_run or more consecutive flags on the same side (a real "event")
"""
from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np
import pandas as pd


@dataclass
class Settings:
    sigma_k: float = 3.0           # Shewhart band = mean +/- sigma_k * sd
    ewma_lambda: float = 0.2       # EWMA weight on the newest point (0-1)
    ewma_k: float = 3.0            # EWMA band = mean +/- ewma_k * sd of baseline EWMA curves
    min_run: int = 3               # consecutive same-side flags needed to raise an alarm
    min_baseline_batches: int = 5  # don't draw limits where fewer good batches exist
    smoothing_window: int = 5      # samples; smooths the limit curves over time
    calibrate: bool = True         # widen sigma_k / ewma_k using leave-one-out on baseline
    target_false_alarm_rate: float = 0.05  # share of baseline batches allowed to alarm

    @classmethod
    def from_config(cls, cfg: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in cfg.get("monitoring", {}).items() if k in known})


def ewma(z: np.ndarray, lam: float) -> np.ndarray:
    """EWMA of z. Missing values don't update the average (their output is NaN)."""
    out = np.full(len(z), np.nan)
    prev = 0.0
    for i, v in enumerate(z):
        if not np.isnan(v):
            prev = lam * v + (1 - lam) * prev
            out[i] = prev
    return out


def _smooth(df: pd.DataFrame, cols: list[str], window: int) -> pd.DataFrame:
    if window > 1:
        df[cols] = df.groupby("sensor")[cols].transform(
            lambda s: s.rolling(window, center=True, min_periods=1).mean())
    return df


def _add_ewma(df: pd.DataFrame, lam: float) -> pd.DataFrame:
    df = df.sort_values(["batch_id", "sensor", "t_idx"])
    df["ewma"] = np.concatenate([ewma(g.to_numpy(), lam)
                                 for _, g in df.groupby(["batch_id", "sensor"], sort=False)["z"]])
    return df


def control_limits(readings: pd.DataFrame, baseline_ids, min_sigma: dict[str, float],
                   s: Settings) -> pd.DataFrame:
    """Learn time-varying Shewhart and EWMA limits from baseline (known-good) batches."""
    base = readings[readings["batch_id"].isin(set(baseline_ids))]
    lim = (base.groupby(["sensor", "t_idx"])
               .agg(t_hours=("t_hours", "first"), n_batches=("value", "count"),
                    mean=("value", "mean"), sd=("value", "std"))
               .reset_index())
    lim = lim[lim["n_batches"] >= s.min_baseline_batches].copy()
    lim = _smooth(lim, ["mean", "sd"], s.smoothing_window)
    lim["sd"] = np.maximum(lim["sd"], lim["sensor"].map(min_sigma).fillna(0))
    lim["lcl"] = lim["mean"] - s.sigma_k * lim["sd"]
    lim["ucl"] = lim["mean"] + s.sigma_k * lim["sd"]

    # EWMA band: run the EWMA on each baseline batch's z-scores, then take
    # mean +/- k*sd across batches at each time point. This captures the
    # real (autocorrelated) behaviour of good batches instead of assuming
    # independent readings, which would cause constant false alarms.
    z = base.merge(lim[["sensor", "t_idx", "mean", "sd"]], on=["sensor", "t_idx"])
    z["z"] = (z["value"] - z["mean"]) / z["sd"]
    z = _add_ewma(z, s.ewma_lambda)
    e = (z.groupby(["sensor", "t_idx"])["ewma"].agg(ewma_mean="mean", ewma_sd="std")
          .reset_index())
    lim = lim.merge(e, on=["sensor", "t_idx"], how="left")
    lim = _smooth(lim, ["ewma_mean", "ewma_sd"], s.smoothing_window)
    lim["ewma_sd"] = np.maximum(lim["ewma_sd"].fillna(0.05), 0.05)
    lim["ewma_lcl"] = lim["ewma_mean"] - s.ewma_k * lim["ewma_sd"]
    lim["ewma_ucl"] = lim["ewma_mean"] + s.ewma_k * lim["ewma_sd"]
    return lim.sort_values(["sensor", "t_idx"]).reset_index(drop=True)


def _standardize(readings: pd.DataFrame, limits: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Attach limits; add z (Shewhart statistic) and EWMA (in z units)."""
    df = readings.merge(limits.drop(columns=["t_hours"]), on=["sensor", "t_idx"], how="left")
    df["missing"] = df["value"].isna()
    df["has_limits"] = df["mean"].notna()
    df["z"] = (df["value"] - df["mean"]) / df["sd"]
    return _add_ewma(df, s.ewma_lambda)


def _critical_values(df: pd.DataFrame, min_run: int) -> dict[str, float]:
    """For one batch: the largest k at which it would still raise an alarm,
    i.e. the max over windows of min_run consecutive points of min(|stat|),
    where all points in the window are on the same side. Max over sensors."""
    df = df.assign(ewma_z=(df["ewma"] - df["ewma_mean"]) / df["ewma_sd"])
    out = {}
    for method, col in (("shewhart", "z"), ("ewma", "ewma_z")):
        best = 0.0
        for _, g in df.groupby("sensor", sort=False):
            x = g[col]
            for signed in (x, -x):
                m = signed.rolling(min_run).min().max()
                if pd.notna(m):
                    best = max(best, float(m))
        out[method] = best
    return out


def calibrate(readings: pd.DataFrame, baseline_ids, min_sigma: dict[str, float],
              s: Settings) -> tuple[Settings, pd.DataFrame]:
    """Leave-one-out calibration on baseline batches only (test data is never used).

    For each baseline batch, learn limits from the OTHER baseline batches and
    find its critical value (largest k that would still alarm). Choose k so at
    most target_false_alarm_rate of baseline batches would alarm, never below
    the configured textbook value. Returns (calibrated settings, per-batch table).
    """
    ids = list(baseline_ids)
    rows = []
    for b in ids:
        lim = control_limits(readings, [x for x in ids if x != b], min_sigma, s)
        std = _standardize(readings[readings["batch_id"] == b], lim, s)
        rows.append({"batch_id": b, **_critical_values(std, s.min_run)})
    crit = pd.DataFrame(rows)
    allowed = int(np.floor(s.target_false_alarm_rate * len(ids)))  # batches allowed to alarm
    new = {}
    for method, textbook in (("shewhart", s.sigma_k), ("ewma", s.ewma_k)):
        c = np.sort(crit[method].to_numpy())[::-1]
        k = np.ceil(c[allowed] * 100) / 100 if allowed < len(c) else textbook
        new[method] = float(max(textbook, k))
    calibrated = Settings(**{**s.__dict__, "sigma_k": new["shewhart"], "ewma_k": new["ewma"]})
    return calibrated, crit


def evaluate(readings: pd.DataFrame, limits: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Score readings against the limits. Adds flag and alarm columns per reading."""
    df = _standardize(readings, limits, s)

    df["shewhart_flag"] = (df["value"] > df["ucl"]) | (df["value"] < df["lcl"])
    df["shewhart_side"] = np.sign(df["z"]).fillna(0)
    df["ewma_flag"] = (df["ewma"] > df["ewma_ucl"]) | (df["ewma"] < df["ewma_lcl"])
    df["ewma_side"] = np.sign(df["ewma"] - df["ewma_mean"]).fillna(0)

    for m in ("shewhart", "ewma"):
        df[f"{m}_alarm"] = False
    df = df.reset_index(drop=True)
    for m in ("shewhart", "ewma"):
        for _, g in df.groupby(["batch_id", "sensor"], sort=False):
            for i0, i1, _side in _runs(g[f"{m}_flag"].to_numpy(), g[f"{m}_side"].to_numpy(), s.min_run):
                df.loc[g.index[i0:i1], f"{m}_alarm"] = True
    return df


def _runs(flag: np.ndarray, side: np.ndarray, min_run: int):
    """Yield (start, stop, side) for runs of >= min_run consecutive same-side flags.
    A missing reading (flag False) breaks a run."""
    state = np.where(flag, side, 0).astype(int)
    i, n = 0, len(state)
    while i < n:
        if state[i] == 0:
            i += 1
            continue
        j = i
        while j < n and state[j] == state[i]:
            j += 1
        if j - i >= min_run:
            yield i, j, state[i]
        i = j


def alarm_events(scored: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Collapse alarm points into one row per event (for the `alarms` table)."""
    rows = []
    for (bid, sensor), g in scored.groupby(["batch_id", "sensor"], sort=False):
        t = g["t_hours"].to_numpy()
        for m in ("shewhart", "ewma"):
            for i0, i1, side in _runs(g[f"{m}_flag"].to_numpy(), g[f"{m}_side"].to_numpy(), s.min_run):
                rows.append({"batch_id": bid, "sensor": sensor, "method": m,
                             "start_h": float(t[i0]), "end_h": float(t[i1 - 1]),
                             "n_points": int(i1 - i0), "side": "high" if side > 0 else "low"})
    cols = ["batch_id", "sensor", "method", "start_h", "end_h", "n_points", "side"]
    return pd.DataFrame(rows, columns=cols)
