"""
generate_kml.py
---------------
Generates KML flight track files for ForeFlight import:
  2021_flighttracks.kml  — GOA 2021 xlsx logs
  2024_flighttracks.kml  — GOA 2024 csv logs
  2022_flighttracks.kml  — ALI 2022 xlsx/csv logs
  2023_flighttracks.kml  — ALI 2023 xlsx/csv logs

Import a KML into ForeFlight:
  Files app (or email) -> tap the .kml file -> Open in ForeFlight

KML notes:
  - Coordinates are lon,lat,alt (KML standard)
  - Colors are AABBGGRR (KML standard, reversed from HTML)
  - altitudeMode = clampToGround so tracks appear on the moving map surface
  - Sites are grouped in Folders so ForeFlight can toggle them individually
"""

import csv
import openpyxl
import glob
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

# ── Shared colour palette ──────────────────────────────────────────────────────

COLORS_HTML = [
    '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231',
    '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4',
    '#469990', '#dcbeff', '#9a6324', '#800000', '#aaffc3',
    '#808000', '#ffd8b1', '#000075', '#a9a9a9', '#e6beff',
]

def to_kml_color(html, alpha='ff'):
    h = html.lstrip('#')
    return f"{alpha}{h[4:6]}{h[2:4]}{h[0:2]}"

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

# ── GOA 2021 site parsing (xlsx, plain numeric IDs) ───────────────────────────

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

# ── GOA 2024 site parsing (csv, NMEA coordinates) ─────────────────────────────

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

# ── ALI site parsing (xlsx+csv, SL-prefixed IDs) ──────────────────────────────

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
    date_str = Path(filepath).stem[:8]
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
                result.append((date_str, str(comment).strip(), list(current_x)))
            current_x = []
    return result

def load_xc_csv_ali(filepath, comment_col=28):
    date_str = Path(filepath).stem[:8]
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
                    result.append((date_str, comment.strip(), list(current_x)))
                current_x = []
    return result

# ── Load GOA 2021 ─────────────────────────────────────────────────────────────

passes_by_site_goa_2021 = defaultdict(list)

for fp in sorted([f for f in glob.glob('flightlogs/**/2021/*.xlsx', recursive=True)
                  if 'LOGSummary' not in f and 'ASSLAP' not in f]):
    for date_str, comment, coords in load_xc_xlsx(fp, comment_col=30):
        if is_operational(comment):
            continue
        label = get_site_label_goa_2021(comment)
        if label:
            passes_by_site_goa_2021[label].append({'date': date_str, 'comment': comment, 'coords': coords})

print(f"GOA 2021: {sum(len(v) for v in passes_by_site_goa_2021.values())} passes across "
      f"{len(passes_by_site_goa_2021)} sites.")

# ── Load GOA 2024 ─────────────────────────────────────────────────────────────

passes_by_site_goa_2024 = defaultdict(list)

for fp in sorted(glob.glob('flightlogs/**/2024/*.csv', recursive=True)):
    m = re.search(r'(\d{4}-\d{2}-\d{2})', fp)
    date_str = m.group(1).replace('-', '') if m else 'unknown'
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
        if not coords:
            continue
        label = get_site_label_goa_2024(site_id, file_names.get(site_id, site_id))
        passes_by_site_goa_2024[label].append({
            'date': date_str,
            'comment': f"{file_names.get(site_id, site_id)} pass {pass_num}",
            'coords': coords,
        })

print(f"GOA 2024: {sum(len(v) for v in passes_by_site_goa_2024.values())} passes across "
      f"{len(passes_by_site_goa_2024)} sites.")

# ── Load ALI 2022 and 2023 ────────────────────────────────────────────────────

def load_ali_year(year_str):
    passes = defaultdict(list)
    for fp in sorted([f for f in glob.glob(f'flightlogs/**/{year_str}/*.xlsx', recursive=True)
                      if 'Aleutian' in f and 'ASSLAP' not in f and 'LOGSummary' not in f]):
        for date_str, comment, coords in load_xc_xlsx(fp, comment_col=30):
            if is_operational(comment):
                continue
            label = get_site_label_ali(comment)
            if label:
                passes[label].append({'date': date_str, 'comment': comment, 'coords': coords})
    for fp in sorted([f for f in glob.glob(f'flightlogs/**/{year_str}/*.csv', recursive=True)
                      if 'Aleutian' in f]):
        for date_str, comment, coords in load_xc_csv_ali(fp, comment_col=28):
            if is_operational(comment):
                continue
            label = get_site_label_ali(comment)
            if label:
                passes[label].append({'date': date_str, 'comment': comment, 'coords': coords})
    print(f"ALI {year_str}: {sum(len(v) for v in passes.values())} passes across {len(passes)} sites.")
    return passes

