-- Gaps of missing readings, grouped into continuous stretches.
-- "Gaps and islands" trick: within a run of consecutive missing samples,
-- t_idx minus its row number is constant, so it works as a group key.
WITH missing AS (
    SELECT
        batch_id, sensor, t_idx, t_hours,
        t_idx - ROW_NUMBER() OVER (PARTITION BY batch_id, sensor ORDER BY t_idx) AS grp
    FROM readings
    WHERE value IS NULL
      AND (:batch_id IS NULL OR batch_id = :batch_id)
)
SELECT
    batch_id, sensor,
    MIN(t_hours) AS gap_start_h,
    MAX(t_hours) AS gap_end_h,
    COUNT(*)     AS n_missing
FROM missing
GROUP BY batch_id, sensor, grp
ORDER BY batch_id, sensor, gap_start_h;
