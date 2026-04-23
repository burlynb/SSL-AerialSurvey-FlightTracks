"""
generate_site_photos.py
-----------------------
Generates satellite-imagery PNG thumbnails for each survey site.

  GOA 2021 (xlsx)  -> photos/2021/<site label>.png
  GOA 2024 (csv)   -> photos/2024/<site label>.png
  ALI 2022 (xlsx+csv) -> photos/2022/<site label>.png
  ALI 2023 (xlsx+csv) -> photos/2023/<site label>.png

Safe to rerun — skips files that already exist.
Tile source: Esri World Imagery (no API key required).
Dependencies: openpyxl, requests, Pillow
"""

import csv
import math
import time
import re
import glob
import openpyxl
import requests
from PIL import Image, ImageDraw
from io import BytesIO
from pathlib import Path
from collections import defaultdict

# ── Shared skip logic ──────────────────────────────────────────────────────────

SKIP_PREFIXES = (
    'TAKE OFF', 'TAKEOFF', 'TEST FIRE', 'LAND', 'KL ', 'ALTITUDE',
    'FRAME CHECK', 'LOW CLOUD', 'SKIPPING', 'SAW GROUP', 'CHECK FRAME',
    'FUEL', 'CLOUDS', 'LAST PASS', 'OBSERVERS', 'PAKT', 'PASI LANDING',
    'ADD ', 'CHECK FOR', 'PREVIOUS', 'ACCIDENTAL', 'COUNTERS', 'ALL ANIMALS',
    'LOOK OUT', 'DISTURBANCE', 'START OF', 'WEST SIDE', 'ANIMALS ON',
    'PASS 1 ', 'PASS 2 ', 'PASS 3 ', 'PASS 4 ', 'PASS 5 ', 'PASS 6 ',
    'PASS 7 ', 'PASS 8 ', 'PASS 9 ', 'PASS 183', 'NEW SITE',
    '1529', 'HIT OUR', '10 JUMPER', '2 JUMPER',
    'PORT -', 'STAR -', 'BB ', 'REFORMATTED', 'SET APERTURE',
    'DISREGARD', 'NO OPENING', 'SILVER BOX', 'PHOTO PASS OF',
)

def is_operational(comment):
    return comment.upper().strip().startswith(SKIP_PREFIXES)

# ── GOA 2021 site-name logic ───────────────────────────────────────────────────

NAME_OVERRIDES_GOA = {'203': 'Ushagat/SW'}

_labels_goa_2021 = {}

def get_site_label_goa_2021(comment):
    c = re.sub(r'^[^A-Za-z0-9]+', '', comment.strip()).strip()
    if re.match(r'^FORRESTER\s+PASS', c, re.IGNORECASE):
        _labels_goa_2021.setdefault('FORRESTER', 'Forrester')
        return _labels_goa_2021['FORRESTER']
    m = re.match(
        r'^(?:SSL?)?(\d+)[A-Z]?\s+(.+?)'
        r'(?:\s+(?:PASS|ABORTED|ONE\s+PASS|NO\s+ANIMALS|OBSV|VISUAL|PHOTO|PASS\s+ONE)'
        r'|\s*[-–]\s*|\s*$)',
        c, re.IGNORECASE
    )
    if not m:
        return None
    sid  = m.group(1)
    name = m.group(2).strip()
    name = re.sub(r'\s+[A-Z]\s+(?:TO|AND)\s+[A-Z]\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+[A-Z]\s*$', '', name).strip()
    name = re.sub(r'\s+\d+\s*$', '', name).strip()
    if sid in NAME_OVERRIDES_GOA:
        name = NAME_OVERRIDES_GOA[sid]
    else:
        name = name.title()
    if not name:
        return None
    _labels_goa_2021.setdefault(sid, f"{name} ({sid})")
    return _labels_goa_2021[sid]

# ── GOA 2024 site-name logic ───────────────────────────────────────────────────

def nmea_to_dd(val, hemisphere):
    v = float(val)
    deg = int(v / 100)
    dd = deg + (v - deg * 100) / 60.0
    if hemisphere.upper() in ('S', 'W'):
        dd = -dd
    return dd

_labels_goa_2024 = {}

