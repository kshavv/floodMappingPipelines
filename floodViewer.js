// ============================================================
// CLASSIFIED FLOOD MAP — VIEWER + BHUVAN COMPARISON
// ============================================================
// This is used to visualize the flood maps over the entire year
// also used to compare the result with Bhuvan bi-weekly flood maps (BW_12..BW_21) for Kharif season.
// ============================================================


// ── CONFIG ───────────────────────────────────────────────────
var ASSET_ROOT         = 'projects/gentle-operator-308420/assets/Classified';
var BHUVAN_ASSET_ROOT  = 'projects/gentle-operator-308420/assets/Bhuvan';
var DEFAULT_TITLE      = 'kerala';
var DEFAULT_YEAR       = String(new Date().getFullYear() - 1);

var SCALE              = 30;
var NATIVE_CRS         = 'EPSG:4326';
var N_BIWEEKS_FULL     = 26;

var CLS_PERENNIAL = 1;
var CLS_LAND      = 2;
var CLS_SEASONAL  = 3;
var CLS_REGULAR   = 4;
var CLS_ANOMALOUS = 5;

// Codes that count as "flooded" in the classified map for comparison.
// Perennial (1) and land (2) are NOT flooded.
var FLOODED_CLASSIFIED_CODES = [CLS_SEASONAL, CLS_REGULAR, CLS_ANOMALOUS];

// Bhuvan: 1 = flooded, 0 = land, 255 = nodata.
var BHUVAN_FLOOD_CODE  = 1;
var BHUVAN_NODATA_CODE = 255;

// 5-class palette / labels (Kharif bands of classified).
var KHARIF_PALETTE = ['#3B82F6', '#E5E7EB', '#ffed00', '#F59E0B', '#EF4444'];
var KHARIF_LABELS  = ['Perennial water', 'Land / non-water',
                      'Seasonal water', 'Regular flood', 'Anomalous water'];

// 2-class palette / labels (Rabi & Zaid bands of classified).
var TWOCLASS_PALETTE = ['#3B82F6', '#E5E7EB'];
var TWOCLASS_LABELS  = ['Water', 'Non-water'];

// Bhuvan palette (cyan flood on grey).
var BHUVAN_PALETTE = ['#E5E7EB', '#06B6D4'];   // 0 → grey, 1 → cyan
var BHUVAN_VIS = {min: 0, max: 1, palette: BHUVAN_PALETTE};

// Fallback season → slot mapping.
var FALLBACK_KHARIF_SLOTS = [10,11,12,13,14,15,16,17,18,19];
var FALLBACK_ZAID_SLOTS   = [6,7,8,9];

// Bi-weeks where Bhuvan has data (matches Python pipeline: BW_12..BW_21).
var BHUVAN_BW_NUMBERS = [12, 13, 14, 15, 16, 17, 18, 19, 20, 21];
function bandIsInBhuvan(bandName) {
  var n = parseInt(bandName.replace('BW_', ''), 10);
  return BHUVAN_BW_NUMBERS.indexOf(n) !== -1;
}

function biweekWindowStr(year, bwZeroBased) {
  var DAY_MS = 86400000;
  var jan1 = Date.UTC(year, 0, 1);
  var sMs = jan1 + bwZeroBased * 14 * DAY_MS;
  var eMs = sMs + 13 * DAY_MS;
  function f(ms) {
    var x = new Date(ms);
    return ('0' + x.getUTCDate()).slice(-2) + '-' +
           ('0' + (x.getUTCMonth() + 1)).slice(-2) + '-' +
           x.getUTCFullYear();
  }
  return f(sMs) + ' → ' + f(eMs);
}


// ── App state ────────────────────────────────────────────────
var appState = {
  // Classified asset
  image:        null,
  assetId:      null,
  year:         null,
  title:        null,
  bandSeason:   {},
  bandList:     [],
  geometry:     null,
  // Bhuvan asset
  bhuvanImage:   null,
  bhuvanAssetId: null,
  bhuvanBands:   [],
  // Comparison region
  compareBbox:   null    // ee.Geometry rectangle, or null
};


// ============================================================
// UI LAYOUT
// ============================================================

ui.root.clear();

var mapPanel = ui.Map();
mapPanel.setOptions('HYBRID');
mapPanel.style().set('cursor', 'crosshair');
mapPanel.setCenter(76.5, 10.5, 7);

var sidePanel = ui.Panel({
  style: {width: '440px', padding: '8px', backgroundColor: '#fafafa'}
});

ui.root.add(sidePanel);
ui.root.add(mapPanel);


// ── Header ───────────────────────────────────────────────────
sidePanel.add(ui.Label('🌊 Classified Flood Map — Viewer + Bhuvan Compare', {
  fontWeight: 'bold', fontSize: '20px', margin: '4px 0 2px 0'
}));
sidePanel.add(ui.Label(
  'View the pre-classified asset and (optionally) the Bhuvan bi-weekly ' +
  'stack. On Kharif bi-weeks (BW_12..BW_21) you can draw a bbox and ' +
  'compute precision / recall / F1 between the two.',
  {fontSize: '11px', color: '#555', margin: '0 0 8px 0'}));


