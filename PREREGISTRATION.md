# Pre-registration

Written before any FastF1 session was loaded.

## Research question
At 60 percent race distance, using only laps already run, does a model with a tyre degradation term predict lap times for the rest of the race better than a model without one? In one race studied with car telemetry (Bahrain Grand Prix), where on the lap does the fitted degradation cost time?

## Season and session
Season 2025, Grand Prix sessions only ("R"). No sprints, practice or qualifying. Data source: FastF1 only.

## Wet-race rule
A race is wet if any lap by any driver in the raw lap table has a compound in INTERMEDIATE or WET. Wet races are excluded from everything.

## Clean-lap definition (applied in this order)
1. LapTime not null.
2. LapNumber at least 2.
3. Not a pit-in lap and not a pit-out lap.
4. TrackStatus exactly "1".
5. IsAccurate True.
6. Compound in SOFT, MEDIUM, HARD and TyreLife not null.
7. LapTime at most 1.07 times the fastest lap surviving steps 1 to 6 in that race. In the forecast split this threshold uses train-period laps only.
Laps are not filtered on Deleted.

## Gap ahead
For each lap, lap_end_s minus the latest lap_end_s of any other driver that is strictly smaller. Clean-air subset: gap above 2.0 s (sensitivity only).

## Models (OLS per race)
- M0: lap_s ~ C(Driver) + C(Compound) + LapNumber
- M1: lap_s ~ C(Driver) + C(Compound) + C(Compound):TyreLife + LapNumber
- M2: M1 plus C(Compound):I(TyreLife**2)
Compounds with fewer than 30 laps in the fitting set are dropped. Full-race fits use driver-clustered standard errors.

## Split and eligibility
cutoff_lap = floor(0.60 * total_laps). Train: clean laps up to the cutoff. Test: clean laps after it. Test laps of dropped compounds or drivers without train laps are removed and counted. Eligible if train laps at least 200, test laps at least 100, and full column rank for M0, M1, M2 on train. At least 12 eligible races are required.

## Metrics
Primary: D1 = mean over eligible races of (MAE_M0 - MAE_M1), with a race-level bootstrap (10000 reps, seed 42, 2.5 and 97.5 percentiles). Secondary: D2 = mean of (MAE_M1 - MAE_M2) with the same bootstrap, races where M1 beat M0 and M2 beat M1, MAE by horizon buckets (1-5, 6-10, 11-20, 21+). Naive stint slope for stints with at least 8 clean laps. Sensitivity: train fractions 0.50, 0.60, 0.70 and the clean-air subset. These are checks, not a search.

## Telemetry case study
Bahrain Grand Prix (exact EventName match, no substitution). Same clean laps and compound minimum. 25 mini-sectors by relative distance, times from SessionTime via interpolation, laps with mismatch above 1.0 s dropped, remaining rescaled to the official lap time. M1 fitted per mini-sector. Linearity check: mini-sector rates sum to the lap-time rate. Reference lap is the fastest clean lap. A mini-sector is STRAIGHT if the minimum reference-lap throttle in it is at least 95 percent, otherwise CORNER.

## Constants
SEASON=2025, SESSION_TYPE="R", DRY_COMPOUNDS=["SOFT","MEDIUM","HARD"], WET_COMPOUNDS=["INTERMEDIATE","WET"], SLOW_LAP_FACTOR=1.07, TRAIN_FRACTION=0.60, TRAIN_FRACTION_GRID=[0.50,0.60,0.70], MIN_COMPOUND_LAPS=30, MIN_TRAIN_LAPS=200, MIN_TEST_LAPS=100, MIN_VALIDATION_RACES=12, CLEAN_AIR_GAP_S=2.0, MIN_STINT_LAPS_NAIVE=8, HORIZON_BUCKETS=[(1,5),(6,10),(11,20),(21,999)], BOOTSTRAP_REPS=10000, RANDOM_SEED=42, CASE_STUDY_EVENT="Bahrain Grand Prix", N_MINISECTORS=25, STRAIGHT_THROTTLE_MIN=95.0, MAX_LAPTIME_MISMATCH_S=1.0, LOAD_RETRIES=3, RETRY_WAIT_S=30, CACHE_DIR="fastf1_cache".

These choices were fixed before any data was downloaded and were not changed afterward.
