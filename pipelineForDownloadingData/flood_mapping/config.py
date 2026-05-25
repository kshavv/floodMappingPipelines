"""Configuration constants shared by every module in this package.

These mirror the values used by `ee_app.js` so assets produced by the
Python pipeline are byte-compatible with the EE app's loader.
"""

# Feature set for the fused (S1 + S2) Random Forest.
FEATURES_FUSED = [
    'VV', 'VH', 'VV_VH_ratio',
    'B2', 'B3', 'B4', 'B8', 'B8A',
    'NDWI', 'BGR', 'B11', 'MNDWI',
]

# Feature set for the S1-only fallback Random Forest.
FEATURES_S1 = ['VV', 'VH', 'VV_VH_ratio']

# RF training settings.
SEED = 43
N_TREES = 500
MIN_LEAF_POPULATION = 2
BAG_FRACTION = 0.7

# Temporal grid.
#
# [PATH2] The full-year grid is anchored on the SAME 14-day phase as the
# Kharif season (it starts in late December of the prior year, not Jan 1), so
# the Kharif window is an exact, byte-identical *slice* of the full-year stack
# with no date drift. This matches the updated EE app, whose loader slices the
# Kharif (and later Rabi / Zaid) sub-stacks out of a single full-year stack.
# On this aligned grid, 27 bi-weeks are needed to cover a whole calendar year,
# and June 1 (Kharif BW_1) always lands at full-year slot index 11 (0-based).
MONSOON_START = 6        # June 1
N_BIWEEKS = 10           # 10 bi-weeks of Kharif starting June 1
N_BIWEEKS_FULL = 27      # 27 bi-weeks cover a full year on the Kharif-aligned grid
BIWEEK_DAYS = 14
HALF_BIWEEK_DAYS = 7     # midpoint offset

# Export settings.
SCALE = 30
NATIVE_CRS = 'EPSG:4326'
MAX_PIXELS = int(1e10)

# Years used for cross-year biweek frequency in the classifier.  Not
# required by the download pipeline itself, but kept here for callers.
HISTORICAL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

# Search-window defaults (days, ±).  See ee_app.js for the rationale.
DEFAULT_S1_WINDOW = 6
DEFAULT_S2_WINDOW = 6

# Bands the pipeline needs from each Sentinel collection.
S2_BANDS = ['B2', 'B3', 'B4', 'B8', 'B8A', 'B11', 'SCL']
S1_BANDS = ['VV', 'VH']
