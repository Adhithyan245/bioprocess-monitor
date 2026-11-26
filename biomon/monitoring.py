"""Statistical monitoring: time-varying Shewhart limits, EWMA drift detection,
missing-reading flags, and grouping of flags into alarm events.

Terms used throughout:
  flag   one reading outside a limit (shown as a marker on the chart)
  alarm  min_run or more consecutive flags on the same side (a real "event")
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

import numpy as np
import pandas as pd

METHODS = ("shewhart", "ewma")


@dataclass
class Settings:
    sigma_k: float = 3.0           # Shewhart band = mean +/- k * sd (textbook default / floor)
    ewma_lambda: float = 0.2       # EWMA weight on the newest point (0-1)
    ewma_k: float = 3.0            # EWMA band = mean +/- k * sd of baseline EWMA curves (default / floor)
    min_run: int = 3               # consecutive same-side flags needed to raise an alarm
    min_baseline_batches: int = 5  # don't draw limits where fewer good batches exist
    smoothing_window: int = 5      # samples; smooths the limit curves over time
    calibrate: bool = True         # widen sigma_k / ewma_k using leave-one-out on baseline
    target_false_alarm_rate: float = 0.05  # share of baseline batches allowed to alarm
    # Per-sensor thresholds set by calibration; sensors not listed use sigma_k / ewma_k.
    shewhart_k_by_sensor: dict = field(default_factory=dict)
    ewma_k_by_sensor: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in cfg.get("monitoring", {}).items() if k in known})

    def k(self, method: str, sensor: str) -> float:
        if method == "shewhart":
            return self.shewhart_k_by_sensor.get(sensor, self.sigma_k)
        return self.ewma_k_by_sensor.get(sensor, self.ewma_k)

    def with_k(self, method: str, by_sensor: dict) -> "Settings":
        return Settings(**{**self.__dict__, f"{method}_k_by_sensor": dict(by_sensor)})


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


def _smooth_per_sensor(df: pd.DataFrame, cols: list[str], default: int,
                       windows: dict[str, int] | None) -> pd.DataFrame:
    """Smooth each sensor with its own window (e.g. 1 = none, for stepped set-point signals)."""
    windows = windows or {}
    parts = [_smooth(g.copy(), cols, windows.get(sensor, default))
             for sensor, g in df.groupby("sensor", sort=False)]
    return pd.concat(parts) if parts else df


def control_limits(readings: pd.DataFrame, baseline_ids, min_sigma: dict[str, float],
                   s: Settings, smoothing: dict[str, int] | None = None) -> pd.DataFrame:
    """Learn time-varying Shewhart and EWMA limits from baseline (known-good) batches.
    `smoothing` optionally overrides the smoothing window per sensor."""
    base = readings[readings["batch_id"].isin(set(baseline_ids))]
    lim = (base.groupby(["sensor", "t_idx"])
               .agg(t_hours=("t_hours", "first"), n_batches=("value", "count"),
                    mean=("value", "mean"), sd=("value", "std"))
               .reset_index())
    lim = lim[lim["n_batches"] >= s.min_baseline_batches].copy()
    lim = _smooth_per_sensor(lim, ["mean", "sd"], s.smoothing_window, smoothing)
    lim["sd"] = np.maximum(lim["sd"], lim["sensor"].map(min_sigma).fillna(0))
    lim["k_shewhart"] = lim["sensor"].map(lambda x: s.k("shewhart", x))
    lim["k_ewma"] = lim["sensor"].map(lambda x: s.k("ewma", x))
    lim["lcl"] = lim["mean"] - lim["k_shewhart"] * lim["sd"]
    lim["ucl"] = lim["mean"] + lim["k_shewhart"] * lim["sd"]

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
    lim = _smooth_per_sensor(lim, ["ewma_mean", "ewma_sd"], s.smoothing_window, smoothing)
    lim["ewma_sd"] = np.maximum(lim["ewma_sd"].fillna(0.05), 0.05)
    lim["ewma_lcl"] = lim["ewma_mean"] - lim["k_ewma"] * lim["ewma_sd"]
    lim["ewma_ucl"] = lim["ewma_mean"] + lim["k_ewma"] * lim["ewma_sd"]
    return lim.sort_values(["sensor", "t_idx"]).reset_index(drop=True)


def _standardize(readings: pd.DataFrame, limits: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Attach limits; add z (Shewhart statistic) and EWMA (in z units)."""
    df = readings.merge(limits.drop(columns=["t_hours"]), on=["sensor", "t_idx"], how="left")
    df["missing"] = df["value"].isna()
    df["has_limits"] = df["mean"].notna()
    df["z"] = (df["value"] - df["mean"]) / df["sd"]
    return _add_ewma(df, s.ewma_lambda)