// ============================================================
// STAGE 1 — LOAD ASSETS
// ============================================================
sidePanel.add(ui.Label('Stage 1 — Load assets', {
  fontWeight: 'bold', fontSize: '14px', margin: '8px 0 2px 0', color: '#0066cc'
}));

sidePanel.add(ui.Label('Title:', {fontSize: '11px', margin: '6px 0 0 0'}));
var titleInput = ui.Textbox({
  value: DEFAULT_TITLE, placeholder: 'e.g. kerala or kerala_ernakulam',
  style: {width: '300px'}
});
sidePanel.add(titleInput);

sidePanel.add(ui.Label('Year:', {fontSize: '11px', margin: '6px 0 0 0'}));
var yearInput = ui.Textbox({
  value: DEFAULT_YEAR, placeholder: 'YYYY', style: {width: '80px'}
});
sidePanel.add(yearInput);

sidePanel.add(ui.Label('Bhuvan asset name (file inside the Bhuvan folder):',
                       {fontSize: '11px', margin: '6px 0 0 0'}));
var bhuvanNameInput = ui.Textbox({
  placeholder: 'e.g. bhuvan_kharif_biweek_kerala_ernakulam_2023_union',
  style: {width: '300px'}
});
sidePanel.add(bhuvanNameInput);

sidePanel.add(ui.Label('Classified asset root:',
                       {fontSize: '11px', margin: '6px 0 0 0'}));
var assetRootInput = ui.Textbox({value: ASSET_ROOT, style: {width: '300px'}});
sidePanel.add(assetRootInput);

sidePanel.add(ui.Label('Bhuvan asset root:',
                       {fontSize: '11px', margin: '6px 0 0 0'}));
var bhuvanRootInput = ui.Textbox({value: BHUVAN_ASSET_ROOT,
                                  style: {width: '300px'}});
sidePanel.add(bhuvanRootInput);

var loadClassifiedBtn = ui.Button({
  label: '📂 Load classified asset',
  style: {stretch: 'horizontal', margin: '8px 0 2px 0'}
});
sidePanel.add(loadClassifiedBtn);

var loadBhuvanBtn = ui.Button({
  label: '📂 Load Bhuvan asset (optional)',
  style: {stretch: 'horizontal', margin: '2px 0'}
});
sidePanel.add(loadBhuvanBtn);

var loadStatusLabel = ui.Label('', {fontSize: '11px', color: '#555', margin: '2px 0'});
sidePanel.add(loadStatusLabel);
var bhuvanStatusLabel = ui.Label('', {fontSize: '11px', color: '#555', margin: '2px 0'});
sidePanel.add(bhuvanStatusLabel);


// ============================================================
// STAGE 2 — SELECT BAND + DISPLAY
// ============================================================
var stage2Panel = ui.Panel({style: {margin: '0', padding: '0', shown: false}});
stage2Panel.add(ui.Label('Stage 2 — Select bi-week band', {
  fontWeight: 'bold', fontSize: '14px', margin: '14px 0 2px 0', color: '#0066cc'
}));
stage2Panel.add(ui.Label(
  'Pick one of the 26 bands. Kharif → 5-class, Rabi/Zaid → 2-class. ' +
  'Bhuvan layer auto-shows on BW_12..BW_21 if loaded.',
  {fontSize: '11px', color: '#555', margin: '0 0 4px 0'}));

var bandSelect = ui.Select({
  items: ['(load an asset first)'],
  placeholder: 'Pick a band',
  disabled: true,
  style: {stretch: 'horizontal', margin: '4px 0'}
});
stage2Panel.add(bandSelect);

var showBtn = ui.Button({
  label: '▶ Display selected band',
  disabled: true,
  style: {stretch: 'horizontal', margin: '6px 0'}
});
stage2Panel.add(showBtn);

sidePanel.add(stage2Panel);


// ============================================================
// STAGE 3 — COMPARISON (Kharif only, both assets needed)
// ============================================================
var stage3Panel = ui.Panel({style: {margin: '0', padding: '0', shown: false}});
stage3Panel.add(ui.Label('Stage 3 — Compare with Bhuvan', {
  fontWeight: 'bold', fontSize: '14px', margin: '14px 0 2px 0', color: '#0066cc'
}));
stage3Panel.add(ui.Label(
  'Draw a bbox or enter coordinates. Comparison merges classified ' +
  '{3, 4, 5} as flooded; perennial (1) and land (2) are excluded. ' +
  'Pixels where either map is nodata (255) are skipped.',
  {fontSize: '11px', color: '#555', margin: '0 0 4px 0'}));

var drawBboxBtn = ui.Button({
  label: '✏ Draw bbox on map',
  style: {stretch: 'horizontal', margin: '4px 0'}
});
stage3Panel.add(drawBboxBtn);

