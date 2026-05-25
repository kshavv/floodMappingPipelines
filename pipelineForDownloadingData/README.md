# flood_mapping — Temporal-image download pipeline

Builds and exports the temporal image needed by the flood-mapping
classifier for a given year and Indian administrative region.

**One output per year:**

- **Full-year stack** (`RF_water_FullYear_<year>_<title>`) — 27 bi-weeks
  on the **Kharif-aligned grid** (anchor ≈ late December of the prior year).

Each band is a uint8 water mask (0 = land, 1 = water, masked = no
data) produced by a hybrid S1+S2 Random-Forest classifier with an
S1-only fallback for cloud/shadow pixels. Bi-week date ranges are
attached as image properties (`BW_<N>_startDate`, `BW_<N>_endDate`),
plus a `grid_anchor` property, so the EE app can rebuild a bi-week
dropdown from a saved asset's metadata.

## Why full-year only (and why the grid is "Kharif-aligned")

Earlier the pipeline exported a separate 10-band Kharif stack alongside
the full-year stack. That's no longer needed: the EE app now **slices**
the Kharif season (and, later, Rabi / Zaid) out of a single full-year
stack at classify time. To make that slice exact, the full-year grid is
anchored on the **same 14-day phase as the Kharif season** — it starts
in late December of the prior year rather than Jan 1, and uses **27**
bi-weeks to cover the year. On this grid, June 1 (Kharif `BW_1`) always
lands at full-year slot index 11 (0-based), so the Kharif window is a
byte-identical slice with no date drift.

> If you have older `RF_water_<year>_<title>` Kharif assets or
> `RF_water_FullYear_*` assets built on the old Jan-1 / 26-bi-week grid,
> they are **not** slice-compatible with the updated EE app. Re-export
> with this pipeline.

## Local setup

```bash
# 1. Install the Earth Engine Python client.
pip install earthengine-api

# 2. Authenticate (opens a browser). Run once per machine.
earthengine authenticate

# 3. Drop the flood_mapping/ folder somewhere on your PYTHONPATH,
#    or just sit next to it when you run python.
```

In Python or a notebook:

```python
import ee
ee.Initialize(project='your-google-cloud-project-id')
```

The project must have Earth Engine enabled in the Cloud Console. If you
don't have one yet, follow Google's "Set up your Earth Engine-enabled
Cloud project" guide.

**For automation (cron jobs, batch runs)** use a service account:

```python
import ee
credentials = ee.ServiceAccountCredentials(
    email='svc-account@your-project.iam.gserviceaccount.com',
    key_file='/path/to/key.json',
)
ee.Initialize(credentials=credentials, project='your-project')
```

## API

### `download_temporal_images_for_year(state, year, training_fc, **kwargs)`

Builds and exports the full-year stack for a single year.

| Argument | Type | Description |
|---|---|---|
| `state` | `str` | Indian state name as in FAO GAUL level1, e.g. `'Kerala'`. |
| `year` | `int` | Year (e.g. `2024`). |
| `training_fc` | `ee.FeatureCollection` or asset-id string | Training FC. Must include all 12 fused features as numeric properties plus `waterType` and `Name`. |
| `districts` | `list[str]`, optional | District names within the state. `None` or empty list → whole state. |
| `destinations` | `'asset'`, `'drive'`, or `['asset','drive']` | Where to send the output. Default: `'asset'`. |
| `asset_root` | `str` | Required when destinations include `'asset'`. Root asset path. |
| `drive_folder` | `str` | Required when destinations include `'drive'`. Drive folder name. |
| `s1_window_days` | `int`, default 6 | ± half-width of S1 search window. Widen for S1-revisit-gap areas. |
| `s2_window_days` | `int`, default 6 | ± half-width of S2 search window. |
| `extra_properties` | `dict`, optional | Extra image properties attached to the output. |
| `start_tasks` | `bool`, default `True` | Start tasks immediately. |
| `skip_existing` | `bool`, default `True` | Skip asset export when the asset already exists. |

