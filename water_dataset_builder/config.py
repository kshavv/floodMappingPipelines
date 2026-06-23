"""
Configuration for the ALL-GEE water-dataset pipeline.

Everything runs server-side on Earth Engine. The only thing that comes
back to your machine is task status — no feature data is ever pulled
local. Inputs are pre-uploaded GEE table assets (one per category); the
output is a single GEE FeatureCollection asset.
"""

# ----------------------------------------------------------------------
# Earth Engine project
# ----------------------------------------------------------------------
EE_PROJECT = "gentle-operator-308420"

# ----------------------------------------------------------------------
# Input assets (one uploaded table asset per category)
# ----------------------------------------------------------------------
# Upload each KML/shapefile as its own GEE table asset, then put the asset
# IDs here. Each polygon must keep its `Name` property (e.g. "19W19102022")
# so the id / waterType / date parsing works.
#
#   do_nw_sampling = True  -> also sample an outer non-water ring
#   do_nw_sampling = False -> water pixels only
ASSET_BASE = "projects/gentle-operator-308420/assets/WaterClsDataset"

CATEGORIES = {
    "large":      {"asset": ASSET_BASE + "/LargePolygon",     "do_nw_sampling": True},
    "large_cnnw": {"asset": ASSET_BASE + "/largePolygonCNNW",  "do_nw_sampling": False},
    "small":      {"asset": ASSET_BASE + "/smallFPPolygon",     "do_nw_sampling": True},
    "small_cnnw": {"asset": ASSET_BASE + "/smallFPPolygonsCNNW",  "do_nw_sampling": False},
    "negatives":  {"asset": ASSET_BASE + "/negativeSampling",  "do_nw_sampling": False},
}

# ----------------------------------------------------------------------
# Output asset (single merged, engineered FeatureCollection)
# ----------------------------------------------------------------------
OUTPUT_ASSET_ID = ASSET_BASE + "/water_rf_dataset"

# ----------------------------------------------------------------------
# Sampling parameters
# ----------------------------------------------------------------------
SCALE = 10

WATER_INTERIOR_BUFFER = -5
WATER_PTS_PER_POLY    = 20

NW_INNER_BUFFER  = 15
NW_RING_WIDTH    = 30
NW_PTS_PER_POLY  = 15

SAMPLE_TILE_SCALE = 1   # 1 = default/fastest; raise to 4/8 only on memory errors

# ----------------------------------------------------------------------
# Sentinel search windows / filters
# ----------------------------------------------------------------------
S1_WINDOW_DAYS = 7
S2_WINDOW_DAYS = 3
S2_MAX_CLOUD   = 60

S1_BANDS = ["VV", "VH"]
S2_BANDS = ["B2", "B3", "B4", "B8", "B5", "B6", "B7", "B8A", "B11"]

# ----------------------------------------------------------------------
# Feature-engineering parameters (now applied SERVER-SIDE)
# ----------------------------------------------------------------------
S1_DAY_DIFF_MAX = 5.5
S2_DAY_DIFF_MAX = 4.5

SIZECLASS_SMALL_MAX  = 5e3
SIZECLASS_MEDIUM_MAX = 5e4

# Properties written to the final asset (geometry is kept on the asset, so
# lat/lon are optional but handy).
OUTPUT_PROPERTIES = [
    "id", "Name",
    "VV", "VH", "VV_VH_ratio",
    "B2", "B3", "B4", "B8", "B8A", "B11", "B5", "B6", "B7",
    "B2_log", "B3_log",
    "BGR", "NDWI", "MNDWI", "soilIndex",
    "month", "poly_area_m2", "sizeClass",
    "s1_datetime_utc", "s1_day_diff", "s2_datetime_utc", "s2_day_diff",
    "waterType",  # 1 = water, 0 = non-water
]