passes_by_site_ali_2022 = load_ali_year('2022')
passes_by_site_ali_2023 = load_ali_year('2023')

# ── KML builder ───────────────────────────────────────────────────────────────

def build_kml(passes_by_site, title, description):
    kml = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
    doc = ET.SubElement(kml, 'Document')
    ET.SubElement(doc, 'name').text = title
    ET.SubElement(doc, 'description').text = description

    for i, html_color in enumerate(COLORS_HTML):
        style = ET.SubElement(doc, 'Style', id=f'color_{i}')
        ls = ET.SubElement(style, 'LineStyle')
        ET.SubElement(ls, 'color').text = to_kml_color(html_color)
        ET.SubElement(ls, 'width').text = '3'
        label_style = ET.SubElement(style, 'LabelStyle')
        ET.SubElement(label_style, 'scale').text = '0.8'

    for idx, site in enumerate(sorted(passes_by_site)):
        color_id = f'color_{idx % len(COLORS_HTML)}'
        folder = ET.SubElement(doc, 'Folder')
        ET.SubElement(folder, 'name').text = site

        for pass_num, p in enumerate(passes_by_site[site], 1):
            pm = ET.SubElement(folder, 'Placemark')
            ET.SubElement(pm, 'name').text = f"P{pass_num}"
            ET.SubElement(pm, 'description').text = (
                f"<b>{site}</b> - Pass {pass_num}<br/>"
                f"Date: {p['date']}<br/>"
                f"{p['comment']}"
            )
            ET.SubElement(pm, 'styleUrl').text = f'#{color_id}'

            line = ET.SubElement(pm, 'LineString')
            ET.SubElement(line, 'tessellate').text = '1'
            ET.SubElement(line, 'altitudeMode').text = 'clampToGround'

            coord_str = '\n'.join(
                f"          {lon},{lat},0"
                for lat, lon in p['coords']
            )
            ET.SubElement(line, 'coordinates').text = '\n' + coord_str + '\n        '

    return kml

def save_kml(kml_element, outfile):
    raw_xml   = ET.tostring(kml_element, encoding='unicode')
    pretty    = minidom.parseString(raw_xml).toprettyxml(indent='  ')
    clean_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(pretty.split('\n')[1:])
    with open(outfile, 'w', encoding='utf-8') as f:
        f.write(clean_xml)
    print(f"Saved: {outfile}")

# ── Write KML files ───────────────────────────────────────────────────────────

save_kml(build_kml(
    passes_by_site_goa_2021,
    '2021 SSL Aerial Survey Flight Tracks — Gulf of Alaska',
    'Steller sea lion aerial survey flight tracks, Gulf of Alaska 2021. '
    'Each folder is one survey site; each placemark is one camera pass.',
), '2021_flighttracks.kml')

save_kml(build_kml(
    passes_by_site_goa_2024,
    '2024 SSL Aerial Survey Flight Tracks — Gulf of Alaska',
    'Steller sea lion aerial survey flight tracks, Gulf of Alaska 2024. '
    'Each folder is one survey site; each placemark is one camera pass.',
), '2024_flighttracks.kml')

save_kml(build_kml(
    passes_by_site_ali_2022,
    '2022 SSL Aerial Survey Flight Tracks — Aleutian Islands',
    'Steller sea lion aerial survey flight tracks, Aleutian Islands 2022. '
    'Each folder is one survey site; each placemark is one camera pass.',
), '2022_flighttracks.kml')

save_kml(build_kml(
    passes_by_site_ali_2023,
    '2023 SSL Aerial Survey Flight Tracks — Aleutian Islands',
    'Steller sea lion aerial survey flight tracks, Aleutian Islands 2023. '
    'Each folder is one survey site; each placemark is one camera pass.',
), '2023_flighttracks.kml')

# ── Summary table ─────────────────────────────────────────────────────────────

print(f"\n{'Site':<45} {'GOA21':>6} {'GOA24':>6} {'ALI22':>6} {'ALI23':>6}")
print('-' * 71)
all_labels = sorted(
    set(passes_by_site_goa_2021) | set(passes_by_site_goa_2024) |
    set(passes_by_site_ali_2022) | set(passes_by_site_ali_2023)
)
for site in all_labels:
    g21 = len(passes_by_site_goa_2021.get(site, []))
    g24 = len(passes_by_site_goa_2024.get(site, []))
    a22 = len(passes_by_site_ali_2022.get(site, []))
    a23 = len(passes_by_site_ali_2023.get(site, []))
    print(f"{site:<45} {g21 or '':>6} {g24 or '':>6} {a22 or '':>6} {a23 or '':>6}")
