"""Example: classify exported full-year temporal assets into a single
27-band classification image.

Prerequisites
-------------
    pip install earthengine-api
    earthengine authenticate

You must have already run the download pipeline so that the input
``RF_water_FullYear_<year>_<title>`` assets exist (27 bands each, on
the Kharif-aligned grid).
"""
import ee
ee.Initialize(project='gentle-operator-308420')

from flood_mapping import classify_year, classify_years


ASSET_ROOT  = 'projects/gentle-operator-308420/assets/TemporalImages'
OUTPUT_ROOT = 'projects/gentle-operator-308420/assets/Classified'
DRIVE_DIR   = 'flood_classified'


# ─────────────────────────────────────────────────────────────
# Example 1: Classify one year (Kerala, whole state). Asset only.
# Resolves the polygon via AdminRoi, masks the output to the state
# boundary so all 27 bands are state-shaped (not bounding-box squares).
# ─────────────────────────────────────────────────────────────
result = classify_year(
    state='Kerala',
    year=2024,
    asset_root=ASSET_ROOT,
    destinations='asset',
    output_root=OUTPUT_ROOT,
)
print('Output asset:      ', result['output_asset_id'])
print('Historical years:  ', result['historical_years'])
print('Missing historical:', result['missing_historical'])


# ─────────────────────────────────────────────────────────────
# Example 2: District subset, both asset and Drive.
# Title auto-derived from AdminRoi (e.g. 'kerala_3,7,12').
# ─────────────────────────────────────────────────────────────
# result = classify_year(
#     state='Kerala',
#     districts=['Ernakulam', 'Kollam', 'Thrissur'],
#     year=2024,
#     asset_root=ASSET_ROOT,
#     destinations=['asset', 'drive'],
#     output_root=OUTPUT_ROOT,
#     drive_folder=DRIVE_DIR,
# )


# ─────────────────────────────────────────────────────────────
# Example 3: Custom thresholds, corrections off.
# ─────────────────────────────────────────────────────────────
# result = classify_year(
#     state='Kerala',
#     year=2024,
#     asset_root=ASSET_ROOT,
#     destinations='asset',
#     output_root=OUTPUT_ROOT,
#     thresholds={'perennial': 0.85, 'biweek': 0.75},
#     apply_temporal_corrections=False,
# )


# ─────────────────────────────────────────────────────────────
# Example 4: Batch over several years (idempotent — skip_existing).
# ─────────────────────────────────────────────────────────────
# classify_years(
#     state='Kerala',
#     years=[2019, 2020, 2021, 2022, 2023, 2024],
#     asset_root=ASSET_ROOT,
#     destinations='asset',
#     output_root=OUTPUT_ROOT,
# )


# ─────────────────────────────────────────────────────────────
# Example 5: Explicit title + ROI (advanced).
# Use when the title doesn't match any GAUL state — e.g. you built
# the temporal assets with a custom AOI.
# ─────────────────────────────────────────────────────────────
# my_roi = ee.Geometry.Rectangle([76.0, 8.0, 77.5, 12.0])
# result = classify_year(
#     title='custom_aoi',
#     year=2024,
#     asset_root=ASSET_ROOT,
#     destinations='asset',
#     output_root=OUTPUT_ROOT,
#     roi=my_roi,
# )
