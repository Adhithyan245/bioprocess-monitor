"""SYNTHETIC batch-fermentation data generator.

Everything here is made up. It is a simple, clearly labelled stand-in that
gives the test suite a known answer key: we inject each fault ourselves, so we
know exactly which batch, sensor and time it starts.

Model (100 h batch, one sample every 15 min):
  growth(t)  S-shaped (logistic) curve from 0 to 1; its timing varies by batch
  temperature  30 degC set point, rises slightly with growth (metabolic heat)
  pH           7.0, drifts down slightly as the culture grows
  DO           ~100 % saturation at the start, falls toward 30 % as cells use oxygen
  agitation    300 rpm, ramps toward 600 rpm to supply more oxygen
Every batch also has small random offsets and measurement noise, plus rare
random single missing readings (as from a flaky data link).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SENSORS = ["temperature", "ph", "dissolved_oxygen", "agitation"]
DURATION_H = 100.0
DT_H = 0.25

# kind -> (sensor, description). Sizes are chosen to be realistic, not trivial.
FAULT_TYPES = {
    "cooling_failure": ("temperature", "Cooling water valve sticks: temperature steps up 0.4 degC"),
    "base_pump_drift": ("ph", "Base dosing pump weakens: pH drifts down 0.004 per hour"),
    "do_probe_fouling": ("dissolved_oxygen", "DO probe membrane fouls: reading drifts down 0.15 % per hour"),
    "agitator_stall": ("agitation", "Agitator speed controller freezes at its current speed"),
    "sensor_dropout": (None, "Data link to one sensor drops for 3-6 hours (readings missing)"),
}


def _normal_batch(rng: np.random.Generator, t: np.ndarray) -> dict[str, np.ndarray]:
    t_mid = 40 + rng.normal(0, 2.0)            # when growth is fastest (h)
    k = 0.12 * (1 + rng.normal(0, 0.05))       # growth steepness
    growth = 1 / (1 + np.exp(-k * (t - t_mid)))
    n = len(t)
    return {
        "temperature": 30.0 + 0.15 * growth + rng.normal(0, 0.03) + rng.normal(0, 0.05, n),
        "ph": 7.0 - 0.15 * growth + rng.normal(0, 0.008) + rng.normal(0, 0.01, n),
        "dissolved_oxygen": 100 - 70 * growth + rng.normal(0, 1.0) + rng.normal(0, 1.0, n),
        "agitation": 300 + 300 * growth + rng.normal(0, 4.0) + rng.normal(0, 3.0, n),
    }


def _inject(kind: str, data: dict, t: np.ndarray, start: float, rng) -> tuple[str, float, float]:
    """Apply a fault in place. Returns (sensor, start_h, end_h)."""
    after = t >= start
    if kind == "cooling_failure":
        data["temperature"][after] += 0.4
    elif kind == "base_pump_drift":
        data["ph"][after] -= 0.004 * (t[after] - start)
    elif kind == "do_probe_fouling":
        data["dissolved_oxygen"][after] -= 0.15 * (t[after] - start)
    elif kind == "agitator_stall":
        i0 = int(np.argmax(after))
        data["agitation"][after] = data["agitation"][i0] + rng.normal(0, 3.0, after.sum())
    elif kind == "sensor_dropout":
        sensor = SENSORS[rng.integers(len(SENSORS))]
        end = start + rng.uniform(3, 6)
        data[sensor][(t >= start) & (t <= end)] = np.nan
        return sensor, start, float(t[t <= end][-1])
    return FAULT_TYPES[kind][0], start, float(t[-1])


def generate(n_baseline: int = 20, n_normal_test: int = 10, faults_per_type: int = 2,
             missing_rate: float = 0.002, seed: int = 42):
    """Return (batches, readings, faults) DataFrames in the biomon schema."""
    rng = np.random.default_rng(seed)
    t = np.round(np.arange(0, DURATION_H + DT_H / 2, DT_H), 4)
    t_idx = np.arange(len(t))

    plan = ([("baseline", None)] * n_baseline + [("test", None)] * n_normal_test
            + [("test", k) for k in FAULT_TYPES for _ in range(faults_per_type)])

    batches, frames, faults = [], [], []
    for i, (role, kind) in enumerate(plan, start=1):
        bid = f"SYN-{i:03d}"
        data = _normal_batch(rng, t)
        # Rare random single missing readings in every batch (not a process fault).
        for s in SENSORS:
            data[s][rng.random(len(t)) < missing_rate] = np.nan
        if kind:
            start = float(np.round(rng.uniform(30, 70) / DT_H) * DT_H)
            sensor, s_h, e_h = _inject(kind, data, t, start, rng)
            faults.append({"batch_id": bid, "sensor": sensor, "kind": kind,
                           "start_h": s_h, "end_h": e_h, "description": FAULT_TYPES[kind][1]})
        batches.append({"batch_id": bid, "source": "synthetic", "role": role,
                        "true_status": "fault" if kind else "normal",
                        "notes": f"SYNTHETIC; injected fault: {kind}" if kind else "SYNTHETIC; normal"})
        for s in SENSORS:
            frames.append(pd.DataFrame({"batch_id": bid, "sensor": s, "t_idx": t_idx,
                                        "t_hours": t, "value": data[s]}))

    return pd.DataFrame(batches), pd.concat(frames, ignore_index=True), pd.DataFrame(faults)
