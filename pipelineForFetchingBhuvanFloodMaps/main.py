import os
import math
import requests
import processing
from qgis.core import *
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry

# ==========================================
# 1. PIPELINE CONFIGURATION
# ==========================================
STATE_CODE = "as"                  # e.g., "as" for Assam, "kl" for Kerala
DATE_STR = "2023_16_06_18"         # e.g., "2023_16_06_18"

# Output Paths
OUTPUT_DIR = r"C:\Users\DELL\Desktop\ICTD_MTP_PROJECT\BhuvanScrapper\flood_tiles"
FINAL_OUTPUT = r"C:\Users\DELL\Desktop\ICTD_MTP_PROJECT\output\final_flood_map.tif"

# Define State Bounding Boxes (EPSG:4326) -> (xmin, ymin, xmax, ymax)
# You can expand this dictionary for all required states
STATE_BBOX = {
    "as": (89.68, 24.13, 96.01, 27.97),
    "kl": (74.85, 8.28, 77.45, 12.79)
}

TILE_SIZE = 0.087890625  # Standard degree size derived from the Bhuvan Zoom Level 11/12 grid
# ==========================================

def write_world_file(wld_path, bbox, width=256, height=256):
    """Generates the .wld georeferencing file for the downloaded PNG."""
    xmin, ymin, xmax, ymax = bbox
    pixel_x_size = (xmax - xmin) / width
    pixel_y_size = (ymin - ymax) / height
    with open(wld_path, "w") as f:
        f.write(f"{pixel_x_size}\n0.0\n0.0\n{pixel_y_size}\n{xmin}\n{ymax}\n")

def download_bhuvan_grid(state_code, date_str, output_dir):
    """Programmatically generates WMS URLs and downloads the state tile grid."""
    if state_code not in STATE_BBOX:
        raise ValueError(f"Bounding box for state '{state_code}' not defined.")
        
    xmin, ymin, xmax, ymax = STATE_BBOX[state_code]
    layer_name = f"flood:{state_code}_{date_str}"
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Clean up existing files in the output directory
    for filename in os.listdir(output_dir):
        os.remove(os.path.join(output_dir, filename))
        
    # Align grid to the tile size
    start_x = math.floor(xmin / TILE_SIZE) * TILE_SIZE
    start_y = math.floor(ymin / TILE_SIZE) * TILE_SIZE
    
    print(f"Scraping Bhuvan WMS for Layer: {layer_name}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://bhuvan-app1.nrsc.gov.in/"
    }
    
    curr_x = start_x
    tile_count = 0
    
    while curr_x < xmax:
        curr_y = start_y
        while curr_y < ymax:
            tile_bbox = (curr_x, curr_y, curr_x + TILE_SIZE, curr_y + TILE_SIZE)
            bbox_str = f"{curr_x},{curr_y},{curr_x + TILE_SIZE},{curr_y + TILE_SIZE}"
            
            # Dynamically construct the WMS API Call
            url = (
                f"https://bhuvan-gp1.nrsc.gov.in/bhuvan/gwc/service/wms"
                f"?LAYERS={layer_name}&TRANSPARENT=TRUE&SERVICE=WMS&VERSION=1.1.1"
                f"&REQUEST=GetMap&STYLES=&FORMAT=image%2Fpng&SRS=EPSG%3A4326"
                f"&BBOX={bbox_str}&WIDTH=256&HEIGHT=256"
            )
            
            try:
                response = requests.get(url, headers=headers, timeout=10)
                
                # Filter out blank/empty tiles to save processing power (empty tiles are usually <1KB)
                if response.status_code == 200 and len(response.content) > 1000: 
                    image_name = f"tile_{state_code}_{date_str}_{tile_count:04d}"
                    image_path = os.path.join(output_dir, image_name + ".png")
                    wld_path = os.path.join(output_dir, image_name + ".wld")
                    
                    with open(image_path, "wb") as f:
                        f.write(response.content)
                    write_world_file(wld_path, tile_bbox)
                    
                    tile_count += 1
            except Exception as e:
                print(f"Failed to download {bbox_str}: {e}")
                
            curr_y += TILE_SIZE
        curr_x += TILE_SIZE
        
    print(f"✅ Download complete. {tile_count} data-rich tiles saved.")
    return tile_count > 0

def process_flood_map(output_dir, final_output):
    """Merges downloaded tiles and applies the flood raster calculation."""
    print("Starting QGIS Processing...")
    
    # 1. Load raster layers
    raster_layers = []
    for filename in os.listdir(output_dir):
        if filename.lower().endswith(".png") or filename.lower().endswith(".tif"):
            filepath = os.path.join(output_dir, filename)
            layer = QgsRasterLayer(filepath, filename)
            if layer.isValid():
                raster_layers.append(layer)
                
    if not raster_layers:
        raise Exception("No valid raster layers found for processing.")
        
    print(f"Merging {len(raster_layers)} tiles...")
    
    # 2. Merge using QGIS processing framework
    merge_params = {
        'INPUT': raster_layers,
        'PCT': False,
        'SEPARATE': False,
        'NODATA_INPUT': None,
        'NODATA_OUTPUT': None,
        'OPTIONS': '',
        'EXTRA': '',
        'DATA_TYPE': 0,
        'OUTPUT': 'TEMPORARY_OUTPUT'
    }
    merged_result = processing.run("gdal:merge", merge_params)
    merged_layer = QgsRasterLayer(merged_result['OUTPUT'], "merged_alias")
    
    if not merged_layer.isValid():
        raise Exception("Merged raster could not be loaded!")

    # 3. Apply Raster Calculator Filter
    print("Applying Raster Calculator filter...")
    entries = []
    for i in range(1, 5):
        entry = QgsRasterCalculatorEntry()
        entry.ref = f'ml@{i}'
        entry.raster = merged_layer
        entry.bandNumber = i
        entries.append(entry)

    # Insert your specific flood-filtering expression here:
    expression = "((ml@1 = 0) AND (ml@2 = 255) AND (ml@3 = 255))"
    
    calc = QgsRasterCalculator(
        expression,
        final_output,
        'GTiff',
        merged_layer.extent(),
        merged_layer.width(),
        merged_layer.height(),
        entries
    )
    
    result = calc.processCalculation()
    if result == 0:
        print(f"✅ Final flood map successfully saved to: {final_output}")
    else:
        print("❌ Raster calculation failed.")

if __name__ == '__main__':
    # Execute the automated pipeline
    has_tiles = download_bhuvan_grid(STATE_CODE, DATE_STR, OUTPUT_DIR)
    
    if has_tiles:
        process_flood_map(OUTPUT_DIR, FINAL_OUTPUT)
    else:
        print("Pipeline aborted: No data returned from Bhuvan for the specified parameters.")