stage3Panel.add(ui.Label(
  '…or enter bbox manually [west, south, east, north]:',
  {fontSize: '11px', margin: '6px 0 0 0'}));
var bboxWestInput  = ui.Textbox({placeholder: 'west',  style: {width: '90px'}});
var bboxSouthInput = ui.Textbox({placeholder: 'south', style: {width: '90px'}});
var bboxEastInput  = ui.Textbox({placeholder: 'east',  style: {width: '90px'}});
var bboxNorthInput = ui.Textbox({placeholder: 'north', style: {width: '90px'}});
stage3Panel.add(ui.Panel(
  [bboxWestInput, bboxSouthInput, bboxEastInput, bboxNorthInput],
  ui.Panel.Layout.flow('horizontal')));

var applyBboxBtn = ui.Button({
  label: '⤴ Use these coordinates',
  style: {stretch: 'horizontal', margin: '4px 0'}
});
stage3Panel.add(applyBboxBtn);

var clearBboxBtn = ui.Button({
  label: '✗ Clear bbox',
  style: {stretch: 'horizontal', margin: '4px 0'}
});
stage3Panel.add(clearBboxBtn);

stage3Panel.add(ui.Label('Scale (m):', {fontSize: '11px', margin: '6px 0 0 0'}));
var scaleInput = ui.Textbox({value: String(SCALE), style: {width: '80px'}});
stage3Panel.add(scaleInput);

var computeMetricsBtn = ui.Button({
  label: '📊 Compute precision / recall / F1',
  style: {stretch: 'horizontal', margin: '8px 0 2px 0'}
});
stage3Panel.add(computeMetricsBtn);

var metricsPanel = ui.Panel({style: {margin: '4px 0', fontSize: '11px'}});
stage3Panel.add(metricsPanel);

sidePanel.add(stage3Panel);


// ============================================================
// SHARED CONTROLS
// ============================================================
var statusLabel = ui.Label('Ready. Enter title + year and click Load.',
                           {fontSize: '11px', color: '#0066cc', margin: '8px 0'});
sidePanel.add(statusLabel);

sidePanel.add(ui.Label('Metadata', {fontWeight: 'bold', margin: '10px 0 2px 0'}));
var metaPanel = ui.Panel({style: {fontSize: '11px', margin: '0 0 6px 0'}});
sidePanel.add(metaPanel);

sidePanel.add(ui.Label('Area by class (ha)', {fontWeight: 'bold', margin: '10px 0 2px 0'}));
var areaPanel = ui.Panel({style: {fontSize: '11px', margin: '0 0 6px 0'}});
sidePanel.add(areaPanel);

sidePanel.add(ui.Label('Layers', {fontWeight: 'bold', margin: '10px 0 2px 0'}));
var layerControls = {};
function addLayerCheckbox(key, label, defaultOn) {
  var cb = ui.Checkbox({label: label, value: defaultOn, style: {fontSize: '11px'}});
  cb.onChange(function(checked) {
    if (layerControls[key].layer) layerControls[key].layer.setShown(checked);
  });
  sidePanel.add(cb);
  layerControls[key] = {checkbox: cb, layer: null};
}
addLayerCheckbox('classified', 'Classified band', true);
addLayerCheckbox('bhuvan',     'Bhuvan band',     true);

sidePanel.add(ui.Label('Legend', {fontWeight: 'bold', margin: '12px 0 2px 0'}));
var legendTitleLabel = ui.Label('(load a band)',
                                {fontSize: '10px', color: '#555', margin: '0 0 2px 0'});
sidePanel.add(legendTitleLabel);
var legendPanel = ui.Panel();
sidePanel.add(legendPanel);


// ── Display state ────────────────────────────────────────────
var displayState = {
  band:        null,
  season:      null,
  image:       null,        // single-band classified image
  bhuvanImage: null,        // single-band Bhuvan image (may be null)
  palette:     null,
  labels:      null
};


// ============================================================
// HELPERS
// ============================================================
function paletteForSeason(season) {
  return (season === 'kharif') ? KHARIF_PALETTE : TWOCLASS_PALETTE;
}
function labelsForSeason(season) {
  return (season === 'kharif') ? KHARIF_LABELS : TWOCLASS_LABELS;
}
function seasonLabel(season) {
  return {kharif: 'Kharif', rabi: 'Rabi', zaid: 'Zaid'}[season] || season;
}

