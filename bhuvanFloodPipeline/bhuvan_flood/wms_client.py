"""Talk to Bhuvan's WMS GeoWebCache.

Builds tile URLs, probes which layer-suffix variant exists for a given
date, and downloads PNG tile bytes. Keep network knowledge confined to
this module so the stitching/processing layers stay pure.
"""
from __future__ import annotations

import io
import time
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from PIL import Image

from .config import (
    BHUVAN_WMS_URL, TILE_PX, TILE_SIZE_DEG, WORLD_WEST, WORLD_NORTH,
    LAYER_SUFFIX_PROBE,
)


# ----------------------------------------------------------------------------
# URL + layer-name helpers
# ----------------------------------------------------------------------------

def layer_name(code: str, date_iso: str, suffix: str = '') -> str:
    """Build a Bhuvan flood layer name for a calendar date.

    ``code`` is the full state code Bhuvan uses in its layer names
    (e.g. ``'Akl'`` for Kerala, ``'Aas'`` for Assam) — pass the exact
    string from ``config.STATES[<state>]['code']``.

    Bhuvan's naming swaps day/month relative to ISO: the URL uses
    ``YYYY_DD_MM`` (and an optional ``_HH`` suffix), so we mirror that.
    """
    y, m, d = date_iso.split('-')
    return f'flood:{code}_{y}_{int(d):02d}_{int(m):02d}{suffix}'


def tile_url(layer: str, west: float, south: float, east: float, north: float,
             width: int = TILE_PX, height: int = TILE_PX) -> str:
    """Construct a WMS GetMap URL for one tile."""
    params = {
        'LAYERS':      layer,
        'TRANSPARENT': 'TRUE',
        'SERVICE':     'WMS',
        'VERSION':     '1.1.1',
        'REQUEST':     'GetMap',
        'STYLES':      '',
        'FORMAT':      'image/png',
        'SRS':         'EPSG:4326',
        'BBOX':        f'{west},{south},{east},{north}',
        'WIDTH':       str(width),
        'HEIGHT':      str(height),
    }
    return f'{BHUVAN_WMS_URL}?{urlencode(params)}'


# ----------------------------------------------------------------------------
# Tile-grid math (standard WMS-C EPSG:4326 quadtree)
# ----------------------------------------------------------------------------

