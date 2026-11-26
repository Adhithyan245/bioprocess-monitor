-- One row per batch: alarms, missing readings and out-of-spec readings.
WITH r AS (
    SELECT r.batch_id,
           COUNT(*) - COUNT(r.value) AS n_missing,
           SUM(CASE WHEN r.value < l.low OR r.value > l.high THEN 1 ELSE 0 END) AS n_out_of_spec,
           MAX(r.t_hours) AS duration_h
    FROM readings r JOIN sensor_limits l ON l.sensor = r.sensor
    GROUP BY r.batch_id
),
a AS (
    SELECT batch_id,
           COUNT(*) AS n_alarms,
           MIN(start_h) AS first_alarm_h,
           GROUP_CONCAT(DISTINCT sensor) AS alarm_sensors
    FROM alarms GROUP BY batch_id
)
SELECT b.batch_id, b.role, b.true_status, r.duration_h,
       COALESCE(a.n_alarms, 0) AS n_alarms, a.first_alarm_h, a.alarm_sensors,
       r.n_missing, r.n_out_of_spec
FROM batches b
JOIN r USING (batch_id)
LEFT JOIN a USING (batch_id)
ORDER BY b.batch_id;