function refreshLegend() {
  var labels  = displayState.labels  || KHARIF_LABELS;
  var palette = displayState.palette || KHARIF_PALETTE;
  var s = displayState.season ? seasonLabel(displayState.season) : '(none)';
  var scheme = (displayState.season === 'kharif') ? '5-class' : '2-class';
  legendTitleLabel.setValue('Band: ' + (displayState.band || '?') +
                            '   Season: ' + s + '   (' + scheme + ')');
  legendPanel.clear();
  labels.forEach(function(label, i) {
    legendPanel.add(ui.Panel([
      ui.Label('', {backgroundColor: palette[i], padding: '8px',
                    margin: '2px 6px 2px 0', border: '1px solid #888'}),
      ui.Label(label, {margin: '4px 0 0 0', fontSize: '11px'})
    ], ui.Panel.Layout.flow('horizontal')));
  });
  // Add Bhuvan legend entry if Bhuvan is being shown.
  if (displayState.bhuvanImage) {
    legendPanel.add(ui.Panel([
      ui.Label('', {backgroundColor: BHUVAN_PALETTE[1], padding: '8px',
                    margin: '2px 6px 2px 0', border: '1px solid #888'}),
      ui.Label('Bhuvan flood (cyan)',
               {margin: '4px 0 0 0', fontSize: '11px'})
    ], ui.Panel.Layout.flow('horizontal')));
  }
}

function setMetadataLabel(panel, key, value) {
  panel.add(ui.Label(key + ': ' + value, {fontSize: '11px', margin: '1px 0'}));
}

function clearLayers() {
  Object.keys(layerControls).forEach(function(k) { layerControls[k].layer = null; });
  mapPanel.layers().reset();
}

function parseBandSeasonProps(props) {
  var map = {};
  var any = false;
  ['kharif', 'rabi', 'zaid'].forEach(function(season) {
    var v = props[season + '_bands'];
    if (v && typeof v === 'string') {
      v.split(',').forEach(function(b) {
        var name = b.trim();
        if (name) { map[name] = season; any = true; }
      });
    }
  });
  return any ? map : null;
}

function fallbackBandSeason(bandNames) {
  var kh = {}, za = {};
  FALLBACK_KHARIF_SLOTS.forEach(function(s){ kh['BW_' + (s + 1)] = true; });
  FALLBACK_ZAID_SLOTS.forEach(function(s){ za['BW_' + (s + 1)] = true; });
  var map = {};
  bandNames.forEach(function(b) {
    if (kh[b])      map[b] = 'kharif';
    else if (za[b]) map[b] = 'zaid';
    else            map[b] = 'rabi';
  });
  return map;
}

// Show or hide Stage 3 depending on whether both assets are loaded AND
// the currently selected band is a Bhuvan bi-week.
function refreshStage3Visibility() {
  if (!appState.image || !appState.bhuvanImage || !displayState.band) {
    stage3Panel.style().set('shown', false);
    return;
  }
  var b = displayState.band;
  var ok = bandIsInBhuvan(b) &&
           (appState.bhuvanBands.indexOf(b) !== -1 ||
            appState.bhuvanBands.length === 1);
  stage3Panel.style().set('shown', !!ok);
}


// Rebuild the band-selector dropdown so that bands also present in the
// loaded Bhuvan asset get a "[Bhuvan]" annotation. Called once after
// the classified asset loads, and again whenever the Bhuvan asset is
// loaded or replaced — so the user sees the annotations without having
// to re-load the classified asset.
function rebuildBandDropdown() {
  if (!appState.bandsOrdered || !appState.bandsOrdered.length) return;
  var items = appState.bandsOrdered.map(function(b) {
    var slot = parseInt(b.replace('BW_', ''), 10) - 1;
    var season = appState.bandSeason[b] || 'rabi';
    var bhvHas = appState.bhuvanBands.indexOf(b) !== -1
                 || (appState.bhuvanBands.length === 1 && bandIsInBhuvan(b));
    var tail = bhvHas ? '  [Bhuvan]' : '';
    return {
      label: b + ' — ' + seasonLabel(season) +
             '  (' + biweekWindowStr(appState.year, slot) + ')' + tail,
      value: b
    };
  });
  var prev = bandSelect.getValue();
  bandSelect.items().reset(items);
  // Re-select whatever was selected before, if it's still in the list.
  if (prev && appState.bandsOrdered.indexOf(prev) !== -1) {
    bandSelect.setValue(prev, false);
  }
}