def covering_tiles(bbox: Tuple[float, float, float, float]
                   ) -> Tuple[int, int, int, int]:
    """Tile-grid indices that fully cover ``bbox`` at the configured zoom.

    Returns ``(tx_min, ty_min, tx_max, ty_max)`` with ``ty`` measured from
    the top (north) so it grows southward — matches how every WMS-C tile
    server numbers tiles. The returned range is inclusive on both ends.
    """
    west, south, east, north = bbox
    tx_min = int((west  - WORLD_WEST)  // TILE_SIZE_DEG)
    tx_max = int((east  - WORLD_WEST)  // TILE_SIZE_DEG)
    ty_min = int((WORLD_NORTH - north) // TILE_SIZE_DEG)
    ty_max = int((WORLD_NORTH - south) // TILE_SIZE_DEG)
    # If east lands exactly on a tile boundary, // includes the next tile;
    # back off when that happens (and symmetrically for south).
    if (east - WORLD_WEST) % TILE_SIZE_DEG == 0 and tx_max > tx_min:
        tx_max -= 1
    if (WORLD_NORTH - south) % TILE_SIZE_DEG == 0 and ty_max > ty_min:
        ty_max -= 1
    return tx_min, ty_min, tx_max, ty_max


def tile_bbox(tx: int, ty: int) -> Tuple[float, float, float, float]:
    """Geographic bbox (west, south, east, north) of tile ``(tx, ty)``."""
    west  = WORLD_WEST  + tx * TILE_SIZE_DEG
    north = WORLD_NORTH - ty * TILE_SIZE_DEG
    east  = west  + TILE_SIZE_DEG
    south = north - TILE_SIZE_DEG
    return (west, south, east, north)


# ----------------------------------------------------------------------------
# HTTP layer
# ----------------------------------------------------------------------------

class BhuvanClient:
    """Small HTTP wrapper with retries and a shared connection pool."""

    def __init__(self, *, timeout: float = 30.0, max_retries: int = 3,
                 backoff: float = 1.5,
                 user_agent: str = 'bhuvan-flood-pipeline/1.0'):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})

    # ── Raw GET with retries ──
    def _get(self, url: str) -> requests.Response:
        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                r = self.session.get(url, timeout=self.timeout)
                # Anything other than 200/404 is worth retrying.
                if r.status_code in (200, 404):
                    return r
                last = RuntimeError(f'HTTP {r.status_code} for {url}')
            except requests.RequestException as e:
                last = e
            time.sleep(self.backoff * (2 ** attempt))
        raise RuntimeError(f'Failed after {self.max_retries} retries: {last}')

    # ── Layer existence probe ──
    def resolve_layer_for_date(self, code: str, date_iso: str,
                               probe_bbox: Optional[
                                   Tuple[float, float, float, float]] = None,
                               suffixes: Iterable[str] = LAYER_SUFFIX_PROBE
                               ) -> Optional[str]:
        """Return the first layer-name variant that has data, else None.

        Probes Bhuvan by fetching one 256x256 tile inside ``probe_bbox``
        (which should be a small bbox inside the AOI — e.g. one tile of
        the state's covering set). A layer is considered to "exist" if
        the response is a real 256x256 PNG and at least one pixel is
        non-transparent (i.e. Bhuvan actually rendered something for
        this layer/region, not just sent back an empty canvas).
        """
        if probe_bbox is None:
            # Caller didn't supply a probe location; we fall back to the
            # world-origin tile, which is fine for detecting whether the
            # layer NAME exists but won't distinguish "exists but empty
            # in this AOI" from "doesn't exist". For accurate probing,
            # always pass probe_bbox.
            west, south = WORLD_WEST, WORLD_NORTH - TILE_SIZE_DEG
            east, north = west + TILE_SIZE_DEG, WORLD_NORTH
        else:
            west, south, east, north = probe_bbox

        for suf in suffixes:
            layer = layer_name(code, date_iso, suf)
            url = tile_url(layer, west, south, east, north)
            try:
                r = self._get(url)
            except RuntimeError:
                continue
            if r.status_code != 200 or not r.content:
                continue
            try:
                with Image.open(io.BytesIO(r.content)) as im:
                    if im.size != (TILE_PX, TILE_PX):
                        continue
                    rgba = im.convert('RGBA')
                    # Any non-transparent pixel means Bhuvan rendered
                    # SOMETHING for this layer in our probe area. That's
                    # enough to commit to this suffix; the full stitch
                    # may still be all-transparent if the actual flood
                    # extent is outside the probe tile, but at least the
                    # named layer exists.
                    alpha_max = max(rgba.split()[3].getextrema())
                    if alpha_max > 0:
                        return layer
            except Exception:
                continue
        return None

    # ── Fetch one tile ──
    def fetch_tile(self, layer: str, tx: int, ty: int) -> Image.Image:
        """Return the 256x256 RGBA PNG for tile ``(tx, ty)`` of ``layer``.

        Falls back to a fully-transparent tile on HTTP errors so a single
        flaky tile doesn't kill a whole stitch.
        """
        west, south, east, north = tile_bbox(tx, ty)
        url = tile_url(layer, west, south, east, north)
        try:
            r = self._get(url)
            if r.status_code == 200 and r.content:
                im = Image.open(io.BytesIO(r.content)).convert('RGBA')
                if im.size == (TILE_PX, TILE_PX):
                    return im
        except Exception:
            pass
        # Empty tile: transparent.
        return Image.new('RGBA', (TILE_PX, TILE_PX), (0, 0, 0, 0))


# ----------------------------------------------------------------------------
# Convenience: list all (tx, ty) covering a bbox
# ----------------------------------------------------------------------------

def tiles_for_bbox(bbox: Tuple[float, float, float, float]
                   ) -> List[Tuple[int, int]]:
    """Enumerate every tile index ``(tx, ty)`` covering ``bbox``."""
    tx_min, ty_min, tx_max, ty_max = covering_tiles(bbox)
    return [(tx, ty)
            for ty in range(ty_min, ty_max + 1)
            for tx in range(tx_min, tx_max + 1)]
