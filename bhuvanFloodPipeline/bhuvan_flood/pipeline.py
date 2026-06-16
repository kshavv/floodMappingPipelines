"""Top-level entry point.

Days with no Bhuvan data become all-zero bands (so the band count is
constant and the time index is preserved). Band names are the ISO
dates.

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
                       n_bands: int,
                       *,
                       nodata=None):
    """Open a new multi-band uint8 GeoTIFF for streaming band writes."""
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
        'nodata':    nodata,
        'BIGTIFF':   'IF_SAFER',
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    return rasterio.open(path, 'w', **profile)


# --- Helpers --------------------------------------------------------------

def _slugify(name: str) -> str:
    import re
    s = (name or '').lower()
    s = re.sub(r'&', ' and ', s)
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def _default_output_path(state: str, year: int, district: Optional[str]) -> str:
    parts = ['bhuvan_kharif', _slugify(state)]
    if district:
        parts.append(_slugify(district))
    parts.append(str(year))
    return f"./{'_'.join(parts)}.tif"


def _default_day_output_path(state: str, date_iso: str,
                             district: Optional[str]) -> str:
    parts = ['bhuvan_flood', _slugify(state)]
    if district:
        parts.append(_slugify(district))
    parts.append(date_iso)
    return f"./{'_'.join(parts)}.tif"


def _default_biweek_output_path(state: str, year: int, district: Optional[str],
                                method: str) -> str:
    parts = ['bhuvan_kharif_biweek', _slugify(state)]
    if district:
        parts.append(_slugify(district))
    parts.append(str(year))
    parts.append(method)
    return f"./{'_'.join(parts)}.tif"


def _resolve_aoi(state, district, district_geometry, bbox_buffer_deg,
                 *, clip_to_state=True):
    """Shared AOI resolution for both the year and day endpoints.

    Returns ``(cfg, polygon_or_None, aoi_bbox, aoi_label)`` so the two
    endpoints can stop duplicating this logic.

    In whole-state mode (no ``district`` / ``district_geometry``), when
    ``clip_to_state=True`` (the default), we also pull the GAUL level-1
    polygon for the state and return it as the mask polygon — so the
    output is state-shaped, not bbox-shaped. If EE isn't available or
    the lookup fails, we fall back to the bbox rectangle with a
    warning. Set ``clip_to_state=False`` to skip the polygon clip and
    force the bbox-only behaviour.
    """
    cfg = state_config(state)
    polygon = None
    if district_geometry is not None:
        polygon = district_geometry
        minx, miny, maxx, maxy = polygon.bounds
        aoi_bbox = (minx - bbox_buffer_deg, miny - bbox_buffer_deg,
                    maxx + bbox_buffer_deg, maxy + bbox_buffer_deg)
        aoi_label = f'{state} / {district or "custom"}'
    elif district is not None:
        from .districts import resolve_district, buffer_bbox
        from shapely.geometry import shape
        geojson, raw_bbox = resolve_district(state, district)
        polygon = shape(geojson)
        aoi_bbox = buffer_bbox(raw_bbox, bbox_buffer_deg)
        aoi_label = f'{state} / {district}'
    else:
        aoi_bbox = cfg['bbox']
        aoi_label = state
        if clip_to_state:
            # Try to clip the output to the actual state polygon. If EE
            # isn't available, isn't initialised, or the lookup fails
            # for any reason, fall back to the bbox rectangle.
            try:
                from .config import state_polygon
                from shapely.geometry import shape
                geojson, _raw_bbox = state_polygon(state)
                polygon = shape(geojson)
            except Exception as exc:
                print(f'  ⚠ State-polygon clip unavailable '
                      f'({exc.__class__.__name__}: {exc}); falling '
                      f'back to bbox rectangle.')
    return cfg, polygon, aoi_bbox, aoi_label


def _pick_probe_bbox(aoi_bbox, polygon):
    """Pick one grid-aligned tile bbox INSIDE the AOI for layer probing."""
    from .wms_client import covering_tiles, tile_bbox as _tile_bbox
    tx_min, ty_min, tx_max, ty_max = covering_tiles(aoi_bbox)
    if polygon is not None:
        from shapely.geometry import box
        for ty in range(ty_min, ty_max + 1):
            for tx in range(tx_min, tx_max + 1):
                tb = _tile_bbox(tx, ty)
                if polygon.intersects(box(*tb)):
                    return tb
        raise RuntimeError(
            'No tile in the AOI bbox intersects the polygon. '
            'Check `district` name or `district_geometry`.')
    probe_tx = (tx_min + tx_max) // 2
    probe_ty = (ty_min + ty_max) // 2
    return _tile_bbox(probe_tx, probe_ty)


# --- Public entry point ---------------------------------------------------

def _count_polygon_vertices(geom) -> int:
    """Total exterior vertex count across any shapely geometry."""
    t = geom.geom_type
    if t == 'Polygon':
        return len(geom.exterior.coords)
    if t == 'MultiPolygon':
        return sum(len(p.exterior.coords) for p in geom.geoms)
    if t == 'GeometryCollection':
        return sum(_count_polygon_vertices(g) for g in geom.geoms)
    return 0


def _print_debug_header(*, state, district, district_geometry,
                        cfg, polygon, aoi_bbox, aoi_label,
                        all_tiles, kept_tiles,
                        sample_first, sample_last, sample_dates,
                        bbox_buffer_deg, output_path, year):
    """Upfront diagnostic block: prints what the run is about to do."""
    print('=' * 70)
    print('STEP 1 — State config')
    print('=' * 70)
    print(f"  State           : {state}")
    print(f"  Bhuvan code     : {cfg['code']!r}")
    print(f"  GAUL name       : {cfg['gaul']!r}")
    print(f"  State bbox      : {cfg['bbox']}")
    sw = cfg['bbox'][2] - cfg['bbox'][0]
    sh = cfg['bbox'][3] - cfg['bbox'][1]
    print(f"    width         : {sw:.4f}° (~{sw*111:.0f} km)")
    print(f"    height        : {sh:.4f}° (~{sh*111:.0f} km)")

    print()
    print('=' * 70)
    if polygon is not None:
        print('STEP 2 — AOI = district polygon')
        print('=' * 70)
        src = 'district_geometry param' if district_geometry is not None \
              else f'FAO GAUL level-2: {district!r}'
        print(f"  AOI source        : {src}")
        print(f"  Geometry type     : {polygon.geom_type}")
        n_pieces = (len(polygon.geoms)
                    if polygon.geom_type in ('MultiPolygon',
                                              'GeometryCollection')
                    else 1)
        print(f"  Sub-geometries    : {n_pieces}")
        print(f"  Total vertices    : {_count_polygon_vertices(polygon)}")
        print(f"  Polygon area (°²) : {polygon.area:.4f}")
        print(f"  Buffered bbox     : {aoi_bbox}")
        print(f"  Buffer applied    : {bbox_buffer_deg}° "
              f"(~{bbox_buffer_deg*111:.1f} km)")
    else:
        print('STEP 2 — AOI = whole-state bbox')
        print('=' * 70)
        print(f"  AOI bbox          : {aoi_bbox}")
        print(f"  No polygon filter — every tile in the covering set "
              f"will be fetched.")
        print(f"  Output will be bbox-shaped, not state-shaped.")

    print()
    print('=' * 70)
    print('STEP 3 — Tile-grid covering at Bhuvan zoom 10')
    print('=' * 70)
    from .wms_client import covering_tiles
    tx_min, ty_min, tx_max, ty_max = covering_tiles(aoi_bbox)
    n_tx = tx_max - tx_min + 1
    n_ty = ty_max - ty_min + 1
    print(f"  Tile-x range      : {tx_min}..{tx_max}  ({n_tx} cols)")
    print(f"  Tile-y range      : {ty_min}..{ty_max}  ({n_ty} rows)")
    print(f"  Total tiles       : {len(all_tiles)}  (= {n_tx} × {n_ty})")
    canvas_mb = n_tx * n_ty * 256 * 256 * 4 / 1e6
    print(f"  Canvas size       : {n_tx*256} × {n_ty*256} px "
          f"(~{canvas_mb:.0f} MB RGBA per day in RAM)")

    if polygon is not None:
        print()
        print('=' * 70)
        print('STEP 4 — Polygon filter')
        print('=' * 70)
        dropped = len(all_tiles) - len(kept_tiles)
        print(f"  Tiles before      : {len(all_tiles)}")
        print(f"  Tiles dropped     : {dropped} (no polygon overlap)")
        print(f"  Tiles kept        : {len(kept_tiles)}")
        if len(all_tiles):
            print(f"  Reduction         : "
                  f"{100*dropped/len(all_tiles):.0f}%")

    print()
    print('=' * 70)
    print(f"STEP 5 — Sample tiles (first 3 + last 3 of "
          f"{len(kept_tiles)} to fetch)")
    print('=' * 70)
    from .wms_client import tile_bbox as _tb
    n = len(kept_tiles)
    show_idx = sorted(set(list(range(min(3, n))) + list(range(max(0, n-3), n))))
    last_shown = -1
    for i in show_idx:
        if i > last_shown + 1:
            print(f"    … ({i - last_shown - 1} tiles in the middle) …")
        tx, ty = kept_tiles[i]
        b = _tb(tx, ty)
        print(f"    [{i+1:>4}/{n}] tx={tx} ty={ty}  "
              f"bbox=({b[0]:.4f}, {b[1]:.4f}, {b[2]:.4f}, {b[3]:.4f})")
        last_shown = i

    print()
    print('=' * 70)
    print('STEP 6 — Run plan')
    print('=' * 70)
    print(f"  AOI label         : {aoi_label}")
    print(f"  Year              : {year}")
    print(f"  Kharif days       : {len(sample_dates)}")
    print(f"  Date range        : {sample_dates[0]} → {sample_dates[-1]}")
    print(f"  Tiles per data-day: {len(kept_tiles)}")
    print(f"  Output path       : {output_path}")
    print(f"  Layer name shape  : flood:{cfg['code']}_YYYY_DD_MM[_HH]")
    print(f"  Probe suffixes    : '', '_06', '_12', '_18' "
          f"(first hit wins)")
    print()
    est_lo = len(kept_tiles) * 0.10
    est_hi = len(kept_tiles) * 0.30
    print(f"  Per-day stitch    : ~{est_lo:.0f}–{est_hi:.0f}s "
          f"at typical Bhuvan latency.")
    print(f"  (No-data days cost only 1–4 probe requests.)")
    print('=' * 70)
    print()


def download_bhuvan_kharif_stack(
    state: str,
    year: int,
    output_path: Optional[str] = None,
    *,
    district: Optional[str] = None,
    district_geometry=None,
    bbox_buffer_deg: float = 0.05,
    clip_to_state: bool = True,
    client: Optional[BhuvanClient] = None,
    log: bool = True,
    debug: bool = False,
    verbose: bool = False,
    tile_cache_dir: Optional[str] = None,
) -> dict:
    """Download and stitch Bhuvan flood layers for the Kharif season of a year."""
    cfg, polygon, aoi_bbox, aoi_label = _resolve_aoi(
        state, district, district_geometry, bbox_buffer_deg,
        clip_to_state=clip_to_state)
    code = cfg['code']
    client = client or BhuvanClient()

    if output_path is None:
        output_path = _default_output_path(state, year, district)

    probe_bbox = _pick_probe_bbox(aoi_bbox, polygon)

    dates = kharif_dates(year)
    band_dates = [d.isoformat() for d in dates]

    # Pre-allocate ONLY a single-band canvas (used as the empty fallback)
    # and learn the output shape + transform from it.
    empty, transform = empty_mask_for_bbox(aoi_bbox)
    height, width = empty.shape

    # When a polygon is given (district mode OR clip_to_state in
    # whole-state mode), build the inside-mask once. Outside-polygon
    # pixels will be written as 255 (nodata), so QGIS/GDAL respect the
    # state shape rather than rendering a bbox rectangle.
    import numpy as _np
    if polygon is not None:
        from .stitch import _polygon_pixel_mask
        inside_mask = _polygon_pixel_mask(polygon, transform, height, width)
        # `empty` is the no-data band template; set outside-polygon to
        # 255 so no-data days look the same as data-days outside Kerala.
        empty = _np.where(inside_mask == 1, 0, 255).astype('uint8')
    else:
        inside_mask = _np.ones((height, width), dtype='uint8')

    layers_used: List[str] = []
    days_with: List[str] = []
    days_without: List[str] = []

    # Compute tile counts once so they're available to both the debug
    # header (if asked for) and the brief log line below.
    from .wms_client import tiles_for_bbox
    all_tiles = tiles_for_bbox(aoi_bbox)
    if polygon is not None:
        from .stitch import filter_tiles_by_polygon
        kept_tiles = filter_tiles_by_polygon(all_tiles, polygon)
    else:
        kept_tiles = all_tiles

    if debug:
        _print_debug_header(
            state=state, district=district, district_geometry=district_geometry,
            cfg=cfg, polygon=polygon, aoi_bbox=aoi_bbox, aoi_label=aoi_label,
            all_tiles=all_tiles, kept_tiles=kept_tiles,
            sample_first=3, sample_last=3, sample_dates=band_dates,
            bbox_buffer_deg=bbox_buffer_deg, output_path=str(output_path),
            year=year,
        )
    elif log:
        # Compact one-block summary when debug is off but log is on.
        print(f'AOI: {aoi_label}')
        print(f'  bbox  : {aoi_bbox}')
        print(f'  canvas: {width} x {height} px')
        if polygon is not None:
            print(f'  tiles : {len(kept_tiles)} of {len(all_tiles)} '
                  f'(polygon filter)')
        else:
            print(f'  tiles : {len(kept_tiles)} (whole bbox)')
        print()

    out = Path(output_path)
    dst = _open_stack_writer(out, (height, width), transform, len(dates),
                             nodata=255 if polygon is not None else None)
    try:
        for i, d in enumerate(dates):
            iso = d.isoformat()
            band_idx = i + 1
            if log:
                print(f'[{band_idx:3d}/{len(dates)}] {iso}  resolving layer …',
                      end=' ', flush=True)
            layer = client.resolve_layer_for_date(code, iso,
                                                  probe_bbox=probe_bbox,
                                                  verbose=debug or verbose)
            if layer is None:
                layers_used.append('')
                days_without.append(iso)
                dst.write(empty, band_idx)
                dst.set_band_description(band_idx, iso)
                dst.update_tags(band_idx, date=iso, bhuvan_layer='NONE')
                if log:
                    print('(no data)')
                continue
            if log:
                print(f'{layer}  stitching …', end=' ' if not verbose else '\n', flush=True)
            mask, t2, stitch_info = stitch_date(
                client, layer, aoi_bbox,
                polygon=polygon,
                verbose=verbose,
                tile_cache_dir=tile_cache_dir,
                return_info=True,
            )
            if t2 != transform or mask.shape != (height, width):
                raise RuntimeError(
                    f'Tile-grid mismatch on {iso}: '
                    f'transform {t2} vs {transform}, '
                    f'shape {mask.shape} vs {(height, width)}')
            if stitch_info['aborted_early']:
                # Circuit breaker tripped — Bhuvan can't serve this
                # layer at the full AOI extent. Treat as no-data: write
                # the empty band, record the dud layer name so the
                # audit trail captures what we tried.
                layers_used.append('')
                days_without.append(iso)
                dst.write(empty, band_idx)
                dst.set_band_description(band_idx, iso)
                dst.update_tags(band_idx, date=iso,
                                bhuvan_layer=f'ABORTED:{layer}')
                if log:
                    fails = stitch_info['tiles_failed']
                    total = stitch_info['tiles_total']
                    print(f'(circuit-breaker abort: {fails}/{total} '
                          f'tiles failed — treating as no-data)')
                continue
            # Encode outside-polygon pixels as 255 nodata.
            if polygon is not None:
                mask = mask.copy()
                mask[inside_mask == 0] = 255
            dst.write(mask, band_idx)
            dst.set_band_description(band_idx, iso)
            dst.update_tags(band_idx, date=iso, bhuvan_layer=layer)
            layers_used.append(layer)
            days_with.append(iso)
            if log:
                inside_flood = int(((mask != 255) & (mask == 1)).sum())
                print(f'flood-pixels={inside_flood}')

        # File-level tags.
        # File-level tags. Includes a summary of which dates had data
        # so you can answer "is this band's all-zero a real dry day or
        # a no-data day?" without scanning per-band tags.
        n_with = len(days_with)
        n_without = len(days_without)
        # Bands marked ABORTED — circuit-breaker aborts (probe passed
        # but Bhuvan couldn't serve the layer at the AOI extent).
        aborted_bands = [
            band_dates[i]
            for i, lyr in enumerate(layers_used)
            if lyr == '' and band_dates[i] in days_without
        ]
        file_tags = {
            'state':            state,
            'year':             str(year),
            'n_bands':          str(len(dates)),
            'kharif_window':    f'{band_dates[0]} → {band_dates[-1]}',
            'source':           'Bhuvan WMS (NRSC), flood layer',
            # Summary of which dates Bhuvan actually had data for.
            'n_days_with_data': str(n_with),
            'n_days_no_data':   str(n_without),
            'days_with_data':   ','.join(days_with),     # ISO-date CSV
            'days_no_data':     ','.join(days_without),  # ISO-date CSV
            'bands_with_data':  ','.join(
                str(i + 1) for i, d in enumerate(band_dates) if d in days_with),
            'bands_no_data':    ','.join(
                str(i + 1) for i, d in enumerate(band_dates) if d in days_without),
        }
        if district:
            file_tags['district'] = district
            file_tags['aoi_mode'] = 'district'
        elif district_geometry is not None:
            file_tags['aoi_mode'] = 'custom_geometry'
        else:
            file_tags['aoi_mode'] = 'state_bbox'
        dst.update_tags(**file_tags)
    finally:
        dst.close()

    if log:
        print(f'\n✓ Wrote {out}  '
              f'({len(days_with)}/{len(dates)} days with data)')

    return {
        'state':            state,
        'district':         district,
        'year':             year,
        'output_path':      str(out),
        'n_bands':          len(dates),
        'n_days_with_data': len(days_with),
        'days_with_data':   days_with,
        'days_without':     days_without,
        'layers_used':      dict(zip(band_dates, layers_used)),
        'bbox':             aoi_bbox,
    }


# ---------------------------------------------------------------------------
# Single-day endpoint
# ---------------------------------------------------------------------------

def download_bhuvan_flood_day(
    state: str,
    date: str,
    output_path: Optional[str] = None,
    *,
    district: Optional[str] = None,
    district_geometry=None,
    bbox_buffer_deg: float = 0.05,
    clip_to_state: bool = True,
    client: Optional[BhuvanClient] = None,
    debug: bool = False,
    verbose: bool = False,
    tile_cache_dir: Optional[str] = None,
) -> dict:

    import datetime as _dt
    try:
        _dt.date.fromisoformat(date)
    except ValueError:
        raise ValueError(f'`date` must be ISO YYYY-MM-DD; got {date!r}.')

    cfg, polygon, aoi_bbox, aoi_label = _resolve_aoi(
        state, district, district_geometry, bbox_buffer_deg,
        clip_to_state=clip_to_state)
    code = cfg['code']
    client = client or BhuvanClient()

    if output_path is None:
        output_path = _default_day_output_path(state, date, district)

    probe_bbox = _pick_probe_bbox(aoi_bbox, polygon)

    # Pre-tile listing for the debug header.
    from .wms_client import tiles_for_bbox
    all_tiles = tiles_for_bbox(aoi_bbox)
    if polygon is not None:
        from .stitch import filter_tiles_by_polygon
        kept_tiles = filter_tiles_by_polygon(all_tiles, polygon)
    else:
        kept_tiles = all_tiles

    if debug:
        _print_debug_header(
            state=state, district=district,
            district_geometry=district_geometry,
            cfg=cfg, polygon=polygon, aoi_bbox=aoi_bbox, aoi_label=aoi_label,
            all_tiles=all_tiles, kept_tiles=kept_tiles,
            sample_first=3, sample_last=3, sample_dates=[date],
            bbox_buffer_deg=bbox_buffer_deg, output_path=str(output_path),
            year=int(date[:4]),
        )

    # ── Resolve which (if any) suffix has data ────────────────────
    if debug:
        print(f'STEP 7 — Probing Bhuvan for {date!r}')
        print('=' * 70)
    layer = client.resolve_layer_for_date(
        code, date, probe_bbox=probe_bbox, verbose=debug or verbose)
    if debug:
        if layer:
            print(f'  ✓ Layer found: {layer}')
        else:
            print(f'  ✗ No layer for {date}. Writing all-zero band.')
        print()

    # ── Build the canvas + (optional) polygon mask ────────────────
    # inside_mask: 1 inside polygon, 0 outside (or all-1 if no polygon).
    # Outside-polygon pixels are written as 255 (nodata) — QGIS / GDAL
    # respect the nodata tag and the state shape becomes visible,
    # not a bounding rectangle of 0s.
    import numpy as _np
    empty, transform = empty_mask_for_bbox(aoi_bbox)
    height, width = empty.shape
    if polygon is not None:
        from .stitch import _polygon_pixel_mask
        inside_mask = _polygon_pixel_mask(polygon, transform, height, width)
        # Make the no-data template 255-outside so it matches data-day
        # bands.
        empty = _np.where(inside_mask == 1, 0, 255).astype('uint8')
    else:
        inside_mask = _np.ones((height, width), dtype='uint8')

    # ── Stitch (or fall through to all-zero) ───────────────────────
    stitch_aborted = False
    if layer is not None:
        if debug:
            print(f'STEP 8 — Fetching {len(kept_tiles)} tiles')
            print('=' * 70)
        mask, _, stitch_info = stitch_date(
            client, layer, aoi_bbox,
            polygon=polygon,
            verbose=verbose,
            tile_cache_dir=tile_cache_dir,
            return_info=True,
        )
        if stitch_info['aborted_early']:
            stitch_aborted = True
            if debug:
                print(f"  ✗ Circuit breaker tripped after "
                      f"{stitch_info['tiles_attempted']} tiles "
                      f"(all {stitch_info['tiles_failed']} failed). "
                      f"Treating {date} as no-data.")
            mask = empty
            layer = None        # so the tag below records 'NONE'
    else:
        mask = empty

    flood_pixels = int(mask.sum())
    # flood_pixels = int((mask == 1).sum())

    # Encode outside-polygon as 255 (nodata). Inside the polygon, the
    # mask values 0/1 are preserved verbatim.
    if polygon is not None:
        mask = mask.copy()
        mask[inside_mask == 0] = 255

    # ── Write the single-band GeoTIFF ──────────────────────────────
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    a, b, c, d, e, f = transform
    profile = {
        'driver':    'GTiff',
        'dtype':     'uint8',
        'count':     1,
        'height':    height,
        'width':     width,
        'transform': Affine(a, b, c, d, e, f),
        'crs':       CRS.from_epsg(4326),
        'compress':  'deflate',
        'predictor': 2,
        'tiled':     True,
        'blockxsize': 256,
        'blockysize': 256,
        'nodata':    255 if polygon is not None else None,
        # 'nodata':    255,
    }
    with rasterio.open(out, 'w', **profile) as dst:
        dst.write(mask, 1)
        dst.set_band_description(1, date)
        dst.update_tags(1, date=date, bhuvan_layer=layer or 'NONE')
        tags = {
            'state':    state,
            'date':     date,
            'aoi_mode': ('district' if district else
                         ('custom_geometry' if district_geometry is not None
                          else 'state_bbox')),
            'source':   'Bhuvan WMS (NRSC), flood layer',
        }
        if district:
            tags['district'] = district
        dst.update_tags(**tags)

    if debug:
        print()
        print('=' * 70)
        print(f'STEP 9 — Summary')
        print('=' * 70)
        print(f'  Output           : {out}')
        print(f'  Layer used       : {layer or "(none)"}')
        print(f'  Has data         : {layer is not None}')
        print(f'  Mask shape       : {mask.shape}')
        print(f'  Flood pixels     : {flood_pixels:,}')
        print(f'  % of canvas      : '
              f'{100*flood_pixels/max(mask.size,1):.4f}%')
        print('=' * 70)
    else:
        print(f'✓ {date}  {aoi_label}  '
              f'layer={layer or "NONE":>30s}  '
              f'flood_px={flood_pixels:,}  → {out}')

    return {
        'state':         state,
        'district':      district,
        'date':          date,
        'output_path':   str(out),
        'layer_used':    layer,
        'has_data':      layer is not None,
        'flood_pixels':  flood_pixels,
        'bbox':          aoi_bbox,
    }

# ---------------------------------------------------------------------------
# Bi-weekly endpoint
# ---------------------------------------------------------------------------

def download_bhuvan_kharif_biweek_stack(
    state: str,
    year: int,
    output_path: Optional[str] = None,
    *,
    method: str = 'union',
    district: Optional[str] = None,
    district_geometry=None,
    bbox_buffer_deg: float = 0.05,
    clip_to_state: bool = True,
    client: Optional[BhuvanClient] = None,
    log: bool = True,
    debug: bool = False,
    verbose: bool = False,
    tile_cache_dir: Optional[str] = None,
) -> dict:
    """Download Bhuvan flood layers and aggregate into 10 Kharif bi-weeks.

    Matches the 14-day grid used by the GEE flood-classification
    pipeline: BW_12 (starts Jun 4) through BW_21 (ends Oct 7), 10
    bands total. Each band is one bi-week.

    Parameters
    ----------
    method
        How to combine the ~14 days of Bhuvan masks within each
        bi-week into a single band. Currently supported:

        ``'union'``         — logical OR. Pixel is 1 if any day in
                              the bi-week was flooded at that pixel.
        ``'mid_snapshot'``  — pick the data-day nearest the bi-week
                              midpoint (Day 7); ties go to the
                              earlier date.

        Add more strategies by extending ``biweek.COMBINERS``.

    All other parameters are the same as ``download_bhuvan_kharif_stack``.
    See that function for AOI / clipping / logging / probe options.

    Returns
    -------
    dict
        Run summary including which date(s) fed each bi-week band.
    """
    from .biweek import (
        COMBINERS, KHARIF_BW_NUMBERS, KHARIF_BW_LENGTH_DAYS,
        biweek_label, combine_union, combine_mid_snapshot,
        kharif_biweek_dates, kharif_biweek_starts,
    )

    if method not in COMBINERS:
        raise ValueError(
            f'Unknown method {method!r}. Known: {sorted(COMBINERS)}')

    cfg, polygon, aoi_bbox, aoi_label = _resolve_aoi(
        state, district, district_geometry, bbox_buffer_deg,
        clip_to_state=clip_to_state)
    code = cfg['code']
    client = client or BhuvanClient()

    if output_path is None:
        output_path = _default_biweek_output_path(state, year, district, method)

    probe_bbox = _pick_probe_bbox(aoi_bbox, polygon)

    biweek_starts = kharif_biweek_starts(year)
    biweek_dates  = kharif_biweek_dates(year)

    # All daily dates in flat order, plus a reverse map back to (bw_idx, day).
    flat_dates: List[_dt.date] = []
    date_to_bw: Dict[_dt.date, int] = {}
    for bw_idx, days in enumerate(biweek_dates):
        for d in days:
            flat_dates.append(d)
            date_to_bw[d] = bw_idx

    # Empty (no-data) template — same logic as the daily year endpoint.
    import numpy as _np
    empty, transform = empty_mask_for_bbox(aoi_bbox)
    height, width = empty.shape
    if polygon is not None:
        from .stitch import _polygon_pixel_mask
        inside_mask = _polygon_pixel_mask(polygon, transform, height, width)
        empty = _np.where(inside_mask == 1, 0, 255).astype('uint8')
    else:
        inside_mask = _np.ones((height, width), dtype='uint8')

    # Tile listing for debug header.
    from .wms_client import tiles_for_bbox
    all_tiles = tiles_for_bbox(aoi_bbox)
    if polygon is not None:
        from .stitch import filter_tiles_by_polygon
        kept_tiles = filter_tiles_by_polygon(all_tiles, polygon)
    else:
        kept_tiles = all_tiles

    if debug:
        _print_debug_header(
            state=state, district=district,
            district_geometry=district_geometry,
            cfg=cfg, polygon=polygon, aoi_bbox=aoi_bbox, aoi_label=aoi_label,
            all_tiles=all_tiles, kept_tiles=kept_tiles,
            sample_first=3, sample_last=3,
            sample_dates=[d.isoformat() for d in flat_dates],
            bbox_buffer_deg=bbox_buffer_deg, output_path=str(output_path),
            year=year,
        )
        print(f'  Bi-week method  : {method}')
        print(f'  Bi-week bands   : {len(KHARIF_BW_NUMBERS)} '
              f'(BW_12 .. BW_21)')
        for bw_idx in range(len(KHARIF_BW_NUMBERS)):
            print(f'    {biweek_label(year, bw_idx)}')
        print()
    elif log:
        print(f'AOI: {aoi_label}')
        print(f'  bbox    : {aoi_bbox}')
        print(f'  method  : {method}')
        print(f'  bi-weeks: {len(KHARIF_BW_NUMBERS)} (BW_12 .. BW_21)')
        print()

    # ── Accumulator state per bi-week ──────────────────────────────
    # For 'union': the running OR-result mask, updated as each
    # data-day arrives. Starts as None until the first data-day in
    # that bi-week; finalised to `empty` if no data days appeared.
    #
    # For 'mid_snapshot': the candidate (date, mask) — replaced
    # whenever we see a data-day that's closer to the bi-week
    # midpoint than the current candidate.
    union_running: List[Optional[_np.ndarray]] = [None] * len(KHARIF_BW_NUMBERS)
    snap_candidate: List[Optional[Tuple[_dt.date, _np.ndarray]]] = [
        None] * len(KHARIF_BW_NUMBERS)
    bw_data_days: List[List[str]] = [[] for _ in KHARIF_BW_NUMBERS]
    bw_layers_used: List[List[str]] = [[] for _ in KHARIF_BW_NUMBERS]
    bw_chosen_date: List[Optional[str]] = [None] * len(KHARIF_BW_NUMBERS)

    def _update_union(bw_idx: int, mask: _np.ndarray) -> None:
        cur = union_running[bw_idx]
        if cur is None:
            union_running[bw_idx] = combine_union([mask])
        else:
            union_running[bw_idx] = combine_union([cur, mask])

    def _update_snapshot(bw_idx: int, d: _dt.date, mask: _np.ndarray) -> None:
        midpoint = biweek_starts[bw_idx] + _dt.timedelta(days=7)
        new_score = (abs((d - midpoint).days), d)
        cur = snap_candidate[bw_idx]
        if cur is None:
            snap_candidate[bw_idx] = (d, mask)
            return
        cur_d, _ = cur
        cur_score = (abs((cur_d - midpoint).days), cur_d)
        if new_score < cur_score:
            snap_candidate[bw_idx] = (d, mask)

    # ── Main loop: iterate every daily date, fetch when present ────
    n_days = len(flat_dates)
    for i, d in enumerate(flat_dates):
        iso = d.isoformat()
        bw_idx = date_to_bw[d]
        if log:
            print(f'[{i+1:3d}/{n_days}] {iso}  (BW_{KHARIF_BW_NUMBERS[bw_idx]})  '
                  f'resolving …', end=' ', flush=True)

        layer = client.resolve_layer_for_date(
            code, iso, probe_bbox=probe_bbox, verbose=debug or verbose)
        if layer is None:
            if log: print('(no data)')
            continue

        if log:
            print(f'{layer}  stitching …',
                  end=' ' if not verbose else '\n', flush=True)
        mask, t2, stitch_info = stitch_date(
            client, layer, aoi_bbox,
            polygon=polygon,
            verbose=verbose,
            tile_cache_dir=tile_cache_dir,
            return_info=True,
        )
        if t2 != transform or mask.shape != (height, width):
            raise RuntimeError(
                f'Tile-grid mismatch on {iso}: '
                f'transform {t2} vs {transform}, '
                f'shape {mask.shape} vs {(height, width)}')
        if stitch_info['aborted_early']:
            if log:
                fails = stitch_info['tiles_failed']
                total = stitch_info['tiles_total']
                print(f'(circuit-breaker abort: {fails}/{total} '
                      f'tiles failed — treating as no-data)')
            continue

        # Apply outside-polygon nodata so combiners see consistent data.
        if polygon is not None:
            mask = mask.copy()
            mask[inside_mask == 0] = 255

        bw_data_days[bw_idx].append(iso)
        bw_layers_used[bw_idx].append(layer)

        if method == 'union':
            _update_union(bw_idx, mask)
        elif method == 'mid_snapshot':
            _update_snapshot(bw_idx, d, mask)

        if log:
            inside_flood = int(((mask != 255) & (mask == 1)).sum())
            print(f'flood-pixels={inside_flood}')

    # ── Finalise each bi-week band ─────────────────────────────────
    out_bands: List[_np.ndarray] = []
    for bw_idx in range(len(KHARIF_BW_NUMBERS)):
        if method == 'union':
            band = union_running[bw_idx]
            if band is None:
                band = empty
        else:   # mid_snapshot
            cur = snap_candidate[bw_idx]
            if cur is None:
                band = empty
            else:
                bw_chosen_date[bw_idx] = cur[0].isoformat()
                band = cur[1]
        out_bands.append(band)

    # ── Write the multi-band GeoTIFF ───────────────────────────────
    out = Path(output_path)
    dst = _open_stack_writer(out, (height, width), transform,
                             len(KHARIF_BW_NUMBERS),
                             nodata=255 if polygon is not None else None)
    try:
        for bw_idx in range(len(KHARIF_BW_NUMBERS)):
            bw_num = KHARIF_BW_NUMBERS[bw_idx]
            band_no = bw_idx + 1
            dst.write(out_bands[bw_idx], band_no)
            dst.set_band_description(band_no, biweek_label(year, bw_idx))
            tags = {
                'biweek_number': str(bw_num),
                'biweek_start':  biweek_starts[bw_idx].isoformat(),
                'biweek_end':    (biweek_starts[bw_idx]
                                  + _dt.timedelta(days=13)).isoformat(),
                'data_days':     ','.join(bw_data_days[bw_idx]),
                'n_data_days':   str(len(bw_data_days[bw_idx])),
                'layers_used':   ','.join(bw_layers_used[bw_idx]) or 'NONE',
            }
            if method == 'mid_snapshot' and bw_chosen_date[bw_idx]:
                tags['snapshot_date'] = bw_chosen_date[bw_idx]
            dst.update_tags(band_no, **tags)

        # File-level tags.
        n_with = sum(1 for days in bw_data_days if days)
        n_without = len(KHARIF_BW_NUMBERS) - n_with
        file_tags = {
            'state':            state,
            'year':             str(year),
            'method':           method,
            'n_bands':          str(len(KHARIF_BW_NUMBERS)),
            'biweek_grid':      'BW_12..BW_21 (Jun 4 → Oct 7)',
            'source':           'Bhuvan WMS (NRSC), bi-weekly aggregate',
            'n_biweeks_with_data':  str(n_with),
            'n_biweeks_no_data':    str(n_without),
            'biweeks_with_data':    ','.join(
                str(KHARIF_BW_NUMBERS[i])
                for i, days in enumerate(bw_data_days) if days),
            'biweeks_no_data':      ','.join(
                str(KHARIF_BW_NUMBERS[i])
                for i, days in enumerate(bw_data_days) if not days),
        }
        if district:
            file_tags['district'] = district
            file_tags['aoi_mode'] = 'district'
        elif district_geometry is not None:
            file_tags['aoi_mode'] = 'custom_geometry'
        else:
            file_tags['aoi_mode'] = 'state_bbox'
        dst.update_tags(**file_tags)
    finally:
        dst.close()

    if log:
        print(f'\n✓ Wrote {out}  '
              f'({sum(1 for d in bw_data_days if d)}/{len(KHARIF_BW_NUMBERS)} '
              f'bi-weeks with data)')

    return {
        'state':                state,
        'district':             district,
        'year':                 year,
        'method':               method,
        'output_path':          str(out),
        'n_bands':              len(KHARIF_BW_NUMBERS),
        'biweek_numbers':       list(KHARIF_BW_NUMBERS),
        'biweek_starts':        [d.isoformat() for d in biweek_starts],
        'biweek_data_days':     {KHARIF_BW_NUMBERS[i]: bw_data_days[i]
                                 for i in range(len(KHARIF_BW_NUMBERS))},
        'biweek_layers_used':   {KHARIF_BW_NUMBERS[i]: bw_layers_used[i]
                                 for i in range(len(KHARIF_BW_NUMBERS))},
        'biweek_snapshot_date': {KHARIF_BW_NUMBERS[i]: bw_chosen_date[i]
                                 for i in range(len(KHARIF_BW_NUMBERS))},
        'bbox':                 aoi_bbox,
    }
