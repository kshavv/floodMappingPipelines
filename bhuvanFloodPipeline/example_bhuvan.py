"""Example: build the Kharif Bhuvan flood stack for Kerala 2023.

Output: one multi-band GeoTIFF
    bhuvan_kharif_kerala_2023.tif
with 140 bands (Jun 1 → Oct 4 inclusive), each band a uint8 0/1 flood
mask. Band descriptions are ISO dates. Days without Bhuvan data are
all-zero bands.
"""
from bhuvan_flood import download_bhuvan_kharif_stack

result = download_bhuvan_kharif_stack(
    state='Kerala',
    year=2023,
    output_path='./bhuvan_kharif_kerala_2023.tif',
)

print()
print('State              :', result['state'])
print('Year               :', result['year'])
print('Output             :', result['output_path'])
print('Bands              :', result['n_bands'])
print('Days with Bhuvan   :', result['n_days_with_data'])
print('Days without data  :', len(result['days_without']))
print('BBox (W,S,E,N)     :', result['bbox'])

# Batching over years:
# for yr in [2018, 2019, 2020, 2021, 2022, 2023, 2024]:
#     download_bhuvan_kharif_stack(
#         state='Kerala', year=yr,
#         output_path=f'./bhuvan_kharif_kerala_{yr}.tif',
#     )
