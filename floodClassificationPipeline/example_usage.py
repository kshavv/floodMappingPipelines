"""Example: download temporal images for Indian states / districts.

[PATH2] Each year produces a SINGLE full-year stack on the Kharif-aligned
27-bi-week grid. The Kharif (and, later, Rabi / Zaid) sub-stacks are sliced
out of this full-year stack by the EE app at classify time — so there are
no separate Kharif assets, for the target year or for historical years.

Prerequisites:
  pip install earthengine-api
  earthengine authenticate
"""
import ee

# Initialise with your Cloud project (replace with your own).
ee.Initialize(project='gentle-operator-308420')

from flood_mapping import (
    download_temporal_images_for_year,
    download_temporal_images_for_years,
)


TRAINING_FC = 'projects/gentle-operator-308420/assets/finalDataset/full_dataset_v3'
ASSET_ROOT  = 'projects/gentle-operator-308420/assets/TemporalImages'
DRIVE_DIR   = 'flood_temporal_images'


# ─────────────────────────────────────────────────────────────
# Example 1: Single year, whole state, asset only.
# Produces ONE asset: RF_water_FullYear_2024_kerala
# ─────────────────────────────────────────────────────────────
result = download_temporal_images_for_year(
    state='Kerala',
    year=2024,
    training_fc=TRAINING_FC,
    asset_root=ASSET_ROOT,
    destinations='asset',
)
print('Full-year asset: ', result['fullyear_asset_id'])
print('Title used:      ', result['title'])


# ─────────────────────────────────────────────────────────────
# Example 2: All historical years in one call (the common case).
# Produces RF_water_FullYear_<yr>_<title> for every year.
# skip_existing=True (default) makes it idempotent — re-running
# skips years whose full-year asset already exists.
# ─────────────────────────────────────────────────────────────
# results = download_temporal_images_for_years(
#     state='Assam',
#     years=[2019, 2020, 2021, 2022, 2023, 2024],
#     training_fc=TRAINING_FC,
#     asset_root=ASSET_ROOT,
#     destinations='asset',
# )
# for r in results:
#     print(r['fullyear_asset_id'], '(skipped)' if r['skipped'] else '(queued)')


# ─────────────────────────────────────────────────────────────
# Example 3: Subset of districts, asset only.
# Title will be 'kerala_3,7,12' (1-based indices into the
# alphabetised Kerala district list).
# ─────────────────────────────────────────────────────────────
# result = download_temporal_images_for_year(
#     state='Kerala',
#     districts=['Ernakulam', 'Kollam', 'Thrissur'],
#     year=2024,
#     training_fc=TRAINING_FC,
#     asset_root=ASSET_ROOT,
#     destinations='asset',
# )


# ─────────────────────────────────────────────────────────────
# Example 4: Both asset and Drive.
# Drive output goes to <drive>/<drive_folder>/<name>.tif
# ─────────────────────────────────────────────────────────────
# result = download_temporal_images_for_year(
#     state='Kerala',
#     districts=['Ernakulam', 'Kollam', 'Thrissur'],
#     year=2024,
#     training_fc=TRAINING_FC,
#     asset_root=ASSET_ROOT,
#     destinations=['asset', 'drive'],
#     drive_folder=DRIVE_DIR,
# )


# ─────────────────────────────────────────────────────────────
# Example 5: Drive only (no asset write), multiple years.
# ─────────────────────────────────────────────────────────────
# download_temporal_images_for_years(
#     state='Assam',
#     years=[2023, 2024],
#     training_fc=TRAINING_FC,
#     destinations='drive',
#     drive_folder=DRIVE_DIR,
# )
