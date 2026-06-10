"""Stitch downloaded tiles and apply the flood-pixel colour test.

For a given date and state (or district), we fetch every covering tile,
stitch them into one big RGBA mosaic on the EPSG:4326 quadtree, threshold
to a single-band 0/1 flood mask (cyan pixels = 1, everything else = 0),
and return a georeferenced numpy array.

Optional polygon filter
-----------------------
``stitch_date`` accepts an optional shapely polygon (the district
boundary, typically). When supplied:
  * Tile fetches are restricted to tiles whose bbox INTERSECTS the
    polygon — corner tiles inside the bbox but outside the polygon are
    skipped entirely (no HTTP request).
  * After thresholding, pixels outside the polygon are zeroed, so the
    output mask is district-shaped, not bbox-shaped.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

import numpy as np
from PIL import Image

from .config import (
    DEG_PER_PIXEL, FLOOD_RGBA, TILE_PX, TILE_SIZE_DEG, WORLD_NORTH, WORLD_WEST,
)
from .wms_client import (
    BhuvanClient, covering_tiles, tile_bbox, tiles_for_bbox,
)


def empty_mask_for_bbox(bbox: Tuple[float, float, float, float]
                        ) -> Tuple[np.ndarray, Tuple[float, ...]]:
    """All-zero ``uint8`` mask aligned to the tile grid covering ``bbox``.

    Returns ``(mask, transform)`` where transform is the 6-tuple GDAL
    affine ``(a, b, c, d, e, f)`` for north-up rasters at the configured
    zoom: ``(deg_per_pixel, 0, west, 0, -deg_per_pixel, north)``.
    """
    tx_min, ty_min, tx_max, ty_max = covering_tiles(bbox)
    n_tx = tx_max - tx_min + 1
    n_ty = ty_max - ty_min + 1
    width  = n_tx * TILE_PX
    height = n_ty * TILE_PX
    mask = np.zeros((height, width), dtype=np.uint8)
    west  = WORLD_WEST  + tx_min * TILE_SIZE_DEG
    north = WORLD_NORTH - ty_min * TILE_SIZE_DEG
    transform = (DEG_PER_PIXEL, 0.0, west, 0.0, -DEG_PER_PIXEL, north)
    return mask, transform


def _polygon_pixel_mask(polygon, transform, height, width) -> np.ndarray:
    """Rasterise ``polygon`` into a uint8 (H, W) mask: 1 inside, 0 outside.

    Used to zero out pixels outside the polygon after stitching, so the
    output is polygon-shaped rather than bbox-shaped.
    """
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    a, b, c, d, e, f = transform
    aff = Affine(a, b, c, d, e, f)
    return rasterize(
        [(polygon, 1)],
        out_shape=(height, width),
        transform=aff,
        fill=0,
        dtype='uint8',
    )


def filter_tiles_by_polygon(tiles, polygon):
    """Keep only tiles whose bbox intersects the polygon.

    ``tiles`` is a list of ``(tx, ty)``; ``polygon`` is a shapely
    geometry. Each tile's geographic bbox is converted to a shapely
    box and intersected; corner tiles outside the polygon are dropped.
    """
    from shapely.geometry import box
    kept = []
    for tx, ty in tiles:
        w, s, e, n = tile_bbox(tx, ty)
        if polygon.intersects(box(w, s, e, n)):
            kept.append((tx, ty))
    return kept


def stitch_date(client: BhuvanClient,
                layer: str,
                bbox: Tuple[float, float, float, float],
                *,
                polygon=None,
                progress: Optional[Callable[[int, int], None]] = None,
                verbose: bool = False,
                tile_cache_dir: Optional[str] = None,
                tile_log: Optional[list] = None,
                failure_cutoff: int = 5,
                fast_fail_tiles: bool = True,
                return_info: bool = False,
                ):
    """Download + stitch every tile covering ``bbox`` for ``layer``.

    Parameters
    ----------
    polygon
        Optional shapely polygon. When given, only tiles that intersect
        it are fetched, and pixels outside it are zeroed in the result.
    progress
        Optional callback ``f(i, total)`` invoked after each tile.
    verbose
        If True, print one line per tile with URL, status, response
        size, elapsed time, and (if applicable) where the PNG was
        cached.
    tile_cache_dir
        If given, every fetched tile's raw PNG is saved here as
        ``<layer-slug>_<tx>_<ty>.png``. Useful to drop into QGIS to
        inspect individual tiles. The directory is created if missing.
    tile_log
        If given (a list), every tile's info dict is appended here.
        Useful when ``verbose`` is False but you still want the audit
        trail programmatically.
    failure_cutoff
        Circuit breaker — if the first ``failure_cutoff`` tiles ALL
        fail (i.e. Bhuvan returned an error / non-200 / unparseable
        PNG, and we fell back to an empty tile for each), abort the
        stitch early and return an all-zeros mask. This is the cure
        for the "probe passed but every actual tile is HTTP 400" case
        where Bhuvan can't serve the layer at the full extent: instead
        of grinding through all 500 tiles, we bail after 5 and let the
        orchestrator mark the date as no-data. Set to ``0`` to
        disable. Default 5.
    fast_fail_tiles
        If True, every tile fetch uses ``fast_fail=True`` (5s timeout,
        no retries). Strongly recommended; cuts per-tile failure cost
        from ~30s of retries to ~5s of one timeout. Default True.
    return_info
        If True, return ``(mask, transform, info)`` where ``info`` is
        a dict with ``aborted_early``, ``tiles_attempted``,
        ``tiles_succeeded``, ``tiles_failed``. The orchestrator uses
        this to distinguish "real flood map with zero floods today"
        from "circuit-breaker abort because the layer can't be
        served". Default False keeps the original two-tuple shape.

    Returns ``(mask, transform)`` — or ``(mask, transform, info)`` if
    ``return_info=True``. ``mask`` is uint8 (0 = land/empty, 1 = flood)
    and ``transform`` is the affine for the stitched extent.
    """
    tx_min, ty_min, tx_max, ty_max = covering_tiles(bbox)
    n_tx = tx_max - tx_min + 1
    n_ty = ty_max - ty_min + 1
    width  = n_tx * TILE_PX
    height = n_ty * TILE_PX

    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))

    tiles = tiles_for_bbox(bbox)
    if polygon is not None:
        tiles = filter_tiles_by_polygon(tiles, polygon)

    if verbose:
        print(f'  [{layer}] {len(tiles)} tile(s) to fetch'
              + (f'  (circuit breaker: bail if first {failure_cutoff} fail)'
                 if failure_cutoff > 0 else ''))

    info_collect = (verbose or tile_cache_dir is not None
                    or tile_log is not None
                    or failure_cutoff > 0)

    # Circuit-breaker state.
    consecutive_fails = 0
    aborted_early = False
    tiles_succeeded = 0
    tiles_failed = 0
    tiles_attempted = 0

    for i, (tx, ty) in enumerate(tiles):
        tiles_attempted += 1
        if info_collect:
            im, info = client.fetch_tile(
                layer, tx, ty,
                return_info=True,
                save_dir=tile_cache_dir,
                fast_fail=fast_fail_tiles,
            )
            if verbose:
                bbox_str = (f'({info["bbox"][0]:.4f},{info["bbox"][1]:.4f},'
                            f'{info["bbox"][2]:.4f},{info["bbox"][3]:.4f})')
                cached = f' → {info["cached_path"]}' if info['cached_path'] else ''
                print(f'    [{i+1:>3}/{len(tiles)}] tx={tx} ty={ty} '
                      f'bbox={bbox_str} '
                      f'status={info["status"]} '
                      f'{info["bytes"]:>6} B '
                      f'{info["elapsed_s"]*1000:>4.0f} ms'
                      f'{cached}')
                print(f'              URL: {info["url"]}')
            if tile_log is not None:
                tile_log.append(info)
            # Circuit-breaker bookkeeping: count consecutive empty/error
            # fallbacks. Reset to 0 on any genuine success.
            if info['fallback_empty']:
                consecutive_fails += 1
                tiles_failed += 1
            else:
                consecutive_fails = 0
                tiles_succeeded += 1
        else:
            im = client.fetch_tile(layer, tx, ty,
                                   fast_fail=fast_fail_tiles)
            # No info available without return_info=True; we can't track
            # success/failure in this branch, but failure_cutoff=0 was
            # required to take this branch (info_collect would have been
            # True otherwise), so no circuit breaker is active here.
            tiles_succeeded += 1

        px = (tx - tx_min) * TILE_PX
        py = (ty - ty_min) * TILE_PX
        canvas.paste(im, (px, py))
        if progress:
            progress(i + 1, len(tiles))

        if (failure_cutoff > 0
                and consecutive_fails >= failure_cutoff
                and i + 1 == consecutive_fails):
            # ALL of the first N tiles failed, with nothing in between
            # succeeding. Bhuvan can't serve this layer at this extent.
            aborted_early = True
            if verbose:
                print(f'  ✗ Circuit breaker tripped: first {failure_cutoff} '
                      f'tiles all failed. Aborting stitch for {layer!r} and '
                      f'treating as no-data.')
            break

    arr = np.array(canvas)             # shape (H, W, 4), uint8
    flood = (
        (arr[..., 0] == FLOOD_RGBA[0]) &
        (arr[..., 1] == FLOOD_RGBA[1]) &
        (arr[..., 2] == FLOOD_RGBA[2]) &
        (arr[..., 3] == FLOOD_RGBA[3])
    ).astype(np.uint8)

    west  = WORLD_WEST  + tx_min * TILE_SIZE_DEG
    north = WORLD_NORTH - ty_min * TILE_SIZE_DEG
    transform = (DEG_PER_PIXEL, 0.0, west, 0.0, -DEG_PER_PIXEL, north)

    if polygon is not None:
        poly_mask = _polygon_pixel_mask(polygon, transform, height, width)
        flood = flood * poly_mask

    if return_info:
        info = {
            'aborted_early':    aborted_early,
            'tiles_total':      len(tiles),
            'tiles_attempted':  tiles_attempted,
            'tiles_succeeded':  tiles_succeeded,
            'tiles_failed':     tiles_failed,
            'layer':            layer,
        }
        return flood, transform, info
    return flood, transform