**Returns** a dict including:

```
admin                      → AdminRoi (resolved region + title)
title                      → str  (the derived title used in filenames)
fullyear_asset_id          → str or None
fullyear_asset_task        → ee.batch.Task or None
fullyear_drive_task        → ee.batch.Task or None
fullyear_drive_filename    → str or None
skipped                    → list[str]  (asset ids skipped)
```

The asset and Drive outputs share the same base name, so a Drive
GeoTIFF named `RF_water_FullYear_2024_kerala.tif` corresponds 1:1 to
the asset at `<asset_root>/RF_water_FullYear_2024_kerala`.

### `download_temporal_images_for_years(state, years, training_fc, **kwargs)`

Thin loop over `download_temporal_images_for_year` — the common way to
fetch every historical year. Forwards all the same keyword arguments.
Returns a `list[dict]`, one result per year in order. With the default
`skip_existing=True`, re-running only exports the years still missing.

```python
results = download_temporal_images_for_years(
    state='Assam',
    years=[2019, 2020, 2021, 2022, 2023, 2024],
    training_fc=TRAINING_FC,
    asset_root=ASSET_ROOT,
)
```

## Quick start

```python
import ee
ee.Initialize(project='your-cloud-project')

from flood_mapping import (
    download_temporal_images_for_year,
    download_temporal_images_for_years,
)

# Single year, whole state, asset only:
result = download_temporal_images_for_year(
    state='Kerala',
    year=2024,
    training_fc='projects/.../full_dataset_v3',
    asset_root='projects/.../TemporalImages',
)

# All historical years in one call:
results = download_temporal_images_for_years(
    state='Assam',
    years=[2019, 2020, 2021, 2022, 2023, 2024],
    training_fc='projects/.../full_dataset_v3',
    asset_root='projects/.../TemporalImages',
)
```

## Title derivation (matches `ee_app.js`)

The output filenames depend only on `state` + `districts`, deterministically:

| Input | Title |
|---|---|
| `state='Kerala'` (no districts) | `kerala` |
| `state='Kerala', districts=[all 14 Kerala districts]` | `kerala` |
| `state='Kerala', districts=['Ernakulam','Kollam','Thrissur']` | `kerala_3,7,12` |
| `state='Tamil Nadu'` | `tamil_nadu` |

Indices are 1-based positions in the alphabetised state district list,
sorted ascending. This means the same `(state, districts)` always
produces the same title — so a later call with the same arguments will
hit `skip_existing` and reuse the prior export.

## Reuse semantics

`skip_existing=True` (the default) calls `ee.data.getAsset()` for the
full-year asset before queuing. Existing assets are skipped and reported
in the returned `skipped` list. Safe to loop (or just use
`download_temporal_images_for_years`):

```python
for yr in [2019, 2020, 2021, 2022, 2023, 2024]:
    download_temporal_images_for_year(
        state='Kerala', year=yr,
        training_fc=TRAINING_FC, asset_root=ASSET_ROOT,
    )
```

Only the years missing from `asset_root` will export.

Drive exports always run when requested. Earth Engine doesn't expose
Drive listing, so we can't detect existing Drive files. Manage Drive
de-duplication yourself if needed.

## Compatibility with `ee_app.js`

This pipeline's output naming and grid are identical to what the updated
EE app produces and consumes. Assets created here load directly from the
app's "Use existing temporal images" mode — enter the same `title` and
`year`, and the bi-week dropdown populates from the asset's metadata
(the app derives the Kharif slice from the full-year grid).

## Files

```
flood_mapping/
├── __init__.py            — public API
├── config.py              — constants (matches ee_app.js)
├── admin.py               — state/district → geometry + title
├── classifiers.py         — RF training + per-bi-week water mask
├── stacks.py              — full-year builder (+ retained Kharif builder)
│                            and the Kharif-aligned grid helpers
└── download_year.py       — top-level pipeline + export (single & multi-year)
example_usage.py           — runnable examples
README.md                  — this file
```