// ============================================================
// STAGE 1 HANDLER — LOAD CLASSIFIED
// ============================================================
loadClassifiedBtn.onClick(function() {
  var title = (titleInput.getValue() || '').trim();
  var yearStr = (yearInput.getValue() || '').trim();
  var year = parseInt(yearStr, 10);
  var root = (assetRootInput.getValue() || ASSET_ROOT).trim().replace(/\/+$/, '');

  if (!title) {
    loadStatusLabel.setValue('✗ Title required.');
    loadStatusLabel.style().set('color', '#cc0000');
    return;
  }
  if (isNaN(year)) {
    loadStatusLabel.setValue('✗ Invalid year.');
    loadStatusLabel.style().set('color', '#cc0000');
    return;
  }

  var assetId = root + '/Classified_' + year + '_' + title;
  loadStatusLabel.setValue('⏳ Loading ' + assetId + ' …');
  loadStatusLabel.style().set('color', '#0066cc');
  metaPanel.clear();
  areaPanel.clear();
  clearLayers();
  bandSelect.setDisabled(true);
  showBtn.setDisabled(true);

  var img = ee.Image(assetId);

  ee.Dictionary({
    bands:              img.bandNames(),
    year:               img.get('year'),
    admin_state:        img.get('admin_state'),
    district_numbering: img.get('district_numbering'),
    classification_scheme: img.get('classification_scheme'),
    kharif_bands:       img.get('kharif_bands'),
    rabi_bands:         img.get('rabi_bands'),
    zaid_bands:         img.get('zaid_bands')
  }).evaluate(function(d, err) {
    if (err) {
      loadStatusLabel.setValue('✗ Could not load asset: ' + err);
      loadStatusLabel.style().set('color', '#cc0000');
      bandSelect.items().reset(['(load failed)']);
      return;
    }
    if (!d.bands || d.bands.length === 0) {
      loadStatusLabel.setValue('✗ Asset has no bands.');
      loadStatusLabel.style().set('color', '#cc0000');
      return;
    }

    var bandSeason = parseBandSeasonProps(d) || fallbackBandSeason(d.bands);

    appState.image      = img;
    appState.assetId    = assetId;
    appState.year       = year;
    appState.title      = title;
    appState.bandSeason = bandSeason;
    appState.bandList   = d.bands.slice();
    appState.geometry   = img.geometry();

    var ordered = d.bands.slice().sort(function(a, b) {
      return parseInt(a.replace('BW_', ''), 10) -
             parseInt(b.replace('BW_', ''), 10);
    });
    appState.bandsOrdered = ordered;     // remembered so we can rebuild later
    rebuildBandDropdown();
    bandSelect.setDisabled(false);
    bandSelect.setPlaceholder('Pick a band');
    showBtn.setDisabled(false);
    stage2Panel.style().set('shown', true);
    mapPanel.centerObject(appState.geometry, 8);

    var msg = '✓ Loaded ' + d.bands.length + '-band classified asset.';
    if (d.admin_state) msg += '  State: ' + d.admin_state + '.';
    if (d.district_numbering) msg += '  Districts: ' + d.district_numbering + '.';
    loadStatusLabel.setValue(msg);
    loadStatusLabel.style().set('color', '#10b981');
    statusLabel.setValue('✓ Classified loaded. Optionally load Bhuvan, then pick a band.');

    metaPanel.clear();
    setMetadataLabel(metaPanel, 'Classified asset', assetId);
    setMetadataLabel(metaPanel, 'Year', d.year != null ? d.year : year);
    if (d.admin_state) setMetadataLabel(metaPanel, 'State', d.admin_state);
    if (d.district_numbering)
      setMetadataLabel(metaPanel, 'Districts', d.district_numbering);
    setMetadataLabel(metaPanel, 'Bands', d.bands.length);
    if (d.classification_scheme)
      setMetadataLabel(metaPanel, 'Scheme', d.classification_scheme);
  });
});


// ============================================================
// STAGE 1 HANDLER — LOAD BHUVAN
// ============================================================
loadBhuvanBtn.onClick(function() {
  var name = (bhuvanNameInput.getValue() || '').trim();
  var root = (bhuvanRootInput.getValue() || BHUVAN_ASSET_ROOT)
             .trim().replace(/\/+$/, '');

  if (!name) {
    bhuvanStatusLabel.setValue('✗ Bhuvan asset name required.');
    bhuvanStatusLabel.style().set('color', '#cc0000');
    return;
  }

  var assetId = root + '/' + name;
  bhuvanStatusLabel.setValue('⏳ Loading Bhuvan ' + assetId + ' …');
  bhuvanStatusLabel.style().set('color', '#0066cc');

  var img = ee.Image(assetId);
  img.bandNames().evaluate(function(bands, err) {
    if (err) {
      bhuvanStatusLabel.setValue('✗ Could not load Bhuvan: ' + err);
      bhuvanStatusLabel.style().set('color', '#cc0000');
      appState.bhuvanImage = null;
      appState.bhuvanAssetId = null;
      appState.bhuvanBands = [];
      refreshStage3Visibility();
      return;
    }
    appState.bhuvanImage   = img;
    appState.bhuvanAssetId = assetId;
    appState.bhuvanBands   = bands.slice();

    bhuvanStatusLabel.setValue('✓ Loaded Bhuvan asset (' + bands.length +
                               ' bands).');
    bhuvanStatusLabel.style().set('color', '#10b981');
    setMetadataLabel(metaPanel, 'Bhuvan asset', assetId);
    rebuildBandDropdown();
    refreshStage3Visibility();
  });
});


