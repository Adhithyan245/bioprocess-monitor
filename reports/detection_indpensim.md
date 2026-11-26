# Detection results: indpensim

Data: IndPenSim public dataset (Goldrick et al., CC BY 4.0). Generated 2026-11-26 by `python -m biomon.build indpensim`.

Only held-out test batches are scored; baseline batches were used to learn the limits.

## Summary

- Faulty batches detected: **5 of 10**
- Normal batches with at least one false alarm: **4 of 45**
- Median detection delay after fault onset: **0.0 h**
- Point-level flag rate on normal test batches: Shewhart 0.09%, EWMA 0.07% of 310,500 readings (flags are single points; alarms need 3 in a row)

## Thresholds used

One k per sensor and method, calibrated by leave-one-out on baseline batches only, so that across all sensors together at most 5% of baseline batches would alarm (never below the textbook value). The last two columns count baseline batches that would alarm on that sensor at each k.

| method | sensor | textbook_k | calibrated_k | alarming_at_textbook | alarming_at_calibrated |
|---|---|---|---|---|---|
| shewhart | aeration | 3 | 3 | 0 | 0 |
| shewhart | agitation | 3 | 3 | 0 | 0 |
| shewhart | dissolved_oxygen | 3 | 6.07 | 4 | 0 |
| shewhart | ph | 3 | 84.7 | 22 | 0 |
| shewhart | pressure | 3 | 3 | 0 | 0 |
| shewhart | temperature | 3 | 20.9 | 25 | 0 |
| ewma | aeration | 3 | 3 | 0 | 0 |
| ewma | agitation | 3 | 3 | 0 | 0 |
| ewma | dissolved_oxygen | 3 | 6.28 | 4 | 0 |
| ewma | ph | 3 | 156 | 27 | 0 |
| ewma | pressure | 3 | 3 | 0 | 0 |
| ewma | temperature | 3 | 19.3 | 27 | 0 |

## Fault batches

| batch_id | fault_kind | fault_sensor | onset_h | detected | method | delay_h | false_alarms |
|---|---|---|---|---|---|---|---|
| IPS-091 | process_fault |  | 20 | False |  |  | 0 |
| IPS-092 | process_fault |  | 80 | False |  |  | 0 |
| IPS-093 | process_fault |  | 70 | True | shewhart (temperature) | 8 | 0 |
| IPS-094 | process_fault |  | 20 | True | shewhart (aeration) | 0 | 0 |
| IPS-095 | process_fault |  | 20 | False |  |  | 0 |
| IPS-096 | process_fault |  | 70 | True | shewhart (temperature) | 8.6 | 0 |
| IPS-097 | process_fault |  | 20 | False |  |  | 0 |
| IPS-098 | process_fault |  | 80 | False |  |  | 0 |
| IPS-099 | process_fault |  | 20 | True | shewhart (aeration) | 0 | 0 |
| IPS-100 | process_fault |  | 20 | True | shewhart (aeration) | 0 | 0 |

## Normal test batches with false alarms

| batch_id | false_alarms | alarm_sensors |
|---|---|---|
| IPS-020 | 6 | temperature |
| IPS-042 | 1 | dissolved_oxygen |
| IPS-044 | 23 | dissolved_oxygen |
| IPS-062 | 2 | temperature |

## Trade-off: what other thresholds would have given

If ONE k were shared by every sensor and both methods (the previous approach), scored on the same test batches. Shown for transparency only; the thresholds above were NOT chosen from this table.

| k | faults_detected | normal_batches_false_alarm |
|---|---|---|
| 3 | 10/10 | 38/45 |
| 4 | 10/10 | 25/45 |
| 5 | 9/10 | 20/45 |
| 7 | 7/10 | 11/45 |
| 10 | 7/10 | 8/45 |
| 20 | 7/10 | 3/45 |
| 40 | 7/10 | 0/45 |
| 70 | 5/10 | 0/45 |
| 110 | 5/10 | 0/45 |
