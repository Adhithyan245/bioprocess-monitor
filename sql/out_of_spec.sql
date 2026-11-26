-- Readings outside the spec limits in config/sensor_limits.json.
SELECT
    r.batch_id, r.sensor, r.t_hours, r.value, l.low, l.high,
    CASE WHEN r.value < l.low THEN 'low' ELSE 'high' END AS side
FROM readings r
JOIN sensor_limits l ON l.sensor = r.sensor
WHERE (r.value < l.low OR r.value > l.high)
  AND (:batch_id IS NULL OR r.batch_id = :batch_id)
ORDER BY r.batch_id, r.sensor, r.t_hours;
