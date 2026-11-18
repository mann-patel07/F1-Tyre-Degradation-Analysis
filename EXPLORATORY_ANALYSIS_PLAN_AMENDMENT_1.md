# Amendment 1 to the exploratory analysis plan

Date: 2026-11-17.

## What the rule was
A stint boundary was not a tyre change only when neither the in-lap nor the out-lap had a pit flag, the compound was the same, and the tyre age rose by exactly 1 (a renumbering artifact). With a pit flag on either lap the boundary counted as a tyre change.

## What it is now
A stint boundary where the compound is the same on both laps and the out-lap tyre age equals the in-lap tyre age plus 1 is never a tyre change, whatever the pit flags say, because the same tyre set is still on the car. With no pit flag it is a renumbering artifact, as before. With a pit flag on either lap it is a new kind, SAME_TYRE_CONTINUATION. It is written to `results/strategy/pit_passes.csv` in a new column `kind` (PIT_PASS for the earlier rows) and described only as "stint number changed with pit flags set, but the same tyre continued". It is never called a pit stop. `results/strategy/reference.csv` has a new column `same_tyre_continuations`. A boundary where either tyre age is null is decided by the earlier rules. Nothing else changed and no constant changed.

## Why
In the 2025 Canadian Grand Prix, most drivers get a new stint number on each of the last laps (67 to 70) with pit flags set, but the compound stays the same and the tyre age rises by 1 each lap. For example ALO has stints 4, 5, 6 and 7 on laps 67 to 70, all HARD, with tyre ages 18, 19, 20 and 21. The tyre did not change. The old rule counted each as a tyre change, which gave Canada a reference of 4 stops.

## Counts
Recounted from the lap files: 247 boundaries in all, matching the count that prompted this change. Per season: 2022 had 25, 2023 had 78, 2024 had 49 and 2025 had 95. The largest were 2025 Canada (49), 2025 Australia (43), 2024 Qatar (34), 2023 Austria (19) and 2023 São Paulo (17).

This change was made after the strategy results had been computed and seen. It fixes a data artifact and was not chosen to move any result in a particular direction.

## Before and after
| Number (all four seasons) | Before | After |
|---|---|---|
| Tyre changes counted in summaries (races with complete tyre data) | 3271 | 3024 |
| Safety car or virtual safety car share of tyre changes | 20.4 percent | 16.7 percent |
| Median stop cost under green (s) | 22.644 | 22.632 |
| Median stop cost under safety car (s) | 14.422 | 14.630 |
| Median stop cost under virtual safety car (s) | 17.126 | 17.126 |
| Green minus safety car (s, interval) | 8.222 (5.417 to 10.966) | 8.001 (5.290 to 10.869) |
| Undercut success share of resolved | 57.1 percent | 57.6 percent |
| Completing drivers labeled DIFFERS | 79.4 percent | 77.8 percent |

The full comparison, including the reference stop count of every race where it changed, is in `results/strategy_fix_comparison.csv`. The ON_REFERENCE window and REF_WINDOW_LAPS were not changed.