def _critical_values(df: pd.DataFrame, min_run: int) -> list[dict]:
    """For one batch, per sensor: the largest k at which it would still raise an
    alarm, i.e. the max over windows of min_run consecutive points of min(|stat|),
    where all points in the window are on the same side (0 if it never could)."""
    df = df.assign(ewma_z=(df["ewma"] - df["ewma_mean"]) / df["ewma_sd"])
    rows = []
    for sensor, g in df.groupby("sensor", sort=False):
        row = {"sensor": sensor}
        for method, col in (("shewhart", "z"), ("ewma", "ewma_z")):
            best = 0.0
            for signed in (g[col], -g[col]):
                m = signed.rolling(min_run).min().max()
                if pd.notna(m):
                    best = max(best, float(m))
            row[method] = best
        rows.append(row)
    return rows


def choose_sensor_k(crit: pd.DataFrame, method: str, textbook: float, target: float) -> dict[str, float]:
    """Pick one k per sensor so that, across ALL sensors together, at most
    `target` of baseline batches would raise an alarm with this method.

    Every sensor's k sits at the same rank m among its own critical values
    (m = 0: the largest, so no baseline batch alarms on it). m is raised as long
    as the combined number of alarming baseline batches stays within budget.
    No k goes below the textbook value."""
    wide = crit.pivot(index="batch_id", columns="sensor", values=method).fillna(0.0)
    n = len(wide)
    allowed = int(np.floor(target * n))
    ordered = {s: np.sort(wide[s].to_numpy())[::-1] for s in wide.columns}

    def ks_at(m: int) -> dict[str, float]:
        return {s: float(max(textbook, np.ceil(c[m] * 100) / 100)) for s, c in ordered.items()}

    best = ks_at(0)
    for m in range(1, n):
        ks = ks_at(m)
        alarming = (wide > pd.Series(ks)).any(axis=1).sum()
        if alarming > allowed:
            break
        best = ks
    return best


def calibrate(readings: pd.DataFrame, baseline_ids, min_sigma: dict[str, float],
              s: Settings, smoothing: dict[str, int] | None = None) -> tuple[Settings, pd.DataFrame]:
    """Leave-one-out calibration on baseline batches only (test data is never used).

    For each baseline batch, learn limits from the OTHER baseline batches and
    find its critical value per sensor (largest k that would still alarm). Then
    choose a k per sensor and method (see choose_sensor_k). Returns
    (calibrated settings, table of critical values: batch_id, sensor, shewhart, ewma).
    """
    ids = list(baseline_ids)
    rows = []
    for b in ids:
        lim = control_limits(readings, [x for x in ids if x != b], min_sigma, s, smoothing)
        std = _standardize(readings[readings["batch_id"] == b], lim, s)
        rows += [{"batch_id": b, **r} for r in _critical_values(std, s.min_run)]
    crit = pd.DataFrame(rows)
    calibrated = s
    for method, textbook in (("shewhart", s.sigma_k), ("ewma", s.ewma_k)):
        calibrated = calibrated.with_k(
            method, choose_sensor_k(crit, method, textbook, s.target_false_alarm_rate))
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
