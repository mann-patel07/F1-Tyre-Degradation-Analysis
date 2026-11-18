# Pre-registration: replication on 2022 to 2024

The 2025 study is finished and its result is known. Seasons 2022, 2023 and 2024 have not been downloaded or looked at. The same design, code and constants are applied to them with no change.

## Data
Race sessions ("R") of seasons 2022, 2023 and 2024 from FastF1, the same columns and conversions as for 2025. Wet races (any lap on INTERMEDIATE or WET) are excluded. Dry compound names other than SOFT, MEDIUM, HARD are dropped by the existing clean-lap rule and counted, never mapped.

## Metrics
- R1: mean of MAE_M0 minus MAE_M1 over all validation-eligible races of 2022, 2023 and 2024 pooled, with the race-level bootstrap interval (10000 resamples, seed 42, 2.5 and 97.5 percentiles). Primary replication metric.
- R2: the same for MAE_M1 minus MAE_M2.
- Races pooled, races where M1 beat M0, races where M2 beat M1, pooled test MAE of each model.
- Per season: D1 and D2 with intervals, eligible races, wet races, failed loads.
- ALL4_D1 and ALL4_D2: means over 2022 to 2025 together, shown for reference only.
- Sensitivity tables (train fractions 0.50, 0.60, 0.70 and the clean-air subset) per season, as checks only.

## Decision wording
Exactly one sentence is chosen by the R1 interval:
- Lower bound above zero: "The replication interval for R1 is above zero: the 2025 result held in 2022 to 2024."
- Interval includes zero: "The replication interval for R1 includes zero: the 2025 result was not confirmed in 2022 to 2024."
- Upper bound below zero: "The replication interval for R1 is below zero: the 2025 result reversed in 2022 to 2024."

## Rate-limit rule
On RateLimitExceededError wait 900 seconds and retry the same session, at most 12 waits per session. Any other failure is retried 3 times with 30 seconds between tries, then recorded as load_failed. A failed race stays failed and is reported.

These choices were fixed before any 2022 to 2024 data was downloaded and were not changed afterward.