def get_site_label_goa_2024(site_id_raw, site_name_raw):
    m = re.match(r'(\d+)', str(site_id_raw).strip())
    parent_id = m.group(1) if m else str(site_id_raw).strip()
    if parent_id in _labels_goa_2024:
        return _labels_goa_2024[parent_id]
    if parent_id in NAME_OVERRIDES_GOA:
        name = NAME_OVERRIDES_GOA[parent_id]
    else:
        name = str(site_name_raw).strip()
        name = re.sub(r'\s+[A-Za-z]\s+to\s+[A-Za-z]\s*$', '', name, flags=re.IGNORECASE).strip()
        name = re.sub(r'/[A-Za-z]\s*$', '', name).strip().strip('/')
        name = name.title()
    label = f"{name} ({parent_id})"
    _labels_goa_2024[parent_id] = label
    return label

# ── ALI (2022/2023) site-name logic ───────────────────────────────────────────

_labels_ali = {}

def get_site_label_ali(comment):
    c = re.sub(r'^[^A-Za-z0-9]+', '', comment.strip()).strip()
    m = re.match(
        r'^(?:SL?)?(\d+)[A-Za-z]?\s+(.+?)'
        r'(?:\s+(?:PASS|ABORTED|ONE\s+PASS|NO\s+ANIMALS|\d+\s+ANIMALS?|OBSV|VISUAL|'
        r'PHOTO|PASS\s+ONE|FIRST\s+PHOTO|TOOK\b|COMMENT\b)'
        r'|\s*[-–;]\s*|\s*$)',
        c, re.IGNORECASE
    )
    if not m:
        return None
    sid  = m.group(1)
    name = m.group(2).strip()
    name = re.sub(r'^TO\s+(?:SL?)?\d*[A-Za-z]?\s*', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+(?:ADD|COUNT|GOT\s+THEM|WILL\s+DROP)\b.*', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+TO\s+HS\d+.*', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+[A-Z]\s+(?:TO|AND)\s+[A-Z]\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+[A-Z]\s*$', '', name).strip()
    name = re.sub(r'\s+\d+\s*$', '', name).strip()
    name = re.sub(r'\s+ANIMALS?\s*$', '', name, flags=re.IGNORECASE).strip()
    name = name.title()
    if not name or len(name) < 2:
        return None
    _labels_ali.setdefault(sid, f"{name} ({sid})")
    return _labels_ali[sid]

# ── Generic X/C-row loaders ────────────────────────────────────────────────────

def load_xc_xlsx(filepath, comment_col=30):
    result = []
    current_x = []
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    for row in ws.iter_rows(min_row=2, values_only=True):
        t, lat, lon = row[0], row[4], row[5]
        comment = row[comment_col] if len(row) > comment_col else None
        if t == 'X' and lat and lon:
            try:
                current_x.append((float(lat), float(lon)))
            except (TypeError, ValueError):
                pass
        elif t == 'C':
            if comment and current_x:
                result.append((str(comment).strip(), list(current_x)))
            current_x = []
    return result

def load_xc_csv(filepath, comment_col=28):
    result = []
    current_x = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if not row:
                continue
            t = row[0]
            lat_raw = row[4] if len(row) > 4 else ''
            lon_raw = row[5] if len(row) > 5 else ''
            comment = row[comment_col] if len(row) > comment_col else ''
            if t == 'X' and lat_raw and lon_raw:
                try:
                    current_x.append((float(lat_raw), float(lon_raw)))
                except (TypeError, ValueError):
                    pass
            elif t == 'C':
                if comment and current_x:
                    result.append((comment.strip(), list(current_x)))
                current_x = []
    return result

# ── Load passes ────────────────────────────────────────────────────────────────

passes_by_site_goa_2021 = defaultdict(list)
for fp in sorted([f for f in glob.glob('flightlogs/**/2021/*.xlsx', recursive=True)
                  if 'LOGSummary' not in f and 'ASSLAP' not in f]):
    for comment, coords in load_xc_xlsx(fp, comment_col=30):
        if is_operational(comment):
            continue
        label = get_site_label_goa_2021(comment)
        if label:
            passes_by_site_goa_2021[label].append(coords)

passes_by_site_goa_2024 = defaultdict(list)
for fp in sorted(glob.glob('flightlogs/**/2024/*.csv', recursive=True)):
    file_passes = defaultdict(list)
    file_names  = {}
    with open(fp, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if len(row) < 31 or row[0] != '$X':
                continue
            site_name = row[29].strip(); site_id = row[27].strip(); pass_num = row[30].strip()
            if not (site_name and site_id):
                continue
            try:
                lat = nmea_to_dd(row[6], row[7]); lon = nmea_to_dd(row[8], row[9])
            except (ValueError, ZeroDivisionError):
                continue
            file_passes[(site_id, pass_num)].append((lat, lon))
            file_names.setdefault(site_id, site_name)
    for (site_id, pass_num), coords in file_passes.items():
        if coords:
            label = get_site_label_goa_2024(site_id, file_names.get(site_id, site_id))
            passes_by_site_goa_2024[label].append(coords)

def load_ali_passes(year_str):
    passes = defaultdict(list)
    for fp in sorted([f for f in glob.glob(f'flightlogs/**/{year_str}/*.xlsx', recursive=True)
                      if 'Aleutian' in f and 'ASSLAP' not in f and 'LOGSummary' not in f]):
        for comment, coords in load_xc_xlsx(fp, comment_col=30):
            if is_operational(comment):
                continue
            label = get_site_label_ali(comment)
            if label:
                passes[label].append(coords)
    for fp in sorted([f for f in glob.glob(f'flightlogs/**/{year_str}/*.csv', recursive=True)
                      if 'Aleutian' in f]):
        for comment, coords in load_xc_csv(fp, comment_col=28):
            if is_operational(comment):
                continue
            label = get_site_label_ali(comment)
            if label:
                passes[label].append(coords)
    return passes

passes_by_site_ali_2022 = load_ali_passes('2022')
passes_by_site_ali_2023 = load_ali_passes('2023')

print(f"Loaded: GOA 2021={len(passes_by_site_goa_2021)}, GOA 2024={len(passes_by_site_goa_2024)}, "
      f"ALI 2022={len(passes_by_site_ali_2022)}, ALI 2023={len(passes_by_site_ali_2023)} sites.")

# ── Tile utilities ─────────────────────────────────────────────────────────────

TILE_SIZE = 256
ESRI_URL  = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
SESSION   = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; site-photo-generator)'})

def deg_to_tile_float(lat, lon, zoom):
    lat_r = math.radians(lat)
    n = 2.0 ** zoom
    tx = (lon + 180.0) / 360.0 * n
    ty = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return tx, ty

def fetch_tile(z, x, y, retries=3, timeout=(5, 10)):
    url = ESRI_URL.format(z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=timeout)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert('RGB')
        except Exception as e:
            if attempt == retries - 1:
                print(f"    Tile fetch failed ({z}/{x}/{y}): {e}")
                return Image.new('RGB', (TILE_SIZE, TILE_SIZE), (40, 40, 40))
            time.sleep(1)

def best_zoom(min_lat, max_lat, min_lon, max_lon, max_tiles=20):
    for zoom in range(15, 7, -1):
        tx0f, ty1f = deg_to_tile_float(max_lat, min_lon, zoom)
        tx1f, ty0f = deg_to_tile_float(min_lat, max_lon, zoom)
        nx = int(tx1f) - int(tx0f) + 1
        ny = int(ty1f) - int(ty0f) + 1
        if nx * ny <= max_tiles:
            return zoom
    return 8

COLORS_HEX = [
    '#e6194b','#3cb44b','#ffe119','#4363d8','#f58231',
    '#911eb4','#42d4f4','#f032e6','#bfef45','#fabed4',
    '#469990','#dcbeff','#9a6324','#800000','#aaffc3',
]

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

COLORS_RGB = [hex_to_rgb(c) for c in COLORS_HEX]

PAD = 0.25

def generate_photo(label, all_passes, output_path):
    all_passes = [list(p) for p in all_passes]
    all_coords = [c for p in all_passes for c in p]
    lats = [c[0] for c in all_coords]
    lons = [c[1] for c in all_coords]
    # Antimeridian normalization: if lon span > 180°, GPS sign flip near antimeridian.
    # All survey sites are in western hemisphere, so negate any erroneously positive lons.
    if max(lons) - min(lons) > 180:
        lons = [-l if l > 0 else l for l in lons]
        all_passes = [[(lat, -lon if lon > 0 else lon) for lat, lon in p] for p in all_passes]
    lat_span = max(lats) - min(lats) or 0.002
    lon_span = max(lons) - min(lons) or 0.003
    min_lat = min(lats) - lat_span * PAD
    max_lat = max(lats) + lat_span * PAD
    min_lon = min(lons) - lon_span * PAD
    max_lon = max(lons) + lon_span * PAD
    zoom = best_zoom(min_lat, max_lat, min_lon, max_lon)
    tx0f, ty0f = deg_to_tile_float(max_lat, min_lon, zoom)
    tx1f, ty1f = deg_to_tile_float(min_lat, max_lon, zoom)
    tx0, ty0 = int(tx0f), int(ty0f)
    tx1, ty1 = int(tx1f), int(ty1f)
    nx = tx1 - tx0 + 1
    ny = ty1 - ty0 + 1
    canvas = Image.new('RGB', (nx * TILE_SIZE, ny * TILE_SIZE))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = fetch_tile(zoom, tx, ty)
            canvas.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
            time.sleep(0.05)

    def to_px(lat, lon):
        txf, tyf = deg_to_tile_float(lat, lon, zoom)
        return int((txf - tx0) * TILE_SIZE), int((tyf - ty0) * TILE_SIZE)

    draw = ImageDraw.Draw(canvas)
    for pi, pass_coords in enumerate(all_passes):
        color = COLORS_RGB[pi % len(COLORS_RGB)]
        pixels = [to_px(lat, lon) for lat, lon in pass_coords]
        if len(pixels) < 2:
            continue
        draw.line(pixels, fill=color, width=3)
        sx, sy = pixels[0]; r = 5
        draw.ellipse([sx-r, sy-r, sx+r, sy+r], fill=color, outline='white', width=1)
        ex, ey = pixels[-1]
        draw.ellipse([ex-r, ey-r, ex+r, ey+r], fill='white', outline=color, width=2)
        draw.text((sx + r + 2, sy - 7), f"P{pi+1}", fill=color)

    px_min, py_min = to_px(max_lat, min_lon)
    px_max, py_max = to_px(min_lat, max_lon)
    px_min = max(0, px_min); py_min = max(0, py_min)
    px_max = min(canvas.width, px_max); py_max = min(canvas.height, py_max)
    canvas = canvas.crop((px_min, py_min, px_max, py_max))
    banner_h = 24
    banner = Image.new('RGB', (canvas.width, banner_h), (30, 30, 30))
    ImageDraw.Draw(banner).text((6, 4), label, fill='white')
    final = Image.new('RGB', (canvas.width, canvas.height + banner_h))
    final.paste(banner, (0, 0))
    final.paste(canvas, (0, banner_h))
    final.save(output_path)

def safe_filename(label):
    return re.sub(r'[\\/:*?"<>|]', '_', label) + '.png'

# ── Main loop ──────────────────────────────────────────────────────────────────

for year, passes_by_site, photo_dir in [
    ('2021', passes_by_site_goa_2021, Path('photos/2021')),
    ('2024', passes_by_site_goa_2024, Path('photos/2024')),
    ('2022', passes_by_site_ali_2022, Path('photos/2022')),
    ('2023', passes_by_site_ali_2023, Path('photos/2023')),
]:
    photo_dir.mkdir(parents=True, exist_ok=True)
    sites = sorted(passes_by_site.keys())
    print(f"\nGenerating {year} photos for {len(sites)} sites...")
    for label in sites:
        fname   = safe_filename(label)
        outpath = photo_dir / fname
        if outpath.exists():
            print(f"  Skipping {outpath} (already exists)")
            continue
        print(f"  {label} -> {outpath} ...", end=' ', flush=True)
        try:
            generate_photo(label, passes_by_site[label], outpath)
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")

print("\nDone. Run make_track_map.py to rebuild the HTML.")
