-- Per-batch, per-sensor summary.
-- Pass :batch_id = NULL for every batch.
SELECT
    r.batch_id,
    b.role,
    b.true_status,
    r.sensor,
    l.unit,
    MAX(r.t_hours)                         AS duration_h,
    COUNT(*)                               AS n_expected,
    COUNT(r.value)                         AS n_present,
    COUNT(*) - COUNT(r.value)              AS n_missing,
    ROUND(MIN(r.value), 3)                 AS min_value,
    ROUND(AVG(r.value), 3)                 AS mean_value,
    ROUND(MAX(r.value), 3)                 AS max_value,
    SUM(CASE WHEN r.value < l.low OR r.value > l.high THEN 1 ELSE 0 END) AS n_out_of_spec,
    (SELECT COUNT(*) FROM alarms a
      WHERE a.batch_id = r.batch_id AND a.sensor = r.sensor) AS n_alarms
FROM readings r
JOIN batches b       ON b.batch_id = r.batch_id
JOIN sensor_limits l ON l.sensor   = r.sensor
WHERE (:batch_id IS NULL OR r.batch_id = :batch_id)
GROUP BY r.batch_id, r.sensor
ORDER BY r.batch_id, r.sensor;
