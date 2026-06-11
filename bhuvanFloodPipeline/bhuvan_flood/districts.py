"""Resolve district polygons.

The pipeline supports per-district downloads, where you give the state
and a single district name and the tile-fetch is constrained to the
district's polygon (with a small buffer).

"""
from __future__ import annotations

from typing import Tuple
import re


def slugify(name: str) -> str:
    """Lower-case + non-alphanumeric → underscore, for filenames."""
    s = (name or '').lower()
    s = re.sub(r'&', ' and ', s)
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def resolve_district(state: str, district: str):
    """Return ``(polygon_geojson_dict, bbox_tuple)`` for one district.

    Uses Earth Engine's ``FAO/GAUL/2015/level2`` collection. The result
    is the polygon as a plain GeoJSON-like dict and its (west, south,
    east, north) bbox in EPSG:4326.

    Raises ``ImportError`` if ``earthengine-api`` is not installed and
    ``RuntimeError`` if no matching district is found.
    """
    try:
        import ee
    except ImportError as exc:
        raise ImportError(
            'Resolving a district by name requires earthengine-api.\n'
            '  pip install earthengine-api\n'
            '  earthengine authenticate\n'
            'Or pass `district_geometry=<shapely geometry>` to skip EE.'
        ) from exc

    # The caller is expected to have already called ee.Initialize().
    # We don't call it here because the project id is user-specific.
    fc = (ee.FeatureCollection('FAO/GAUL/2015/level2')
          .filter(ee.Filter.And(
              ee.Filter.eq('ADM0_NAME', 'India'),
              ee.Filter.eq('ADM1_NAME', state),
              ee.Filter.eq('ADM2_NAME', district))))

    size = fc.size().getInfo()
    if size == 0:
        # Try a case-insensitive match — GAUL names sometimes vary
        # ("Ernakulam" vs "Ernakulum").
        all_in_state = (ee.FeatureCollection('FAO/GAUL/2015/level2')
                        .filter(ee.Filter.And(
                            ee.Filter.eq('ADM0_NAME', 'India'),
                            ee.Filter.eq('ADM1_NAME', state))))
        names = all_in_state.aggregate_array('ADM2_NAME').getInfo()
        target = district.lower().strip()
        match = next((n for n in names if n.lower().strip() == target), None)
        if not match:
            raise RuntimeError(
                f'No GAUL district named {district!r} in {state!r}. '
                f'Districts available in {state}: {sorted(names)}')
        fc = (ee.FeatureCollection('FAO/GAUL/2015/level2')
              .filter(ee.Filter.And(
                  ee.Filter.eq('ADM0_NAME', 'India'),
                  ee.Filter.eq('ADM1_NAME', state),
                  ee.Filter.eq('ADM2_NAME', match))))

    geom = fc.geometry().simplify(100)
    geojson = geom.getInfo()             # plain dict
    bbox = geom.bounds().coordinates().getInfo()[0]
    xs = [c[0] for c in bbox]
    ys = [c[1] for c in bbox]
    bbox_tuple = (min(xs), min(ys), max(xs), max(ys))
    return geojson, bbox_tuple


def buffer_bbox(bbox: Tuple[float, float, float, float],
                buffer_deg: float = 0.05
                ) -> Tuple[float, float, float, float]:
    """Expand a bbox by ``buffer_deg`` on every side.

    Districts are small, so the default buffer is tighter (0.05° ≈ 5.5 km)
    than the state-level 0.2°. The buffer absorbs GAUL polygon noise at
    the border and ensures the tile-grid covering captures every tile
    that touches the district.
    """
    w, s, e, n = bbox
    return (w - buffer_deg, s - buffer_deg,
            e + buffer_deg, n + buffer_deg)
