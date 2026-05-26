import fiona
import csv
import numpy as np
from UliEngineering.Math.Coordinates import BoundingBox

# Assuming shapefile is in the same directory
shapefile_path = "ne_10m_admin_1_states_provinces/ne_10m_admin_1_states_provinces.shp"

with fiona.open(shapefile_path) as c:
    with open('india_states_bbox.csv', mode='w', newline='', encoding='utf-8') as bbox_file:

        bbox_writer = csv.writer(bbox_file)
        # Added xmin, ymin, xmax, ymax for easier reading into your scraper
        bbox_writer.writerow(['country', 'state', 'bbox_string', 'xmin', 'ymin', 'xmax', 'ymax'])

        print("STATE_BBOX = {")

        for record in c:
            country = record['properties']['admin']
            
            # 1. FILTER: Only process records where the country is India
            if country == 'India':
                region = record['properties']['name']  # State name
                
                # 2. OPTIMIZED GEOMETRY EXTRACTION
                coordinates = []
                if record['geometry']['type'] == "Polygon":
                    # Extract the outer boundary of the polygon
                    coordinates = record['geometry']['coordinates'][0]
                elif record['geometry']['type'] == "MultiPolygon":
                    # Extract the outer boundary of each polygon within the multipolygon
                    for poly in record['geometry']['coordinates']:
                        coordinates.extend(poly[0])
                else:
                    continue # Skip empty geometries

                # Fiona reads coordinates as (longitude, latitude) which is (x, y)
                # Your Bhuvan scraper needs (xmin, ymin, xmax, ymax) which corresponds to (min_lon, min_lat, max_lon, max_lat)
                # We don't need to flip them for the bounding box logic.
                
                coord_array = np.asarray(coordinates)
                
                # We can calculate min/max directly using numpy, avoiding external library quirks
                xmin = np.min(coord_array[:, 0])
                ymin = np.min(coord_array[:, 1])
                xmax = np.max(coord_array[:, 0])
                ymax = np.max(coord_array[:, 1])

                bbox_str = f"{xmin},{ymin},{xmax},{ymax}"
                
                # Write to CSV
                bbox_writer.writerow([country, region, bbox_str, xmin, ymin, xmax, ymax])

                # Print in a format ready to be pasted into your scraper script
                # Creates a short code key (e.g., "Assam" -> "assam")
                state_key = region.lower().replace(" ", "_")
                print(f'    "{state_key}": ({xmin:.4f}, {ymin:.4f}, {xmax:.4f}, {ymax:.4f}),  # {region}')

        print("}")
        print("\n✅ Successfully extracted Indian states to 'india_states_bbox.csv'")