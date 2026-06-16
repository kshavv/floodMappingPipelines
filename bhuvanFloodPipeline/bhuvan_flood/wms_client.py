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
                 probe_timeout: float = 20.0,
                 user_agent: str = 'bhuvan-flood-pipeline/1.0'):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.probe_timeout = probe_timeout
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})

    # ── Raw GET with retries ──
    def _get(self, url: str, *, fast_fail: bool = False) -> requests.Response:
        """Fetch ``url`` and return the response.

        ``fast_fail=True`` is used by the layer-existence probe: short
        timeout, no retries, any error → raise immediately. This stops
        no-data days from spending minutes on exponential-backoff retries
        for requests Bhuvan was always going to refuse.

        ``fast_fail=False`` (the default, used by tile fetches) keeps
        the old retry behaviour for genuine transient network errors.
        """
        if fast_fail:
            r = self.session.get(url, timeout=self.probe_timeout)
            # No retries; just hand the response back. Caller decides
            # what to do with non-200 codes.
            return r

        last: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                r = self.session.get(url, timeout=self.timeout)
                # 200/404 are conclusive — return immediately.
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
                               suffixes: Iterable[str] = LAYER_SUFFIX_PROBE,
                               *, verbose: bool = False
                               ) -> Optional[str]:
        """Return the first layer-name variant that has data, else None.
        """
        if probe_bbox is None:
            west, south = WORLD_WEST, WORLD_NORTH - TILE_SIZE_DEG
            east, north = west + TILE_SIZE_DEG, WORLD_NORTH
        else:
            west, south, east, north = probe_bbox

        for suf in suffixes:
            layer = layer_name(code, date_iso, suf)
            url = tile_url(layer, west, south, east, north)

            # Try once with fast-fail. If we hit a ReadTimeout, give
            # Bhuvan one more chance — the first uncached request can
            # be slow, but the second usually hits a warm cache. Other
            # network errors and HTTP failures are treated as
            # "this suffix isn't available" and we move on.
            r = None
            try:
                r = self._get(url, fast_fail=True)
            except requests.exceptions.ReadTimeout:
                if verbose:
                    print(f'      probe suffix {suf!r:>5}: ReadTimeout '
                          f'on first try, retrying once …')
                try:
                    r = self._get(url, fast_fail=True)
                except requests.RequestException as exc:
                    if verbose:
                        print(f'      probe suffix {suf!r:>5}: retry also '
                              f'failed ({exc.__class__.__name__}) — skipping')
                    continue
                except RuntimeError as exc:
                    if verbose:
                        print(f'      probe suffix {suf!r:>5}: retry: {exc}')
                    continue
            except requests.RequestException as exc:
                if verbose:
                    print(f'      probe suffix {suf!r:>5}: network error '
                          f'({exc.__class__.__name__}) — skipping')
                continue
            except RuntimeError as exc:
                if verbose:
                    print(f'      probe suffix {suf!r:>5}: {exc}')
                continue

            if r.status_code != 200 or not r.content:
                if verbose:
                    print(f'      probe suffix {suf!r:>5}: HTTP '
                          f'{r.status_code} ({len(r.content) if r.content else 0} B) — no layer')
                continue
            try:
                with Image.open(io.BytesIO(r.content)) as im:
                    if im.size != (TILE_PX, TILE_PX):
                        if verbose:
                            print(f'      probe suffix {suf!r:>5}: PNG size '
                                  f'{im.size} != expected — no layer')
                        continue
                    # Any valid 256x256 PNG response means Bhuvan
                    # successfully RENDERED this layer at this location.
                    # Whether the probe tile happens to contain flood
                    # cyan or is fully transparent doesn't matter — the
                    # layer exists, and the real flood may be in tiles
                    # we haven't sampled. Commit to this suffix and
                    # let the stitcher fetch the full AOI.
                    if verbose:
                        rgba = im.convert('RGBA')
                        alpha_max = max(rgba.split()[3].getextrema())
                        note = (f'flood pixels at probe (alpha_max={alpha_max})'
                                if alpha_max > 0
                                else 'no flood at probe tile (all transparent), '
                                     'but layer rendered — accepting')
                        print(f'      probe suffix {suf!r:>5}: '
                              f'HIT ({len(r.content)} B) — {note}')
                    return layer
            except Exception as exc:
                if verbose:
                    print(f'      probe suffix {suf!r:>5}: PNG decode '
                          f'failed ({exc}) — skipping')
                continue
        return None

    # ── Fetch one tile ──
    def fetch_tile(self, layer: str, tx: int, ty: int,
                   *, return_info: bool = False,
                   save_dir: Optional[str] = None,
                   fast_fail: bool = False):
        """Return the 256x256 RGBA PNG for tile ``(tx, ty)`` of ``layer``.

        Falls back to a fully-transparent tile on HTTP errors so a single
        flaky tile doesn't kill a whole stitch.

        Parameters
        ----------
        return_info
            If True, return ``(image, info_dict)`` instead of just the
            image. ``info_dict`` contains the URL, HTTP status, response
            bytes, tile bbox, and elapsed seconds — useful for verbose
            logging and debugging.
        save_dir
            If given, also write the raw PNG response to
            ``<save_dir>/<layer-slug>_<tx>_<ty>.png``. The directory is
            created if missing. Useful to inspect individual tiles in
            QGIS without re-running the pipeline.
        fast_fail
            If True, use the short-timeout, no-retry path. Useful when
            we already suspect Bhuvan can't serve this layer at the
            full extent (e.g. probe passed locally but the layer is
            unrenderable at the state level) — saves ~30s of retries
            per failing tile. Default False keeps the old retry
            behaviour for genuine transient errors.
        """
        import time as _time
        west, south, east, north = tile_bbox(tx, ty)
        url = tile_url(layer, west, south, east, north)
        info = {
            'tx': tx, 'ty': ty,
            'bbox': (west, south, east, north),
            'url': url,
            'layer': layer,
            'status': None,
            'bytes': 0,
            'elapsed_s': 0.0,
            'cached_path': None,
            'fallback_empty': False,
        }
        t0 = _time.time()
        try:
            r = self._get(url, fast_fail=fast_fail)
            info['status'] = r.status_code
            info['bytes'] = len(r.content) if r.content else 0
            if r.status_code == 200 and r.content:
                if save_dir is not None:
                    import os as _os
                    _os.makedirs(save_dir, exist_ok=True)
                    layer_slug = layer.replace(':', '_').replace('/', '_')
                    out = _os.path.join(save_dir,
                                        f'{layer_slug}_{tx}_{ty}.png')
                    with open(out, 'wb') as fh:
                        fh.write(r.content)
                    info['cached_path'] = out
                im = Image.open(io.BytesIO(r.content)).convert('RGBA')
                if im.size == (TILE_PX, TILE_PX):
                    info['elapsed_s'] = _time.time() - t0
                    return (im, info) if return_info else im
        except Exception as exc:
            info['status'] = f'error: {exc}'
        info['elapsed_s'] = _time.time() - t0
        info['fallback_empty'] = True
        # Empty tile: transparent.
        empty = Image.new('RGBA', (TILE_PX, TILE_PX), (0, 0, 0, 0))
        return (empty, info) if return_info else empty


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
