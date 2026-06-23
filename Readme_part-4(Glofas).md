# GFM Flood Data Pipeline — Documentation

## Overview

This pipeline downloads, processes, and stacks Global Flood Monitoring (GFM) satellite-derived flood extent data for a given Indian district and year. The output is a **26-band biweekly GeoTIFF** where each band represents one ~2-week period of the year, clipped to the district boundary.

**Data source:** [EODC GFM STAC API](https://stac.eodc.eu/api/v1)  
**Satellite:** Sentinel-1 SAR-derived flood extent  
**Output CRS:** EPSG:4326  
**Output classes (final clipped TIF):**

| Value | Class |
|-------|-------|
| 1 | Flood extent |
| 2 | Land |
| 3 | Seasonal water |
| 4 | Permanent water |

> Intermediate outputs may contain `0` (unassigned pixels where neither flood nor reference water covered a pixel) and `255` (pixels outside the district boundary set during clipping). Both are removed in the final clipped TIF — within the district boundary, the reference water layer provides complete land/water coverage, so every pixel resolves to a class 1–4.

---

## Pipeline Architecture

```
District Name
     │
     ▼
[GADM Boundary Lookup]  ──►  AOI bbox + district geometry
     │
     ▼
[STAC Search]  ──►  ENSEMBLE_FLOOD items intersecting AOI
     │
     ├──► [Download]  ──►  ensemble_flood_extent tiles  (per date)
     │                     reference_water_mask tiles   (all dates, merged once)
     │
     ▼
[Merge Tiles per Date]
     │
     ├──► ENSEMBLE_FLOOD_{date}_merged.tif
     └──► REFERENCE_WATER_merged.tif  (shared across all dates)
     │
     ▼
[Combine Flood + Ref Water]  ──►  combined_native_{date}.tif  (classified, native CRS)
     │
     ▼
[Reproject to EPSG:4326]  ──►  combined_4326_{date}.tif
     │
     ▼
[Biweekly Stack]  ──►  gfm_biweekly_{year}.tif  (26-band, full AOI extent)
     │
     ▼
[Clip to District]  ──►  gfm_biweekly_{year}_clipped.tif  (nodata=255 outside boundary)
```

---

## Prerequisites

### Python Packages

```bash
pip install -r requirements.txt
```

### GADM District Boundaries

The pipeline uses GADM Level 2 (district) boundaries for India. Download and cache locally before running:

```python
import geopandas as gpd

gadm_url = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IND_2.json"
india_districts = gpd.read_file(gadm_url)
india_districts.to_file("india_districts.gpkg", driver="GPKG")
```

This only needs to be done **once** — the file `india_districts.gpkg` is reused on subsequent runs.

---

## GFM Account Registration

Before running the pipeline, you need a registered account on the GFM portal. The `EMAIL` and `PASSWORD` in the config are the credentials from this account.

1. Go to [https://portal.gfm.eodc.eu/](https://portal.gfm.eodc.eu/)
2. Click **Register** and fill in your details
3. Verify your email address
4. Once verified, your credentials can be used directly in the pipeline config below

The pipeline authenticates via `POST /v2/auth/login` and receives a bearer token used for all subsequent STAC searches and tile downloads. The token is fetched fresh on every run — no manual login is needed after the one-time registration.

---

## Configuration

Edit these variables at the top of the script before running:

```python
EMAIL         = "your@email.com"     # GFM portal registered email
PASSWORD      = "yourpassword"       # GFM portal password

DISTRICT_NAME = "Barpeta"            # Must match GADM NAME_2 field (case-insensitive)
START_DATE    = "2023-01-01"
END_DATE      = "2023-12-31"
```

**Finding the correct district name:** GADM uses transliterated English spellings. If the exact name is not found, the script will print similar matches to help you correct it.

---

## Step-by-Step Walkthrough

### Step 1 — District Boundary Lookup (`get_district_info`)

Reads `india_districts.gpkg`, matches the district name against the `NAME_2` column (case-insensitive), and returns:

- `aoi_bbox` — padded bounding box `[west, south, east, north]` used for STAC search
- `district_geom` — GeoJSON-like geometry dict used for final clipping

A 0.1° padding is added around the district boundary so that STAC tile search captures edge tiles fully.

### Step 2 — STAC Search (`search_products`)

Queries the EODC STAC API for all `GFM` collection items:

- Spatially filtered to `aoi_bbox`
- Temporally filtered to `START_DATE` / `END_DATE`
- Further filtered to items whose ID contains `ENSEMBLE_FLOOD` and whose footprint actually intersects the AOI

The date is extracted from the item ID (format: `ENSEMBLE_FLOOD_YYYYMMDDTHHMMSS_...`).

### Step 3 — Coverage Check (`check_spatial_coverage`)

Computes the union of all item footprints and reports what percentage of the AOI is covered. Useful for identifying gaps in the Sentinel-1 acquisition schedule.

### Step 4 — Download (`download_products`, `search_reference_water`)

Downloads two asset types per STAC item:

- `ensemble_flood_extent` — binary flood mask (0 = no flood, 1 = flood)
- `reference_water_mask` — reference water classes (0 = land, 1 = permanent water, 2 = seasonal water)

Files are saved to `gfm_downloads/`. Already-downloaded files are skipped.

Reference water tiles are also searched independently across the full AOI to ensure complete spatial coverage even on dates where no flood items exist.

### Step 5 — Merge Tiles (`merge_per_date`)

Tiles are mosaicked using `rasterio.merge`:

- **Flood:** one merged file per acquisition date → `gfm_merged/ENSEMBLE_FLOOD_{date}_merged.tif`
- **Reference water:** all tiles merged once → `gfm_merged/REFERENCE_WATER_merged.tif` (reused for every date)

### Step 6 — Classification (`combine_tifs`)

For each date, combines the flood and reference water layers into a single classified raster:

```
Priority order (flood takes precedence over water classes):

  flood == 1                          → class 1 (flood)
  flood != 1 AND ref_water == 0       → class 2 (land)
  flood != 1 AND ref_water == 2       → class 3 (seasonal water)
  flood != 1 AND ref_water == 1       → class 4 (permanent water)
  everything else                     → class 0 (unclassified)
```

Both layers are reprojected to the flood tile's native CRS and grid during compositing.

### Step 7 — Reproject to EPSG:4326 (`reproject_to_4326`)

Reprojects each classified TIF to geographic coordinates (EPSG:4326) using nearest-neighbour resampling to preserve discrete class values. A colormap is embedded:

| Class | Color |
|-------|-------|
| 1 — Flood | Violet `(148, 0, 211)` |
| 2 — Land | White `(255, 255, 255)` |
| 3 — Seasonal water | Cyan `(0, 255, 255)` |
| 4 — Permanent water | Blue `(0, 0, 255)` |

Intermediate `combined_native_{date}.tif` files are deleted after reprojection to save disk space.

### Step 8 — Biweekly Stack (`create_biweekly_stack`)

Groups the daily classified TIFs into 26 biweekly periods (each ~14 days). The output is a 26-band GeoTIFF where Band N corresponds to biweek N of the year.

**Grid computation:** The output grid extent is computed as the **union of all input file extents** — i.e. the bounding box that covers every daily TIF. Each file is then reprojected onto this common grid before compositing. This ensures no data is lost when different acquisition dates have slightly different spatial coverages. Pixels in the union extent that fall outside all input files remain `0` at this stage, but are removed in the subsequent district clipping step.

**Priority compositing** within each biweek (highest priority wins per pixel):

```
Flood (1) > Seasonal water (3) > Permanent water (4) > Land (2)
```

This means if any single day in a biweek shows flooding at a pixel, the biweek band records it as flood.

Band descriptions are written as `Biweek_1` through `Biweek_26`.

### Step 9 — Clip to District (`clip_to_district`)

Clips the 26-band stack to the exact district polygon using `rasterio.mask`. Pixels outside the district boundary are set to `nodata=255` (chosen to avoid conflict with valid class values 1–4). Within the district, the reference water layer provides complete coverage, so no `0` pixels remain — every pixel in the final output is one of classes 1–4.

Output: `gfm_biweekly_{year}_clipped.tif`

---

## Output Files

| File | Location | Description |
|------|----------|-------------|
| `gfm_downloads/*.tif` | `gfm_downloads/` | Raw downloaded tiles |
| `ENSEMBLE_FLOOD_{date}_merged.tif` | `gfm_merged/` | Merged flood tiles per date |
| `REFERENCE_WATER_merged.tif` | `gfm_merged/` | Single merged reference water mosaic |
| `combined_4326_{date}.tif` | `gfm_final/` | Classified + reprojected TIF per date |
| `gfm_biweekly_{year}.tif` | `gfm_final/` | 26-band biweekly stack (full AOI) |
| `gfm_biweekly_{year}_clipped.tif` | `gfm_final/` | 26-band stack clipped to district boundary |

The clipped file is the primary deliverable for downstream analysis and validation.

---

## Resumability

The pipeline is designed to be re-run safely:

- Downloaded tiles are skipped if the file already exists
- Merged TIFs are skipped if already present
- Per-date combined TIFs are skipped if `combined_4326_{date}.tif` already exists

To reprocess a specific date, delete the corresponding `combined_4326_{date}.tif` from `gfm_final/`.

---

## Common Issues

**District not found**
The script prints similar GADM `NAME_2` values when no exact match is found. Use the suggested spelling exactly.

**No STAC items returned**
Check that `START_DATE` / `END_DATE` and `DISTRICT_NAME` are correct. Sentinel-1 has a ~6–12 day revisit cycle, so some short date ranges may return no items for small districts.

**Partial AOI coverage**
If `check_spatial_coverage` reports < 100%, the district likely straddles a fixed GFM tile boundary. This is expected — the stack compositing will still capture all available data.

**API 502/503/504 errors**
The EODC API occasionally returns transient errors. Adding a retry loop around `requests.get` calls (with exponential backoff) is recommended for large downloads.

---

## Notes on Design Choices

- `nodata=255` is used (not `0`) during district clipping because `0` appears in intermediate outputs as an unassigned pixel value. Using `0` as nodata would make it ambiguous; `255` is safely outside the 1–4 class range.
- Within the district boundary, `0` pixels do not appear in the final output because the reference water layer provides complete land/water coverage — every pixel resolves to land (2), seasonal water (3), or permanent water (4) at minimum.
- Reference water is merged once and shared across all dates because it is a static layer — it does not vary by acquisition date.
- The biweekly period is a fixed 14-day window anchored to Jan 1.
