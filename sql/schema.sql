-- One database per data source (synthetic or IndPenSim).

-- Each batch, and whether it is used to learn limits ('baseline') or only scored ('test').
-- true_status is the ground truth ('normal' or 'fault'), used only for validation.
CREATE TABLE IF NOT EXISTS batches (
    batch_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('baseline', 'test')),
    true_status TEXT NOT NULL CHECK (true_status IN ('normal', 'fault')),
    notes       TEXT
);

-- Sensor metadata and spec limits, copied from config/sensor_limits.json.
CREATE TABLE IF NOT EXISTS sensor_limits (
    sensor TEXT PRIMARY KEY,
    label  TEXT NOT NULL,
    unit   TEXT NOT NULL,
    low    REAL,
    high   REAL
);

-- Long format: one row per batch, sensor and time point.
-- value is NULL when a reading is missing.
CREATE TABLE IF NOT EXISTS readings (
    batch_id TEXT    NOT NULL REFERENCES batches(batch_id),
    sensor   TEXT    NOT NULL REFERENCES sensor_limits(sensor),
    t_idx    INTEGER NOT NULL,          -- sample number from batch start
    t_hours  REAL    NOT NULL,          -- hours from batch start
    value    REAL,
    PRIMARY KEY (batch_id, sensor, t_idx)
) WITHOUT ROWID;

-- Known (injected or labelled) faults: the answer key for validation.
-- sensor is NULL when the fault is a process fault not tied to one sensor.
CREATE TABLE IF NOT EXISTS faults (
    batch_id    TEXT NOT NULL REFERENCES batches(batch_id),
    sensor      TEXT,
    kind        TEXT NOT NULL,
    start_h     REAL NOT NULL,
    end_h       REAL NOT NULL,
    description TEXT
);

-- Time-varying control limits learned from baseline batches.
CREATE TABLE IF NOT EXISTS control_limits (
    sensor     TEXT    NOT NULL,
    t_idx      INTEGER NOT NULL,
    t_hours    REAL    NOT NULL,
    n_batches  INTEGER NOT NULL,
    mean       REAL    NOT NULL,
    sd         REAL    NOT NULL,
    lcl        REAL    NOT NULL,
    ucl        REAL    NOT NULL,
    ewma_mean  REAL,
    ewma_sd    REAL,
    ewma_lcl   REAL,
    ewma_ucl   REAL,
    PRIMARY KEY (sensor, t_idx)
) WITHOUT ROWID;

-- Thresholds actually used, and how they were chosen.
CREATE TABLE IF NOT EXISTS calibration (
    method          TEXT PRIMARY KEY CHECK (method IN ('shewhart', 'ewma')),
    textbook_k      REAL NOT NULL,
    calibrated_k    REAL NOT NULL,
    n_baseline      INTEGER NOT NULL,
    baseline_alarming_at_textbook INTEGER NOT NULL,
    target_rate     REAL NOT NULL
);

-- Alarm events found by the monitoring step: runs of consecutive flagged points.
CREATE TABLE IF NOT EXISTS alarms (
    batch_id TEXT    NOT NULL,
    sensor   TEXT    NOT NULL,
    method   TEXT    NOT NULL CHECK (method IN ('shewhart', 'ewma')),
    start_h  REAL    NOT NULL,
    end_h    REAL    NOT NULL,
    n_points INTEGER NOT NULL,
    side     TEXT    NOT NULL CHECK (side IN ('high', 'low'))
);
