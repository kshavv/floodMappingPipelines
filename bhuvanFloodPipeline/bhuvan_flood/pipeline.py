"""Top-level entry point.

For one (state, year), iterate over every calendar day in the Kharif
window (Jun 1 → Oct 4, matching the GEE classifier's Kharif slot
range), probe Bhuvan for that day's layer, fetch + stitch the tiles,
and pack the resulting 0/1 masks into a single multi-band GeoTIFF with
one band per ISO date.

Days with no Bhuvan data become all-zero bands (so the band count is
constant and the time index is preserved). Band names are the ISO
dates.

Memory note
-----------
A state-sized canvas at Bhuvan's zoom 10 is ~5000×7000 pixels per
band; 140 bands × that × uint8 ≈ 5 GiB. We never hold the full stack
in RAM — bands are written to disk one at a time as they're computed.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.crs import CRS

from .config import state_config
from .stitch import empty_mask_for_bbox, stitch_date
from .wms_client import BhuvanClient, layer_name


# --- Date helpers ---------------------------------------------------------
# Match the GEE classifier's Kharif window: Jun 1 → Oct 4 inclusive,
# which is 10 bi-weeks * 14 days = 140 days.
KHARIF_START_MONTH = 6
KHARIF_START_DAY = 1
KHARIF_N_DAYS = 140


def kharif_dates(year: int) -> List[_dt.date]:
    """Every calendar day in the Kharif window for ``year``."""
    start = _dt.date(year, KHARIF_START_MONTH, KHARIF_START_DAY)
    return [start + _dt.timedelta(days=i) for i in range(KHARIF_N_DAYS)]


# --- GeoTIFF writer (streamed, one band at a time) ------------------------

def _open_stack_writer(path: Path,
                       shape: Tuple[int, int],
                       transform: Tuple[float, ...],
                       n_bands: int):
    """Open a new multi-band uint8 GeoTIFF for streaming band writes.

    Returns the open ``rasterio`` dataset; caller is responsible for
    closing it. Compression is deflate; the file is tiled so partial
    bands stream efficiently.
    """
    height, width = shape
    a, b, c, d, e, f = transform
    aff = Affine(a, b, c, d, e, f)
    profile = {
        'driver':    'GTiff',
        'dtype':     'uint8',
        'count':     n_bands,
        'height':    height,
        'width':     width,
        'transform': aff,
        'crs':       CRS.from_epsg(4326),
        'compress':  'deflate',
        'predictor': 2,
        'tiled':     True,
        'blockxsize': 256,
        'blockysize': 256,
        'nodata':    None,
        'BIGTIFF':   'IF_SAFER',
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    return rasterio.open(path, 'w', **profile)


# --- Public entry point ---------------------------------------------------

def download_bhuvan_kharif_stack(
    state: str,
    year: int,
    output_path: str,
    *,
    client: Optional[BhuvanClient] = None,
    log: bool = True,
) -> dict:
    """Build the multi-band Kharif flood stack for ``(state, year)``.

    Parameters
    ----------
    state
        State name registered in ``config.STATES`` (e.g. ``"Kerala"``).
    year
        Calendar year. The Kharif window is Jun 1 → Oct 4 of this year
        (140 days = 140 bands).
    output_path
        Destination GeoTIFF path. Parent directories are created.
    client
        Optional pre-built :class:`BhuvanClient`. A default one is
        created if not supplied.
    log
        Print a one-line status per day.

    Returns
    -------
    dict
        Summary of what got built::

            {
              'state':           'Kerala',
              'year':            2023,
              'output_path':     '/.../bhuvan_kharif_kerala_2023.tif',
              'n_bands':         140,
              'n_days_with_data':  37,
              'days_with_data':  ['2023-06-16', ...],
              'days_without':    ['2023-06-01', ...],
              'layers_used':     {'2023-06-16': 'flood:kl_2023_16_06_06', ...},
              'bbox':            (74.5, 8.0, 78.0, 13.0),
            }
    """
    cfg = state_config(state)
    code = cfg['code']
    bbox = cfg['bbox']
    client = client or BhuvanClient()

    # A small probe bbox INSIDE the state so the existence probe can
    # detect "layer exists" by checking for any non-transparent pixel.
    # We use the center of the state's bbox, snapped to the tile grid.
    from .wms_client import covering_tiles, tile_bbox as _tile_bbox
    tx_min, ty_min, tx_max, ty_max = covering_tiles(bbox)
    probe_tx = (tx_min + tx_max) // 2
    probe_ty = (ty_min + ty_max) // 2
    probe_bbox = _tile_bbox(probe_tx, probe_ty)

    dates = kharif_dates(year)
    band_dates = [d.isoformat() for d in dates]

    # Pre-allocate ONLY a single-band canvas (used as the empty fallback)
    # and learn the output shape + transform from it. The full multi-band
    # stack is never held in RAM — bands stream directly to the GeoTIFF
    # as they're computed.
    empty, transform = empty_mask_for_bbox(bbox)
    height, width = empty.shape

    layers_used: List[str] = []
    days_with: List[str] = []
    days_without: List[str] = []

    out = Path(output_path)
    dst = _open_stack_writer(out, (height, width), transform, len(dates))
    try:
        for i, d in enumerate(dates):
            iso = d.isoformat()
            band_idx = i + 1
            if log:
                print(f'[{band_idx:3d}/{len(dates)}] {iso}  resolving layer …',
                      end=' ', flush=True)
            layer = client.resolve_layer_for_date(code, iso,
                                                  probe_bbox=probe_bbox)
            if layer is None:
                layers_used.append('')
                days_without.append(iso)
                # Write the pre-built empty band; cheap, and keeps every
                # band's shape/transform identical.
                dst.write(empty, band_idx)
                dst.set_band_description(band_idx, iso)
                dst.update_tags(band_idx, date=iso, bhuvan_layer='NONE')
                if log:
                    print('(no data)')
                continue
            if log:
                print(f'{layer}  stitching …', end=' ', flush=True)
            mask, t2 = stitch_date(client, layer, bbox)
            # Sanity: the stitch transform must match the pre-allocated one
            # (same tile grid, same zoom). If it doesn't, the bbox produced
            # a different covering set — should never happen, but assert so
            # the failure is loud.
            if t2 != transform or mask.shape != (height, width):
                raise RuntimeError(
                    f'Tile-grid mismatch on {iso}: '
                    f'transform {t2} vs {transform}, '
                    f'shape {mask.shape} vs {(height, width)}')
            dst.write(mask, band_idx)
            dst.set_band_description(band_idx, iso)
            dst.update_tags(band_idx, date=iso, bhuvan_layer=layer)
            layers_used.append(layer)
            days_with.append(iso)
            if log:
                print(f'flood-pixels={int(mask.sum())}')

        # File-level tags.
        dst.update_tags(
            state=state,
            year=str(year),
            n_bands=str(len(dates)),
            kharif_window=f'{band_dates[0]} → {band_dates[-1]}',
            source='Bhuvan WMS (NRSC), flood layer',
        )
    finally:
        dst.close()

    if log:
        print(f'\n✓ Wrote {out}  ({len(days_with)}/{len(dates)} days with data)')

    return {
        'state':            state,
        'year':             year,
        'output_path':      str(out),
        'n_bands':          len(dates),
        'n_days_with_data': len(days_with),
        'days_with_data':   days_with,
        'days_without':     days_without,
        'layers_used':      dict(zip(band_dates, layers_used)),
        'bbox':             bbox,
    }
