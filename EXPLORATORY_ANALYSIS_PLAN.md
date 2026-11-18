# Exploratory analysis plan

These analyses are descriptive and exploratory. They were not pre-registered. The 2025 data had already been seen when this plan was written. The plan was written before any of these results was computed.

## Strategy module (all four seasons, all races that loaded, including wet)
Constants: TYRE_DATA_MAX_MISSING 0.05, REF_WINDOW_LAPS 3, REF_MIN_STOPS 3, FINISH_FRACTION 0.90, UNDERCUT_GAP_S 2.0, COVER_GAP_S 3.0, COVER_LOOKBACK_LAPS 2, UNDERCUT_RESPONSE_LAPS 5, CYCLE_LAPS_AFTER 5, MIN_COMPARISON_DRIVERS 3.

Limit: what a team planned is not public. A reference strategy is defined from what the field did under green. Tyre changes are tagged with the circumstances the data shows. Sentences use "consistent with" for motive.

- Status codes in TrackStatus: 1 clear, 2 yellow, 4 safety car, 5 red flag, 6 and 7 virtual safety car. "Contains" means the digit appears. Green means the string is exactly "1".
- Rows with null Stint or LapNumber are not used. A race is tyre_data_incomplete if more than 5 percent of rows have null Stint or Compound; it is excluded from season summaries.
- Stint boundary: consecutive usable laps of a driver with different Stint (earlier lap in-lap, later lap out-lap). Renumbering artifact: neither pit flag, same compound, out-lap TyreLife equals in-lap TyreLife plus 1; not a tyre change. Every other boundary is a tyre change; a pit stop if either pit flag is set, otherwise a change without a pit lap.
- Pit lane pass without a tyre change: LapNumber at least 2, pit-out flag, not the out-lap of a tyre change.
- Reference strategy: among drivers who completed the race (largest lap at least 90 percent of the race maximum), the most common number of tyre changes (tie to the smaller); the reference lap for stop k is the median in-lap among completing drivers with that count whose stop k in-lap is green, undefined with fewer than 3 stops. Reference compound sequence: most common ordered list, all ties reported.
- Rivals: car ahead and behind from Position on lap n minus 1; gap is the absolute lap_end_s difference on that lap. Missing values make the rival undefined.
- Tags: RED_FLAG, WEATHER_TO_WET, WEATHER_TO_DRY, WET_TO_WET, UNKNOWN_COMPOUND, SAFETY_CAR, VIRTUAL_SAFETY_CAR, COVER, UNDERCUT_ATTEMPT, ON_REFERENCE, EARLIER_THAN_REFERENCE, LATER_THAN_REFERENCE, EXTRA_STOP, NO_REFERENCE, UNFLAGGED_CHANGE as defined in the instructions of the expansion.
- Primary circumstance, first that applies: RED_FLAG, WEATHER_TO_WET, WEATHER_TO_DRY, WET_TO_WET, SAFETY_CAR, VIRTUAL_SAFETY_CAR, COVER, UNDERCUT_ATTEMPT, ON_REFERENCE, EXTRA_STOP, EARLIER_THAN_REFERENCE, LATER_THAN_REFERENCE, UNFLAGGED_CHANGE, UNKNOWN_COMPOUND, NO_REFERENCE.
- Driver label: MATCHES_REFERENCE, DIFFERS, DID_NOT_COMPLETE.
- Time cost of a stop: (in-lap time plus out-lap time) minus the median over at least 3 comparison drivers of their lap n plus lap n+1, comparison drivers having no tyre change near and no pit flag on those laps.
- Position change over the stop cycle: Position on lap n-1 minus Position on lap n+1+5. Descriptive only.
- Undercut outcome: SUCCEEDED, FAILED or NOT_RESOLVED from positions on lap m+1 after the car ahead stops within 5 laps.
- Season summaries: shares by primary circumstance; median stop cost for green, safety car, virtual safety car with race-level bootstrap intervals (10000 resamples, seed 42) for each median and the differences; undercut counts; share of completing drivers labeled DIFFERS.

## Corrected pace module (dry races, all four seasons)
Constants: MIN_DRIVER_LAPS 20, MIN_RACES_TEAM 8, MIN_RACES_TEAMMATE 5, COMPOUND_COMPARE_AGE 5.
- Per race fit M1 on clean laps after the compound minimum. Driver effect is the driver coefficient (0 for the reference driver). Keep drivers with at least 20 laps. pace = effect minus the mean effect over kept drivers.
- Team pace is the mean pace of its kept drivers. Team ranking, teammate differences, development slope on round number and compound comparison at tyre age 5 per season, with race-level bootstrap intervals.
- Caveats: car and driver are not separated; traffic, damage, team orders and pace management are in the numbers; wet races are left out; fitted values under this model.

## Cross-module links
Per dry race, deg_index is the lap-weighted mean of fitted degradation rates. Spearman correlations (with race counts and p-values, per season and pooled) with the reference number of stops, the share of completing drivers labeled DIFFERS, the forecast gain, and, for 2025, the density difference G. No claim is made from any single correlation.
