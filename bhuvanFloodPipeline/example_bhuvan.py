"""Bhuvan flood pipeline — two endpoints.

YEAR endpoint
    download_bhuvan_kharif_stack(...)
    -> One multi-band GeoTIFF, 140 bands (Jun 1 -> Oct 18), one band per day.

DAY endpoint
    download_bhuvan_flood_day(...)
    -> One single-band GeoTIFF for one specific date.

Both endpoints accept the same AOI options: whole state (state=), single
GAUL district (district=, requires Earth Engine), or custom polygon
(district_geometry=, no EE needed).

Both endpoints accept the same logging flags:
    log=True       per-day status line (year endpoint only)
    debug=True     upfront diagnostic block (state config, AOI bbox,
                   tile-grid math, sample tiles, polygon stats,
                   layer-name preview, run plan)
    verbose=True   per-tile URL + status + bytes + elapsed time
    tile_cache_dir save raw PNGs to disk for QGIS inspection
"""
import ee
ee.Initialize(project='gentle-operator-308420')   # only needed for district= by name

from bhuvan_flood import (
    download_bhuvan_kharif_stack,
    download_bhuvan_flood_day,
)


# ────────────────────────────────────────────────────────────────────
# DAY endpoint — single date.
# Fastest way to sanity-check a specific date before committing to a
# year. Auto-derives output to ./bhuvan_flood_kerala_2018-08-16.tif.
# ────────────────────────────────────────────────────────────────────
download_bhuvan_flood_day(
    state='Kerala',
    date='2018-08-16',
    debug=True,
)


# DAY endpoint with a single district:
# download_bhuvan_flood_day(
#     state='Kerala',
#     district='Ernakulam',
#     date='2018-08-16',
#     debug=True,
# )


# ────────────────────────────────────────────────────────────────────
# YEAR endpoint — full Kharif window, one multi-band file.
# Whole state, ~500 tiles/data-day. Days without Bhuvan data are
# all-zero bands. Auto-derives output to
# ./bhuvan_kharif_kerala_2018.tif.
# ────────────────────────────────────────────────────────────────────
# download_bhuvan_kharif_stack(
#     state='Kerala',
#     year=2018,
#     debug=True,         # upfront diagnostic block
#     log=True,           # one line per day during the run
# )


# YEAR endpoint with a single district (~10-30 tiles/data-day, ~50x faster):
# download_bhuvan_kharif_stack(
#     state='Kerala',
#     district='Ernakulam',
#     year=2018,
#     debug=True,
# )
