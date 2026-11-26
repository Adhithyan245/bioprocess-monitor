-- Readings outside the time-varying Shewhart control limits (mean +/- k*sd of
-- baseline batches at the same time point).
SELECT
    r.batch_id, r.sensor, r.t_hours, r.value,
    ROUND(c.lcl, 4) AS lcl,
    ROUND(c.ucl, 4) AS ucl,
    ROUND((r.value - c.mean) / c.sd, 2) AS z_score
FROM readings r
JOIN control_limits c ON c.sensor = r.sensor AND c.t_idx = r.t_idx
WHERE (r.value < c.lcl OR r.value > c.ucl)
  AND (:batch_id IS NULL OR r.batch_id = :batch_id)
ORDER BY r.batch_id, r.sensor, r.t_hours;
