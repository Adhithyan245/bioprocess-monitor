# Detection results: indpensim

Data: IndPenSim public dataset (Goldrick et al., CC BY 4.0). Generated 2026-11-26 by `python -m biomon.build indpensim`.

Only held-out test batches are scored; baseline batches were used to learn the limits.

## Summary

- Faulty batches detected: **2 of 10**
- Normal batches with at least one false alarm: **0 of 45**
- Median detection delay after fault onset: **67.0 h**
- Point-level flag rate on normal test batches: Shewhart 0.00%, EWMA 0.00% of 207,000 readings (flags are single points; alarms need 3 in a row)

## Thresholds used

Calibrated by leave-one-out on baseline batches only (never below the textbook value):

| method | textbook_k | calibrated_k | n_baseline | baseline_alarming_at_textbook | target_rate |
|---|---|---|---|---|---|
| shewhart | 3 | 68.9 | 45 | 37 | 0.05 |
| ewma | 3 | 106 | 45 | 36 | 0.05 |

## Fault batches

| batch_id | fault_kind | fault_sensor | onset_h | detected | method | delay_h | false_alarms |
|---|---|---|---|---|---|---|---|
| IPS-091 | process_fault |  | 20 | False |  |  | 0 |
| IPS-092 | process_fault |  | 80 | True | ewma (ph) | 66.2 | 0 |
| IPS-093 | process_fault |  | 70 | False |  |  | 0 |
| IPS-094 | process_fault |  | 20 | False |  |  | 0 |
| IPS-095 | process_fault |  | 20 | False |  |  | 0 |
| IPS-096 | process_fault |  | 70 | False |  |  | 0 |
| IPS-097 | process_fault |  | 20 | False |  |  | 0 |
| IPS-098 | process_fault |  | 80 | True | ewma (ph) | 67.8 | 0 |
| IPS-099 | process_fault |  | 20 | False |  |  | 0 |
| IPS-100 | process_fault |  | 20 | False |  |  | 0 |

## Normal test batches with false alarms

None.

## Trade-off: what other thresholds would have given

Same k for Shewhart and EWMA, scored on the same test batches. Shown for transparency only; the thresholds above were NOT chosen from this table.

| k | faults_detected | normal_batches_false_alarm |
|---|---|---|
| 3 | 10/10 | 38/45 |
| 4 | 10/10 | 25/45 |
| 5 | 9/10 | 20/45 |
| 7 | 6/10 | 11/45 |
| 10 | 4/10 | 8/45 |
| 20 | 4/10 | 3/45 |
| 40 | 4/10 | 0/45 |
| 70 | 2/10 | 0/45 |
| 110 | 2/10 | 0/45 |
