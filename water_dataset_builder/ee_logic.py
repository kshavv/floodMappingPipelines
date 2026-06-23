"""
All server-side Earth Engine logic for the water dataset.

Pipeline per category:
  asset -> parse Name -> sample water pixels (+ optional NW ring)
        -> enrich with Sentinel-1/2 -> engineer features (server-side)

Nothing is pulled to local; the orchestrator merges categories and exports
one asset.
"""

import ee
import config


# ----------------------------------------------------------------------
# 1. Parse the `Name` property into id / waterType / day / month / year
#    (server-side port of your df.map regex parsing)
# ----------------------------------------------------------------------
def parse_assets(fc):
    def parse(f):
        name = ee.String(f.get("Name"))
        # id   = leading digits
        idv = ee.String(name.match("^[0-9]+").get(0))
        # type = "NW" if present else "W"  (check NW first!)
        is_nw = name.match("NW").size().gt(0)
        typ = ee.String(ee.Algorithms.If(is_nw, "NW", "W"))
        # remove id + type prefix -> "DDMMYYYY"
        # anchor with ^ so only the leading prefix is stripped, never a
        # coincidental mid-string match.
        rest = name.replace(ee.String("^").cat(idv).cat(typ), "")
        day = ee.String(rest.slice(0, 2))
        month = ee.String(rest.slice(2, 4))
        year = ee.String(rest.slice(4, 8))
        return f.set({
            "id": idv, "waterType": typ,
            "day": day, "month": month, "year": year,
            "poly_area_m2": f.geometry().area(1),
            "poly_id": name,
        })
    return fc.map(parse)


# ----------------------------------------------------------------------
# 2. Sentinel helpers
# ----------------------------------------------------------------------
def get_closest_s1(target_date, geom):
    start = target_date.advance(-config.S1_WINDOW_DAYS, "day")
    end = target_date.advance(config.S1_WINDOW_DAYS, "day")
    col = (ee.ImageCollection("COPERNICUS/S1_GRD")
           .filterBounds(geom).filterDate(start, end)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .map(lambda img: img.select(config.S1_BANDS).set(
               "timeDiff", img.date().difference(target_date, "day").abs()))
           .sort("timeDiff"))
    empty = ee.Image.constant([0, 0]).rename(config.S1_BANDS).selfMask()
    return ee.Image(ee.Algorithms.If(col.size().gt(0), col.first(), empty))


def get_closest_s2(target_date, geom):
    start = target_date.advance(-config.S2_WINDOW_DAYS, "day")
    end = target_date.advance(config.S2_WINDOW_DAYS, "day")
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(geom).filterDate(start, end)
           .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", config.S2_MAX_CLOUD))
           .map(lambda img: img.select(config.S2_BANDS).set(
               "timeDiff", img.date().difference(target_date, "day").abs()))
           .sort("timeDiff"))
    empty = ee.Image.constant([0] * len(config.S2_BANDS)).rename(config.S2_BANDS).selfMask()
    return ee.Image(ee.Algorithms.If(col.size().gt(0), col.first(), empty))


# ----------------------------------------------------------------------
# 3. Pixel sampling
# ----------------------------------------------------------------------
def _base():
    return (ee.Image.pixelLonLat().rename(["longitude", "latitude"])
            .addBands(ee.Image.constant(1).rename("maskBase")))


def sample_water_pixels(parsed_fc):
    base = _base()
    bd = config.WATER_INTERIOR_BUFFER

    def per_poly(f):
        geom = f.geometry()
        buffered = geom.buffer(bd, 1)
        pixels = ee.FeatureCollection(ee.Algorithms.If(
            buffered.area().gt(0),
            base.sample(region=buffered, scale=config.SCALE, geometries=True),
            ee.FeatureCollection([])
        ))
        return (pixels.randomColumn("rand").sort("rand")
                .limit(config.WATER_PTS_PER_POLY)
                .map(lambda p: p.set({
                    "id": f.get("id"), "Name": f.get("Name"),
                    "day": f.get("day"), "month": f.get("month"),
                    "year": f.get("year"), "waterType": f.get("waterType"),
                    "poly_area_m2": f.get("poly_area_m2"),
                })))
    return ee.FeatureCollection(parsed_fc.map(per_poly)).flatten()


def sample_nw_pixels(parsed_fc):
    base_img = ee.Image.pixelLonLat().addBands(ee.Image.constant(1).rename("dummy"))
    ib, rw = config.NW_INNER_BUFFER, config.NW_RING_WIDTH

    def process(feat):
        poly = ee.Feature(feat)
        geom = poly.geometry()
        inner = geom.buffer(ib)
        outer = geom.buffer(ib + rw)
        ring = outer.difference(inner, 1)
        region = ee.Geometry(ee.Algorithms.If(ring.area(1).gt(0), ring, outer))
        cand = base_img.sample(region=region, scale=config.SCALE, geometries=True)
        return (cand.randomColumn("rand").sort("rand")
                .limit(config.NW_PTS_PER_POLY)
                .map(lambda p: p.set({
                    "id": poly.get("id"), "Name": poly.get("Name"),
                    "waterType": "NW",
                    "day": poly.get("day"), "month": poly.get("month"),
                    "year": poly.get("year"),
                    "poly_area_m2": poly.get("poly_area_m2"),
                })))
    water = parsed_fc.filter(ee.Filter.eq("waterType", "W"))
    return ee.FeatureCollection(water.map(process)).flatten()


