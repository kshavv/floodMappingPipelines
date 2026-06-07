# Bhuvan Flood Pipeline

Download Bhuvan's daily flood layers via WMS and stack them into a
single multi-band GeoTIFF — one band per Kharif day, ISO date as the
band name.

## What it does

For one `(state, year)` it iterates every calendar day of the Kharif
window (Jun 1 → Oct 4, 140 days, matching the GEE classifier's Kharif
slot range), probes Bhuvan for that day's WMS layer, downloads the
covering tiles, stitches them, applies the cyan-pixel test (port of
your QGIS raster-calculator expression `R=0 ∧ G=255 ∧ B=255 ∧ A=255`),
and writes the 0/1 mask as one band of the output GeoTIFF.

Days with no Bhuvan data become all-zero bands so the band index is
1:1 with day-of-Kharif. Each band carries:

- `set_band_description(...)` = ISO date (e.g. `2023-08-16`)
- per-band tag `bhuvan_layer` = the actual layer name fetched
  (e.g. `flood:kl_2023_16_08_06`), or `NONE` for empty days

## Layer-name probe order

Bhuvan layer names embed `YYYY_DD_MM` (day-then-month — your scraper
already handles this) and optionally a UTC-hour suffix. For each date
we try, in order:

1. `flood:<code>_YYYY_DD_MM`
2. `flood:<code>_YYYY_DD_MM_06`
3. `flood:<code>_YYYY_DD_MM_12`
4. `flood:<code>_YYYY_DD_MM_18`

The first variant that returns a non-empty 256×256 tile inside the
state wins. If all four come back empty, the band is all zeros.

## State mapping

Edit `bhuvan_flood/config.py::STATES` to add or adjust:

```python
STATES = {
    'Kerala':    {'code': 'kl', 'bbox': (74.5,  8.0, 78.0, 13.0), ...},
    'Karnataka': {'code': 'ka', 'bbox': (73.5, 11.0, 79.0, 19.5), ...},
    'Haryana':   {'code': 'hr', 'bbox': (74.0, 27.0, 78.5, 31.5), ...},
    'Bihar':     {'code': 'br', 'bbox': (83.0, 24.0, 89.0, 27.5), ...},
    'Assam':     {'code': 'as', 'bbox': (89.5, 24.0, 96.5, 28.5), ...},
}
```

The bbox is intentionally slightly larger than the state polygon so
every tile that overlaps the state gets fetched. The output extent is
the tile-grid covering of this bbox at Bhuvan's zoom 10.

## Tile grid

Bhuvan serves the flood layers on the standard WMS-C quadtree in
EPSG:4326: world is 2 tiles wide at z=0, tiles are 256×256 px, zoom
is 10 for these layers. That gives a pixel size of ~0.000687° (~76 m
at the equator), and tile boundaries align at multiples of ~0.176°.
Pre-allocating the empty canvas to this exact grid means days with
data and days without share the same affine transform; rasterio
writes the whole thing band-by-band so the full stack never lives in
RAM.

## Install

```bash
pip install rasterio pillow requests numpy
```

## Usage

```python
from bhuvan_flood import download_bhuvan_kharif_stack

result = download_bhuvan_kharif_stack(
    state='Kerala',
    year=2023,
    output_path='./bhuvan_kharif_kerala_2023.tif',
)

print(result['n_days_with_data'], 'days had Bhuvan data')
```

Batch over years:

```python
for yr in [2018, 2019, 2020, 2021, 2022, 2023, 2024]:
    download_bhuvan_kharif_stack(
        state='Kerala', year=yr,
        output_path=f'./bhuvan_kharif_kerala_{yr}.tif',
    )
```

See `example_bhuvan.py`.

## Output

One GeoTIFF per `(state, year)`:

- driver: GeoTIFF, BigTIFF if needed
- dtype: `uint8` (0 = land / no data, 1 = flood)
- count: 140 bands
- CRS: EPSG:4326
- compression: deflate + predictor 2, tiled 256×256
- band descriptions: ISO date strings (`2023-06-01` … `2023-10-18`)
- band tags: `date`, `bhuvan_layer`
- file tags: `state`, `year`, `n_bands`, `kharif_window`, `source`

## Module layout

| Module               | Role                                            |
| -------------------- | ----------------------------------------------- |
| `config.py`          | State → (code, bbox) mapping, grid constants    |
| `wms_client.py`      | URL building, layer probe, tile fetch           |
| `stitch.py`          | Stitch tiles + cyan-pixel test                  |
| `pipeline.py`        | Orchestrator: streaming multi-band write        |
