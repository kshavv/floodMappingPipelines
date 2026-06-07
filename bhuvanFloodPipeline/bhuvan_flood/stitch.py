"""Stitch downloaded tiles and apply the flood-pixel colour test.

For a given date and state, we fetch every covering tile, stitch them
into one big RGBA mosaic on the EPSG:4326 quadtree, threshold to a
single-band 0/1 flood mask (cyan pixels = 1, everything else = 0),
and return a georeferenced numpy array. Per-day GeoTIFFs are written
optionally; the multi-date stack is built by `stack.py`.
"""
from __future__ import annotations

from typing import Optional, Tuple

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


def stitch_date(client: BhuvanClient,
                layer: str,
                bbox: Tuple[float, float, float, float],
                *,
                progress: Optional[callable] = None
                ) -> Tuple[np.ndarray, Tuple[float, ...]]:
    """Download + stitch every tile covering ``bbox`` for ``layer``.

    Returns ``(mask, transform)`` where mask is uint8 (0 = land/empty,
    1 = flood) and transform is the affine for the stitched extent.
    """
    tx_min, ty_min, tx_max, ty_max = covering_tiles(bbox)
    n_tx = tx_max - tx_min + 1
    n_ty = ty_max - ty_min + 1
    width  = n_tx * TILE_PX
    height = n_ty * TILE_PX

    # Accumulate into one big RGBA canvas, then threshold once at the end.
    # Stitching in RGBA space (rather than per-tile thresholding) keeps the
    # behaviour identical to the QGIS gdal:merge + raster-calculator flow.
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))

    tiles = tiles_for_bbox(bbox)
    for i, (tx, ty) in enumerate(tiles):
        im = client.fetch_tile(layer, tx, ty)
        px = (tx - tx_min) * TILE_PX
        py = (ty - ty_min) * TILE_PX
        canvas.paste(im, (px, py))
        if progress:
            progress(i + 1, len(tiles))

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
    return flood, transform
