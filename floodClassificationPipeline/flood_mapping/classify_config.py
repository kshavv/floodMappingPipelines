"""Configuration for the classification pipeline.

This module classifies the *already-exported* full-year temporal assets
(``RF_water_FullYear_<year>_<title>``, **27 bands on the Kharif-aligned
grid** — see ``stacks.build_full_year_stack``) into a single 27-band
classification image and exports it.

Per-bi-week classification scheme
---------------------------------
Each of the 27 bi-weeks is assigned to exactly one season on the
Kharif-aligned grid. The grid is anchored ~late Dec of the prior year
and Jun 1 always lands at slot 11 (0-based):

    Kharif  → slots 11..20  (BW_12 .. BW_21,  Jun 1  → Oct 4)   5-class
    Zaid    → slots  7..10  (BW_8  .. BW_11,  Apr 6  → May 17)  2-class
    Rabi    → all remaining slots (BW_1..BW_7 + BW_22..BW_27)   2-class

Rabi absorbs every non-Kharif, non-Zaid slot, so all 27 bands are
classified — there are no masked gaps.

Class codes (shared across all bands of the output image)
---------------------------------------------------------
    1 = perennial water        (Kharif only)
    2 = land / non-water
    3 = seasonal water          (Kharif only)
    4 = regular flood           (Kharif only)
    5 = anomalous water         (Kharif only)

For Rabi/Zaid bi-weeks the result is 2-class, encoded with the SAME
codes so every band shares one palette:

    1 = water
    2 = non-water
"""
from __future__ import annotations

# ── Grid (must match the exported full-year assets) ───────────
# stacks.build_full_year_stack writes N_BIWEEKS_FULL bands anchored on the
# Kharif 14-day phase (~late Dec of prior year).
N_BIWEEKS_FULL = 27
BIWEEK_DAYS = 14
HALF_BIWEEK_DAYS = 7
MONSOON_START = 6
KHARIF_N_BIWEEKS = 10

# ── Season slot ranges on the 27-band Kharif-aligned grid ─────
# Slots are ZERO-BASED full-year indices; band name = 'BW_' + (slot + 1).
# Verified stable year-to-year on the Kharif-phase anchor:
#   Jun 1 → slot 11 (Kharif BW_1)
#   Apr 1 → slot  7 (Zaid  BW_1)
#   Nov 1 → slot 22 (Rabi proper BW_1; falls inside the "rabi" group below)
KHARIF_SLOTS = list(range(11, 21))                  # BW_12..BW_21
ZAID_SLOTS = list(range(7, 11))                     # BW_8..BW_11
RABI_SLOTS = (
    [s for s in range(N_BIWEEKS_FULL)
     if s not in set(KHARIF_SLOTS) and s not in set(ZAID_SLOTS)]
)

# slot -> season key, for fast per-band dispatch.
SLOT_SEASON = {}
for _s in KHARIF_SLOTS:
    SLOT_SEASON[_s] = 'kharif'
for _s in ZAID_SLOTS:
    SLOT_SEASON[_s] = 'zaid'
for _s in RABI_SLOTS:
    SLOT_SEASON[_s] = 'rabi'

# ── Class codes ───────────────────────────────────────────────
CLS_PERENNIAL = 1   # also: water (2-class)
CLS_LAND = 2        # also: non-water (2-class)
CLS_SEASONAL = 3    # Kharif only
CLS_REGULAR = 4     # Kharif only
CLS_ANOMALOUS = 5   # Kharif only

# 5-class palette + labels (shared by the whole output image).
CLASS_PALETTE = ['#3B82F6', '#E5E7EB', '#ffed00', '#F59E0B', '#EF4444']
CLASS_LABELS = ['Perennial / Water', 'Land / Non-water',
                'Seasonal water', 'Regular flood', 'Anomalous water']

# ── Classification thresholds (defaults mirror the JS sliders) ─
DEFAULT_THRESHOLDS = {
    'perennial': 0.80,
    'biweek':    0.80,
    'biweekAn':  0.40,
    'yearlyAn':  0.30,
}

# ── Temporal-correction parameters (mirror ee_app.js) ─────────
GLOBAL_TRANSITION_THRESHOLD = 6
LOCAL_TRANSITION_THRESHOLD = 4
LOCAL_WINDOW_RADIUS = 3

# ── Export / raster settings (must match download pipeline) ───
SCALE = 30
NATIVE_CRS = 'EPSG:4326'
MAX_PIXELS = int(1e10)

# Years whose full-year assets supply the cross-year bi-week frequency.
HISTORICAL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

# Asset naming (must match download_year.py).
FULLYEAR_PREFIX = 'RF_water_FullYear_'


def fullyear_asset_id(asset_root: str, year: int, title: str) -> str:
    """Full-year asset id, byte-identical to the download pipeline."""
    return f"{asset_root.rstrip('/')}/{FULLYEAR_PREFIX}{year}_{title}"


def season_for_slot(slot_zero_based: int) -> str:
    """Return 'kharif' | 'rabi' | 'zaid' for a 0-based full-year slot."""
    return SLOT_SEASON[slot_zero_based]
