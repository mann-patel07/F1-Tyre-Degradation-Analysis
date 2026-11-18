# Pre-registration: telemetry for all dry 2025 races

The Bahrain case study is finished and its result is known. Telemetry for the other 2025 races has not been downloaded or looked at.

## Procedure
For every 2025 race with status "used" (dry), Bahrain first, repeat the Bahrain procedure unchanged: 25 mini-sectors by relative distance from SessionTime, laps with a mismatch above 1.0 s dropped, kept laps rescaled to the official lap time, compound minimum before and after the mismatch filter, reference lap = fastest kept lap, class STRAIGHT if the minimum reference throttle in the mini-sector is at least 95 percent, otherwise CORNER (no samples means CORNER). A second label, class3: BRAKING if any reference sample in the mini-sector has Brake true, else CORNER_NO_BRAKE if the minimum throttle is below 95 percent, else STRAIGHT (no samples: CORNER_NO_BRAKE).

M1 is fitted per mini-sector. The linearity check (mini-sector rates sum to the lap-time rate, tolerance 1e-6) must hold for every race.

## Metrics
Per race and compound: total, corner and straight rates, corner and straight time on the reference lap, and the density difference G = corner_rate / corner_time minus straight_rate / straight_time (undefined if a class is empty). The same densities for class3.

Primary metric T1: for each race take the compound with the most kept laps, then the mean of G over races where it is defined, with the race-level bootstrap interval (10000 resamples, seed 42). Also the number of races, the number with G above zero, and the races left out with the reason. Secondary: the mean of each class3 density with intervals.

## Regression check
For Bahrain, the new mini-sector file and fits must equal the earlier Bahrain files within 1e-6.

These choices were fixed before this telemetry was downloaded and were not changed afterward.
