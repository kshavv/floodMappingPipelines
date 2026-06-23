"""Train the two Random-Forest classifiers and produce per-bi-week
binary water masks.
"""
from __future__ import annotations
import ee

from .config import (
    FEATURES_FUSED, FEATURES_S1,
    SEED, N_TREES, MIN_LEAF_POPULATION, BAG_FRACTION,
    DEFAULT_S1_WINDOW, DEFAULT_S2_WINDOW,
    S1_BANDS, S2_BANDS,
)


def train_classifiers(training_fc: ee.FeatureCollection) -> dict:
    """Train the two classifiers (fused S1+S2, S1-only).
    """
    polygons = training_fc.distinct('Name').randomColumn('rand', SEED)
    train_polys = polygons.filter(ee.Filter.lt('rand', 0.99))
    subset = training_fc.filter(
        ee.Filter.inList('Name', train_polys.aggregate_array('Name')))

    def train(features):
        return ee.Classifier.smileRandomForest(
            numberOfTrees=N_TREES,
            minLeafPopulation=MIN_LEAF_POPULATION,
            bagFraction=BAG_FRACTION,
            seed=SEED,
        ).train(
            features=subset,
            classProperty='waterType',
            inputProperties=features,
        )

    return {
        'fused': train(FEATURES_FUSED),
        's1':    train(FEATURES_S1),
    }


def _nearest_image(coll: ee.ImageCollection, target_date: ee.Date) -> ee.ImageCollection:
    """Annotate each image with |t - target|, then sort descending so
    the nearest image ends up first after `mosaic()`."""
    def annot(img):
        diff = ee.Number(img.get('system:time_start')).subtract(
            target_date.millis()).abs()
        return img.set('date_dist', diff)
    return coll.map(annot).sort('date_dist', False) #this sorting is important because when the tiles are mosaicked, it choses the first one in the collection


def rf_water_for_biweek(target_date: ee.Date,
                        roi: ee.Geometry,
                        rfs: dict,
                        s1_window_days: int = DEFAULT_S1_WINDOW,
                        s2_window_days: int = DEFAULT_S2_WINDOW) -> ee.Image:
    """Produce a single-band byte water mask for the bi-week centred on
    `target_date`(closest to target_date).

    The mask is the prediction of the fused (S1 + S2) classifier where
    S2 is cloud/shadow-free, and the S1-only classifier where S2 is
    obstructed. 
    """
    def pick(coll_id, w):
        c = (ee.ImageCollection(coll_id)
             .filterBounds(roi)
             .filterDate(target_date.advance(-w, 'day'),
                         target_date.advance(w, 'day')))
        return {'coll': c, 'has_any': c.size().gt(0)}

    s1p = pick('COPERNICUS/S1_GRD',           s1_window_days)
    s2p = pick('COPERNICUS/S2_SR_HARMONIZED', s2_window_days)

    s1_sorted = _nearest_image(s1p['coll'], target_date)
    s2_sorted = _nearest_image(s2p['coll'], target_date)

    # Constant-zero fallback images keep `.select(...)` from raising
    # when the collection happens to be empty.
    s2_empty = (ee.Image.constant(0).rename('B2')
                .addBands(ee.Image.constant(0).rename('B3'))
                .addBands(ee.Image.constant(0).rename('B4'))
                .addBands(ee.Image.constant(0).rename('B8'))
                .addBands(ee.Image.constant(0).rename('B8A'))
                .addBands(ee.Image.constant(0).rename('B11'))
                .addBands(ee.Image.constant(0).rename('SCL')))
    s1_empty = (ee.Image.constant(0).rename('VV')
                .addBands(ee.Image.constant(0).rename('VH')))

    s2_image = ee.Image(ee.Algorithms.If(
        s2p['has_any'],
        s2_sorted.mosaic().select(S2_BANDS).clip(roi),
        s2_empty.clip(roi)))
    s1_image = ee.Image(ee.Algorithms.If(
        s1p['has_any'],
        s1_sorted.mosaic().select(S1_BANDS).clip(roi),
        s1_empty.clip(roi)))

    # Cast both to ee.Number before .and() — otherwise the untyped
    # ComputedObject doesn't expose .And/.and.
    has_data = ee.Number(s1p['has_any']).And(ee.Number(s2p['has_any']))

    scl = s2_image.select('SCL')
    is_obstructed = scl.eq(9).Or(scl.eq(10)).Or(scl.eq(3))

    ndwi  = s2_image.normalizedDifference(['B3', 'B8']).rename('NDWI')
    bgr   = (s2_image.select('B2')
             .divide(s2_image.select('B3')).rename('BGR'))
    mndwi = s2_image.normalizedDifference(['B3', 'B11']).rename('MNDWI')
    ratio = (s1_image.select('VV').subtract(s1_image.select('VH'))
             .rename('VV_VH_ratio'))

    fused = (s2_image.addBands([ndwi, mndwi, bgr, ratio])
             .addBands(s1_image.select(['VV', 'VH']))
             .select(FEATURES_FUSED))
    s1_only = (s1_image.select(['VV', 'VH']).addBands([ratio])
               .select(FEATURES_S1))

    classified = (fused.classify(rfs['fused'])
                  .where(is_obstructed, s1_only.classify(rfs['s1'])))

    return classified.updateMask(ee.Image.constant(has_data))