// ============================================================
// STAGE 2 HANDLER — DISPLAY SELECTED BAND
// ============================================================
showBtn.onClick(function() {
  var band = bandSelect.getValue();
  if (!appState.image || !band) {
    statusLabel.setValue('✗ Load an asset and pick a band first.');
    return;
  }

  var season = appState.bandSeason[band] || 'rabi';
  var slot = parseInt(band.replace('BW_', ''), 10) - 1;
  var palette = paletteForSeason(season);
  var labels  = labelsForSeason(season);

  var bandImg = appState.image.select([band]).rename('classification');

  displayState.band    = band;
  displayState.season  = season;
  displayState.image   = bandImg;
  displayState.palette = palette;
  displayState.labels  = labels;

  // Bhuvan band: same band name if it exists in BW_12..BW_21 AND
  // Bhuvan asset is loaded.
  displayState.bhuvanImage = null;
  if (appState.bhuvanImage && bandIsInBhuvan(band)) {
    // Try to select by the expected Kharif band name (BW_12..BW_21).
    // If the Bhuvan asset doesn't have that band but has exactly one
    // band (single-image upload for verification), use that single
    // band — assumes the user lined it up with the currently selected
    // biweek.
    var pickName = band;
    if (appState.bhuvanBands.indexOf(band) === -1) {
      if (appState.bhuvanBands.length === 1) {
        pickName = appState.bhuvanBands[0];
      } else {
        statusLabel.setValue('⚠ Bhuvan asset has no band "' + band +
          '". Available: ' + appState.bhuvanBands.join(', ') +
          '. Skipping overlay.');
        pickName = null;
      }
    }
    if (pickName) {
      var b = appState.bhuvanImage.select([pickName]).rename('bhuvan');
      displayState.bhuvanImage = b.updateMask(b.neq(BHUVAN_NODATA_CODE));
    }
  }

  // ── Render ──────────────────────────────────────────────
  clearLayers();
  var renderPalette = (season === 'kharif')
    ? KHARIF_PALETTE
    : [TWOCLASS_PALETTE[0], TWOCLASS_PALETTE[1],
       TWOCLASS_PALETTE[1], TWOCLASS_PALETTE[1], TWOCLASS_PALETTE[1]];
  var vis = {min: 1, max: 5, palette: renderPalette};

  var clsLayer = ui.Map.Layer(
    bandImg.selfMask(), vis, 'Classified ' + band,
    layerControls.classified.checkbox.getValue());
  layerControls.classified.layer = clsLayer;
  mapPanel.layers().add(clsLayer);

  if (displayState.bhuvanImage) {
    var bhuvanLayer = ui.Map.Layer(
      displayState.bhuvanImage, BHUVAN_VIS, 'Bhuvan ' + band,
      layerControls.bhuvan.checkbox.getValue());
    layerControls.bhuvan.layer = bhuvanLayer;
    mapPanel.layers().add(bhuvanLayer);
  }

  mapPanel.centerObject(appState.geometry, 9);
  refreshLegend();
  refreshStage3Visibility();

  // ── Metadata for the chosen band ─────────────────────────
  metaPanel.clear();
  setMetadataLabel(metaPanel, 'Classified asset', appState.assetId);
  if (appState.bhuvanAssetId)
    setMetadataLabel(metaPanel, 'Bhuvan asset', appState.bhuvanAssetId);
  setMetadataLabel(metaPanel, 'Year', appState.year);
  setMetadataLabel(metaPanel, 'Band', band);
  setMetadataLabel(metaPanel, 'Season', seasonLabel(season));
  setMetadataLabel(metaPanel, 'Bi-week window',
    biweekWindowStr(appState.year, slot));
  if (bandIsInBhuvan(band)) {
    setMetadataLabel(metaPanel, 'Bhuvan overlay',
      appState.bhuvanImage ? 'on' : 'asset not loaded');
  } else {
    setMetadataLabel(metaPanel, 'Bhuvan overlay', 'not available (non-Kharif)');
  }

  statusLabel.setValue('⏳ Computing area statistics for ' + band + ' …');
  computeAreaStats(bandImg, season, appState.geometry, function() {
    statusLabel.setValue('✓ Displaying ' + band + ' (' +
                         seasonLabel(season) + ').');
  });
});


// ============================================================
// AREA STATISTICS
// ============================================================
function computeAreaStats(bandImg, season, roi, onDone) {
  var labels  = labelsForSeason(season);
  var palette = paletteForSeason(season);
  var nClasses = labels.length;

  var pixelArea = ee.Image.pixelArea().divide(10000);
  var bands = [];
  for (var i = 0; i < nClasses; i++) {
    bands.push(pixelArea.updateMask(bandImg.eq(i + 1)).rename('c' + (i + 1)));
  }

  areaPanel.clear();
  ee.Image.cat(bands).reduceRegion({
    reducer: ee.Reducer.sum(), geometry: roi, scale: SCALE,
    crs: NATIVE_CRS, maxPixels: 1e10, bestEffort: true
  }).evaluate(function(d, err) {
    if (err) { statusLabel.setValue('✗ Area error: ' + err); return; }
    var total = 0;
    for (var i = 0; i < nClasses; i++) total += (d['c' + (i + 1)] || 0);
    labels.forEach(function(label, i) {
      var ha = d['c' + (i + 1)] || 0;
      var pct = total > 0 ? (100 * ha / total).toFixed(1) : '0.0';
      areaPanel.add(ui.Panel([
        ui.Label('', {backgroundColor: palette[i], padding: '6px',
                      margin: '1px 6px 1px 0'}),
        ui.Label(label + ': ' + ha.toFixed(0) + ' ha (' + pct + '%)',
                 {fontSize: '11px', margin: '2px 0'})
      ], ui.Panel.Layout.flow('horizontal')));
    });
    if (onDone) onDone();
  });
}