# ----------------------------------------------------------------------
# 4. Sentinel enrichment
# ----------------------------------------------------------------------
def enrich(combined_fc):
    def do(f):
        year = ee.Number.parse(f.get("year"))
        month = ee.Number.parse(f.get("month"))
        day = ee.Number.parse(f.get("day"))
        target = ee.Date.fromYMD(year, month, day)
        geom = f.geometry()

        s1 = get_closest_s1(target, geom)
        s2 = get_closest_s2(target, geom)
        s1_ok = s1.bandNames().size().gt(0)
        s2_ok = s2.bandNames().size().gt(0)

        def both():
            s1dt = ee.Date(s1.get("system:time_start"))
            s2dt = ee.Date(s2.get("system:time_start"))
            stacked = s1.select(config.S1_BANDS).addBands(s2.select(config.S2_BANDS))
            sampled = stacked.sample(region=geom, scale=config.SCALE,
                                     tileScale=config.SAMPLE_TILE_SCALE).first()
            return ee.Algorithms.If(
                sampled,
                f.copyProperties(sampled, sampled.propertyNames()).set({
                    "s1_datetime_utc": s1dt.format("YYYY-MM-dd HH:mm:ss"),
                    "s2_datetime_utc": s2dt.format("YYYY-MM-dd HH:mm:ss"),
                    "s1_day_diff": s1.get("timeDiff"),
                    "s2_day_diff": s2.get("timeDiff"),
                    "sample_missing": 0,
                }),
                f.set({"sample_missing": 1})
            )

        return ee.Feature(ee.Algorithms.If(
            s1_ok.And(s2_ok), both(),
            f.set({"sample_missing": 1, "s1_missing": s1_ok.Not(), "s2_missing": s2_ok.Not()})
        ))
    return combined_fc.map(do)


# ----------------------------------------------------------------------
# 5. Server-side feature engineering (port of the pandas script)
# ----------------------------------------------------------------------
def engineer(fc):
    # Drop failed samples first (mirrors sample_missing == 0 filter).
    fc = fc.filter(ee.Filter.eq("sample_missing", 0))

    def add_features(f):
        # Cast band props to numbers (sampled props arrive as numbers, but
        # date parts are strings; be explicit where it matters).
        vv = ee.Number(f.get("VV"))
        vh = ee.Number(f.get("VH"))
        b2 = ee.Number(f.get("B2"))
        b3 = ee.Number(f.get("B3"))
        b4 = ee.Number(f.get("B4"))
        b8 = ee.Number(f.get("B8"))
        b11 = ee.Number(f.get("B11"))

        ndwi = b3.subtract(b8).divide(b3.add(b8).add(1e-6))
        mndwi = b3.subtract(b11).divide(b3.add(b11).add(1e-6))
        bgr = b2.subtract(b3).divide(b2.add(b3).add(1e-6))
        soil = b11.divide(b4.add(1e-6))
        area = ee.Number(f.get("poly_area_m2"))

        size_class = ee.Number(ee.Algorithms.If(
            area.lte(config.SIZECLASS_SMALL_MAX), 0,
            ee.Algorithms.If(area.lte(config.SIZECLASS_MEDIUM_MAX), 1, 2)))

        water_bin = ee.Number(ee.Algorithms.If(
            ee.String(f.get("waterType")).equals("W"), 1, 0))

        return f.set({
            "VV_VH_ratio": vv.subtract(vh),
            "NDWI": ndwi,
            "MNDWI": mndwi,
            "BGR": bgr,
            "soilIndex": soil,
            "B2_log": b2.add(1e-6).log(),
            "B3_log": b3.add(1e-6).log(),
            "month": ee.Number.parse(f.get("month")),
            "sizeClass": size_class,
            "waterType": water_bin,
        })

    fc = fc.map(add_features)

    # Day-diff quality filter (server-side equivalent of the pandas mask).
    fc = fc.filter(ee.Filter.And(
        ee.Filter.lte("s1_day_diff", config.S1_DAY_DIFF_MAX),
        ee.Filter.lte("s2_day_diff", config.S2_DAY_DIFF_MAX),
    ))
    return fc


# ----------------------------------------------------------------------
# 6. Per-category orchestration
# ----------------------------------------------------------------------
def build_category(asset_id, do_nw_sampling):
    fc = ee.FeatureCollection(asset_id)
    parsed = parse_assets(fc)
    water_px = sample_water_pixels(parsed)
    combined = water_px.merge(sample_nw_pixels(parsed)) if do_nw_sampling else water_px
    enriched = enrich(combined)
    return engineer(enriched)
