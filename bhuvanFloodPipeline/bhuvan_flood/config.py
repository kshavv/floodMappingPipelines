"""Configuration for the Bhuvan flood-tile download pipeline.

State mapping
-------------
Each state maps to (1) the state code Bhuvan embeds in its WMS layer
names (e.g. ``flood:Akl_2021_19_10_06`` for Kerala — the ``Akl`` is
the full code, prefix included) and (2) a generous geographic bounding
box used to enumerate the WMS tile grid.

The bbox is derived from FAO GAUL level-1 polygons + a 0.2° buffer on
all sides so the covering tile set captures every tile that overlaps
the state.

Tile grid
---------
The Bhuvan flood layers are published on the standard WMS-C quadtree
in EPSG:4326 with the world 2 tiles wide at z=0, 256-px tiles, origin
(-180, -90). At ZOOM the pixel size in degrees is::

    deg_per_pixel = 180 / (256 * 2**ZOOM)

For these layers ZOOM = 10  (verified against an observed BBOX), so
pixel size ≈ 0.0006866455° (~76 m at the equator).
"""
from __future__ import annotations

# --- Bhuvan tile grid constants -------------------------------------------
BHUVAN_WMS_URL = 'https://bhuvan-gp1.nrsc.gov.in/bhuvan/gwc/service/wms'
ZOOM = 10
TILE_PX = 256
WORLD_WEST = -180.0
WORLD_NORTH = 90.0
TILE_SIZE_DEG = 180.0 / (2 ** ZOOM)          # 0.17578125 at z=10
DEG_PER_PIXEL = TILE_SIZE_DEG / TILE_PX      # 0.0006866455... at z=10

# --- Flood-pixel colour test (port of the QGIS calculator) ----------------
# A pixel is flooded iff (R, G, B, A) == FLOOD_RGBA. Bhuvan uses cyan on a
# transparent background; transparent pixels (A=0) are non-flood.
FLOOD_RGBA = (0, 255, 255, 255)

# --- State mapping --------------------------------------------------------
# code  : full state code as used by Bhuvan in layer names
#         (`flood:<code>_YYYY_DD_MM[_HH]`). Includes any leading prefix
#         (e.g. 'Akl' for Kerala) — passed verbatim into the layer name.
# bbox  : (west, south, east, north) in EPSG:4326. Derived from FAO GAUL
#         level-1 polygons + 0.2° buffer on all sides so the covering
#         tile set captures every tile that overlaps the state.
# gaul  : GAUL level-1 ADM1_NAME used for precise polygon clipping.
#
# Codes marked 'XX' are placeholders — fill them in from Bhuvan's
# GetCapabilities or by inspecting a working layer URL.
STATES = {
    'Andaman and Nicobar':     {'code': 'XX',  'bbox': (92.0042,  6.5560, 94.4776, 13.8754), 'gaul': 'Andaman and Nicobar'},
    'Andhra Pradesh':          {'code': 'XX',  'bbox': (76.5570, 12.4118, 84.9607, 20.1161), 'gaul': 'Andhra Pradesh'},
    'Arunachal Pradesh':       {'code': 'XX',  'bbox': (93.4358, 26.4426, 97.3671, 28.5013), 'gaul': 'Arunachal Pradesh'},
    'Assam':                   {'code': 'as', 'bbox': (89.4948, 23.9348, 96.2209, 28.1774), 'gaul': 'Assam'},
    'Bihar':                   {'code': 'br', 'bbox': (83.1161, 24.0870, 88.4919, 27.7200), 'gaul': 'Bihar'},
    'Chandigarh':              {'code': 'XX',  'bbox': (76.4906, 30.4693, 77.0363, 30.9990), 'gaul': 'Chandigarh'},
    'Chhattisgarh':            {'code': 'XX',  'bbox': (80.0396, 17.5828, 84.5896, 24.3070), 'gaul': 'Chhattisgarh'},
    'Dadra and Nagar Haveli':  {'code': 'XX',  'bbox': (72.7223, 19.8516, 73.4292, 20.5607), 'gaul': 'Dadra and Nagar Haveli'},
    'Daman and Diu':           {'code': 'XX',  'bbox': (70.4712, 20.1687, 73.0755, 21.1901), 'gaul': 'Daman and Diu'},
    'Delhi':                   {'code': 'XX',  'bbox': (76.6329, 28.2085, 77.5377, 29.0845), 'gaul': 'Delhi'},
    'Goa':                     {'code': 'XX',  'bbox': (73.4790, 14.6916, 74.5417, 15.9975), 'gaul': 'Goa'},
    'Gujarat':                 {'code': 'XX',  'bbox': (67.9782, 19.9208, 74.6789, 24.9058), 'gaul': 'Gujarat'},
    'Haryana':                 {'code': 'hr', 'bbox': (74.2653, 27.4560, 77.7920, 31.1304), 'gaul': 'Haryana'},
    'Himachal Pradesh':        {'code': 'XX',  'bbox': (75.3788, 30.1845, 79.1957, 33.3719), 'gaul': 'Himachal Pradesh'},
    'Jharkhand':               {'code': 'XX',  'bbox': (83.1236, 21.7666, 88.1733, 25.5484), 'gaul': 'Jharkhand'},
    'Karnataka':               {'code': 'ka', 'bbox': (73.8547, 11.3745, 78.7775, 18.6551), 'gaul': 'Karnataka'},
    'Kerala':                  {'code': 'kl', 'bbox': (74.6661,  8.0973, 77.5962, 12.9908), 'gaul': 'Kerala'},
    'Lakshadweep':             {'code': 'XX',  'bbox': (71.6395,  7.8892, 73.9030, 12.5981), 'gaul': 'Lakshadweep'},
    'Madhya Pradesh':          {'code': 'XX',  'bbox': (73.8347, 20.8753, 83.0078, 27.0744), 'gaul': 'Madhya Pradesh'},
    'Maharashtra':             {'code': 'XX',  'bbox': (72.4504, 15.4046, 81.0922, 22.2310), 'gaul': 'Maharashtra'},
    'Manipur':                 {'code': 'XX',  'bbox': (92.7736, 23.6360, 94.9432, 25.8977), 'gaul': 'Manipur'},
    'Meghalaya':                {'code': 'XX', 'bbox': (89.6157, 24.8288, 93.0044, 26.3187), 'gaul': 'Meghalaya'},
    # --- Mizoram, Nagaland, Odisha, Puducherry, Punjab, Rajasthan,
    # --- Sikkim, Tamil Nadu, Telangana?, Tripura : add here when you
    # --- re-paste the truncated middle of your GAUL output.
    'Uttar Pradesh':           {'code': 'XX',  'bbox': (76.8849, 23.6728, 84.8306, 30.6125), 'gaul': 'Uttar Pradesh'},
    'Uttarakhand':             {'code': 'XX',  'bbox': (77.3622, 28.5156, 81.2433, 31.4909), 'gaul': 'Uttarakhand'},
    'West Bengal':             {'code': 'XX',  'bbox': (85.6264, 20.6685, 90.0775, 27.4210), 'gaul': 'West Bengal'},
}


