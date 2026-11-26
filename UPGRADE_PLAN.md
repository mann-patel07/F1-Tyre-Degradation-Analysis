# Plan for the stint split

Date: 2026-11-26

Written before these results existed. The first version's analyses and numbers are unchanged.

## Question
How much of D1 comes from wear within a stint, and how much from knowing when each driver changed tyres?

## Method
- Same races, cleaning, cutoff (60 percent of race distance), models M0, M1, M2 and forecasts as the first version. Nothing is refitted differently.
- Each test lap is "continuing" if its driver and stint number also appear among that race's training laps (the stint began before the cutoff), and "new stint" otherwise.
- For each race and each group with at least 20 test laps: MAE of M0, M1 and M2, D1 = MAE(M0) - MAE(M1), and D2 = MAE(M1) - MAE(M2).
- Over races: mean D1 and D2 for each group, with the same race-level bootstrap interval as the first version (10,000 resamples, seed 42), and the number of races where D1 is above zero.
- Done for 2025 and for 2022, 2023 and 2024 (the replication seasons), and pooled over 2022 to 2024.

## Reading
- D1 for continuing laps measures what tyre age adds within a stint, where no pit stop can happen. That is the closest this data gets to pure wear.
- D1 for new-stint laps also includes the reset at the pit stop.
- I report both, whatever they are.