// ============================================================
// STAGE 3 — BBOX DRAWING + APPLY
// ============================================================
// We use the Map's drawing tools. A separate Layer holds the user-drawn
// rectangle so it doesn't conflict with the comparison layers.

function setBboxOnMap(west, south, east, north) {
  // Replace any existing bbox layer with a fresh outlined rectangle.
  // Remove old by name.
  var layers = mapPanel.layers();
  for (var i = layers.length() - 1; i >= 0; i--) {
    if (layers.get(i).getName() === 'Compare bbox') {
      layers.remove(layers.get(i));
    }
  }
  appState.compareBbox = ee.Geometry.Rectangle([west, south, east, north]);
  var outline = ee.Image().byte().paint({
    featureCollection: ee.FeatureCollection([ee.Feature(appState.compareBbox)]),
    color: 1, width: 3
  });
  var lyr = ui.Map.Layer(outline, {palette: ['#ff00ff']}, 'Compare bbox');
  mapPanel.layers().add(lyr);
  // Reflect into the manual textboxes.
  bboxWestInput.setValue(String(west));
  bboxSouthInput.setValue(String(south));
  bboxEastInput.setValue(String(east));
  bboxNorthInput.setValue(String(north));
}

drawBboxBtn.onClick(function() {
  statusLabel.setValue('✏ Click two opposing corners on the map to draw a rectangle.');
  var drawingTools = mapPanel.drawingTools();
  drawingTools.setShown(true);
  drawingTools.setDrawModes(['rectangle']);
  drawingTools.setShape('rectangle');
  // Remove existing user-drawn geometries.
  while (drawingTools.layers().length() > 0) {
    drawingTools.layers().remove(drawingTools.layers().get(0));
  }
  var dummy = ui.Map.GeometryLayer({geometries: [], name: 'bbox_layer', color: '#ff00ff'});
  drawingTools.layers().add(dummy);
  drawingTools.setLinked(false);
  drawingTools.draw();

  var onDraw = function(geom) {
    drawingTools.onDraw(null);
    drawingTools.setShape(null);
    drawingTools.stop();
    var coords = geom.bounds().coordinates().getInfo()[0];
    var xs = coords.map(function(c){ return c[0]; });
    var ys = coords.map(function(c){ return c[1]; });
    var west  = Math.min.apply(null, xs);
    var east  = Math.max.apply(null, xs);
    var south = Math.min.apply(null, ys);
    var north = Math.max.apply(null, ys);
    setBboxOnMap(west, south, east, north);
    statusLabel.setValue('✓ Bbox captured. Click "Compute precision / recall / F1".');
  };
  drawingTools.onDraw(onDraw);
});

applyBboxBtn.onClick(function() {
  var w = parseFloat(bboxWestInput.getValue());
  var s = parseFloat(bboxSouthInput.getValue());
  var e = parseFloat(bboxEastInput.getValue());
  var n = parseFloat(bboxNorthInput.getValue());
  if ([w, s, e, n].some(isNaN) || w >= e || s >= n) {
    statusLabel.setValue('✗ Bad bbox: need west<east, south<north.');
    return;
  }
  setBboxOnMap(w, s, e, n);
  statusLabel.setValue('✓ Bbox set from manual coordinates.');
});

clearBboxBtn.onClick(function() {
  appState.compareBbox = null;
  var layers = mapPanel.layers();
  for (var i = layers.length() - 1; i >= 0; i--) {
    if (layers.get(i).getName() === 'Compare bbox') layers.remove(layers.get(i));
  }
  bboxWestInput.setValue('');  bboxSouthInput.setValue('');
  bboxEastInput.setValue('');  bboxNorthInput.setValue('');
  metricsPanel.clear();
  statusLabel.setValue('✓ Bbox cleared.');
});