def state_config(state: str) -> dict:
    """Resolve a state name to its (code, bbox, gaul) record.

    Lookup is case-insensitive on the state's English name. Raises
    ``KeyError`` with the available list if the state isn't registered.
    """
    key = state.strip()
    for k, v in STATES.items():
        if k.lower() == key.lower():
            return v
    raise KeyError(
        f'State {state!r} not registered. Add it to STATES in '
        f'flood_mapping_bhuvan/config.py. Known: {sorted(STATES.keys())}')


# --- Layer-name suffix probe order ----------------------------------------
# Bhuvan publishes flood layers with optional sub-day suffixes 06 / 12 / 18
# (UTC hours). For a given calendar date we try the bare layer first, then
# each suffix in order; the first one that returns 200 OK wins.
LAYER_SUFFIX_PROBE = ['', '_06', '_12', '_18']


def state_polygon(state: str):
    """Resolve a state's GAUL level-1 polygon via Earth Engine.

    Called when the user picks state-only mode but still wants the
    output masked to the actual state boundary instead of the bbox
    rectangle. Returns ``(polygon_geojson_dict, bbox_tuple)`` — same
    shape as ``districts.resolve_district`` so the orchestrator can
    use it interchangeably.

    Raises ``ImportError`` if earthengine-api isn't installed; raises
    ``RuntimeError`` if no matching GAUL row is found.
    """
    try:
        import ee
    except ImportError as exc:
        raise ImportError(
            'state_polygon needs earthengine-api.\n'
            '  pip install earthengine-api && earthengine authenticate\n'
            'Or pass `clip_to_state=False` to keep the bbox rectangle.'
        ) from exc

    cfg = state_config(state)
    fc = (ee.FeatureCollection('FAO/GAUL/2015/level1')
          .filter(ee.Filter.And(
              ee.Filter.eq('ADM0_NAME', 'India'),
              ee.Filter.eq('ADM1_NAME', cfg['gaul']))))
    if fc.size().getInfo() == 0:
        raise RuntimeError(
            f'No GAUL level-1 row for state {state!r} '
            f'(ADM1_NAME={cfg["gaul"]!r}).')

    geom = fc.geometry().simplify(100)
    geojson = geom.getInfo()
    bbox = geom.bounds().coordinates().getInfo()[0]
    xs = [c[0] for c in bbox]
    ys = [c[1] for c in bbox]
    return geojson, (min(xs), min(ys), max(xs), max(ys))