// ============================================================
// STAGE 3 — COMPUTE METRICS
// ============================================================
computeMetricsBtn.onClick(function() {
  if (!appState.image || !appState.bhuvanImage) {
    statusLabel.setValue('✗ Need both Classified + Bhuvan assets loaded.');
    return;
  }
  if (!displayState.band || !bandIsInBhuvan(displayState.band)) {
    statusLabel.setValue('✗ Comparison only works on Kharif bands (BW_12..BW_21).');
    return;
  }
  if (!appState.compareBbox) {
    statusLabel.setValue('✗ Draw a bbox or enter coordinates first.');
    return;
  }
  var scale = parseFloat(scaleInput.getValue()) || SCALE;

  metricsPanel.clear();
  statusLabel.setValue('⏳ Computing confusion matrix in bbox at ' + scale + ' m …');

  var band = displayState.band;
  var cls = appState.image.select([band]).rename('cls');
  // Pick Bhuvan band: prefer the same name, fall back to the asset's
  // single band when present (single-image verification upload).
  var bhvBand = band;
  if (appState.bhuvanBands.indexOf(band) === -1) {
    if (appState.bhuvanBands.length === 1) {
      bhvBand = appState.bhuvanBands[0];
    } else {
      statusLabel.setValue('✗ Bhuvan asset has no band "' + band +
        '". Available: ' + appState.bhuvanBands.join(', ') + '.');
      return;
    }
  }
  var bhv = appState.bhuvanImage.select([bhvBand]).rename('bhv');

  // Predicted (classified) flooded = pixel is in {3, 4, 5}.
  var pred = cls.eq(CLS_SEASONAL)
              .or(cls.eq(CLS_REGULAR))
              .or(cls.eq(CLS_ANOMALOUS))
              .rename('pred');
  // Reference (Bhuvan) flooded = pixel == 1. Nodata is 255.
  var ref  = bhv.eq(BHUVAN_FLOOD_CODE).rename('ref');

  // Valid-pixel mask:
  //   * classified must be 1..5 (i.e. have a class assignment) — we
  //     test with mask() since the asset doesn't use an explicit nodata
  //     value. The classifier writes 1..5 inside the AOI and masks
  //     outside, so the existing pixel-mask from the asset already
  //     excludes outside-AOI pixels.
  //   * Bhuvan must not be the nodata sentinel.
  var validBhv = bhv.neq(BHUVAN_NODATA_CODE);
  var clsMask  = cls.mask();        // 1 inside AOI, 0 outside
  var both = validBhv.and(clsMask);

  // Confusion matrix bands: TP, FP, FN, TN, all masked to `both`.
  var tp = pred.eq(1).and(ref.eq(1)).updateMask(both).rename('tp');
  var fp = pred.eq(1).and(ref.eq(0)).updateMask(both).rename('fp');
  var fn = pred.eq(0).and(ref.eq(1)).updateMask(both).rename('fn');
  var tn = pred.eq(0).and(ref.eq(0)).updateMask(both).rename('tn');

  ee.Image.cat([tp, fp, fn, tn]).reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: appState.compareBbox,
    scale: scale,
    crs: NATIVE_CRS,
    maxPixels: 1e10,
    bestEffort: true
  }).evaluate(function(d, err) {
    if (err) {
      statusLabel.setValue('✗ Metrics error: ' + err);
      return;
    }
    var TP = d.tp || 0, FP = d.fp || 0, FN = d.fn || 0, TN = d.tn || 0;
    var total = TP + FP + FN + TN;
    var precision = (TP + FP > 0) ? TP / (TP + FP) : 0;
    var recall    = (TP + FN > 0) ? TP / (TP + FN) : 0;
    var f1        = (precision + recall > 0)
                    ? 2 * precision * recall / (precision + recall) : 0;
    var iou       = (TP + FP + FN > 0)
                    ? TP / (TP + FP + FN) : 0;

    function fmt(n) {
      // Format pixel counts; total area too if useful.
      return n.toFixed(0);
    }
    function pct(x) { return (100 * x).toFixed(2) + '%'; }
    var areaHa = total * scale * scale / 10000;

    metricsPanel.clear();
    metricsPanel.add(ui.Label('Band: ' + band, {fontWeight: 'bold'}));
    metricsPanel.add(ui.Label('Scale: ' + scale + ' m'));
    metricsPanel.add(ui.Label('Valid pixels compared: ' + fmt(total) +
                              '  (~' + areaHa.toFixed(0) + ' ha)'));
    metricsPanel.add(ui.Label(''));
    metricsPanel.add(ui.Label('Confusion matrix (pixel counts):',
                              {fontWeight: 'bold'}));
    metricsPanel.add(ui.Label('  TP (both flood)        : ' + fmt(TP)));
    metricsPanel.add(ui.Label('  FP (cls flood, bhv dry): ' + fmt(FP)));
    metricsPanel.add(ui.Label('  FN (cls dry, bhv flood): ' + fmt(FN)));
    metricsPanel.add(ui.Label('  TN (both dry)          : ' + fmt(TN)));
    metricsPanel.add(ui.Label(''));
    metricsPanel.add(ui.Label('Metrics (cls vs bhv as reference):',
                              {fontWeight: 'bold'}));
    metricsPanel.add(ui.Label('  Precision : ' + pct(precision)));
    metricsPanel.add(ui.Label('  Recall    : ' + pct(recall)));
    metricsPanel.add(ui.Label('  F1 score  : ' + pct(f1)));
    metricsPanel.add(ui.Label('  IoU       : ' + pct(iou)));

    statusLabel.setValue('✓ Metrics computed for ' + band + '.');
  });
});


// ============================================================
// STARTUP
// ============================================================
refreshLegend();
statusLabel.setValue('Ready. Enter title + year, load classified (and optionally Bhuvan).');