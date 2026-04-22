"""
generate_kml.py
---------------
Generates 2021_flighttracks.kml from all xlsx survey files.
Import the KML into ForeFlight as a map layer:
  Files app (or email) -> tap the .kml file -> Open in ForeFlight

KML notes:
  - Coordinates are lon,lat,alt (KML standard)
  - Colors are AABBGGRR (KML standard, reversed from HTML)
  - altitudeMode = clampToGround so tracks appear on the moving map surface
  - Sites are grouped in Folders so ForeFlight can toggle them individually
"""

import openpyxl, glob, re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

# ── same site-parsing logic as make_track_map.py ──────────────────────────────

NAME_OVERRIDES = {'203': 'Ushagat/SW'}

SKIP_PREFIXES = (
    'TAKE OFF', 'TAKEOFF', 'TEST FIRE', 'LAND', 'KL ', 'ALTITUDE',
    'FRAME CHECK', 'LOW CLOUD', 'SKIPPING', 'SAW GROUP', 'CHECK FRAME',
    'FUEL', 'CLOUDS', 'LAST PASS', 'OBSERVERS', 'PAKT', 'PASI LANDING',
    'ADD ', 'CHECK FOR', 'PREVIOUS', 'ACCIDENTAL', 'COUNTERS', 'ALL ANIMALS',
    'LOOK OUT', 'DISTURBANCE', 'START OF', 'WEST SIDE', 'ANIMALS ON',
    'PASS 1 ', 'PASS 2 ', 'PASS 3 ', 'PASS 4 ', 'PASS 5 ', 'PASS 6 ',
    'PASS 7 ', 'PASS 8 ', 'PASS 9 ', 'PASS 183', 'NEW SITE',
    '1529', 'HIT OUR', '10 JUMPER', '2 JUMPER',
)

_site_labels = {}

def get_site_label(comment):
    c = re.sub(r'^[^A-Za-z0-9]+', '', comment.strip()).strip()
    if re.match(r'^FORRESTER\s+PASS', c, re.IGNORECASE):
        _site_labels.setdefault('FORRESTER', 'Forrester')
        return _site_labels['FORRESTER']
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
    if sid in NAME_OVERRIDES:
        name = NAME_OVERRIDES[sid]
    name = name.title()
    if not name:
        return None
    _site_labels.setdefault(sid, f"{name} ({sid})")
    return _site_labels[sid]

passes_by_site = defaultdict(list)

for filepath in sorted(glob.glob('*.xlsx')):
    date_str = Path(filepath).stem[:8]
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb.active
    current_x = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        type_, lat, lon, comment = row[0], row[4], row[5], row[30]
        if type_ == 'X' and lat and lon:
            current_x.append((float(lat), float(lon)))
        elif type_ == 'C' and comment:
            comment = str(comment).strip()
            if current_x and not comment.upper().startswith(SKIP_PREFIXES):
                label = get_site_label(comment)
                if label:
                    passes_by_site[label].append({
                        'date':    date_str,
                        'comment': comment,
                        'coords':  list(current_x),
                    })
            current_x = []

print(f"Loaded {sum(len(v) for v in passes_by_site.values())} passes "
      f"across {len(passes_by_site)} sites.")

# ── colour palette (matches make_track_map.py) ────────────────────────────────

COLORS_HTML = [
    '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231',
    '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4',
    '#469990', '#dcbeff', '#9a6324', '#800000', '#aaffc3',
    '#808000', '#ffd8b1', '#000075', '#a9a9a9', '#e6beff',
]

def to_kml_color(html, alpha='ff'):
    """Convert #rrggbb → aabbggrr (KML byte order)."""
    h = html.lstrip('#')
    return f"{alpha}{h[4:6]}{h[2:4]}{h[0:2]}"

# ── build KML document ────────────────────────────────────────────────────────

kml = ET.Element('kml', xmlns='http://www.opengis.net/kml/2.2')
doc = ET.SubElement(kml, 'Document')
ET.SubElement(doc, 'name').text = '2021 SSL Aerial Survey Flight Tracks'
ET.SubElement(doc, 'description').text = (
    'Steller sea lion aerial survey flight tracks, 2021. '
    'Each folder is one survey site; each placemark is one camera pass.'
)

# Shared line styles — one per colour slot
for i, html_color in enumerate(COLORS_HTML):
    style = ET.SubElement(doc, 'Style', id=f'color_{i}')
    ls = ET.SubElement(style, 'LineStyle')
    ET.SubElement(ls, 'color').text = to_kml_color(html_color)
    ET.SubElement(ls, 'width').text = '3'
    # Label style (keeps pass labels visible at reasonable zoom)
    label_style = ET.SubElement(style, 'LabelStyle')
    ET.SubElement(label_style, 'scale').text = '0.8'

# One Folder per site, one Placemark per pass
for idx, site in enumerate(sorted(passes_by_site)):
    color_id = f'color_{idx % len(COLORS_HTML)}'

    folder = ET.SubElement(doc, 'Folder')
    ET.SubElement(folder, 'name').text = site

    for pass_num, p in enumerate(passes_by_site[site], 1):
        pm = ET.SubElement(folder, 'Placemark')
        ET.SubElement(pm, 'name').text = f"P{pass_num}"
        ET.SubElement(pm, 'description').text = (
            f"<b>{site}</b> — Pass {pass_num}<br/>"
            f"Date: {p['date']}<br/>"
            f"{p['comment']}"
        )
        ET.SubElement(pm, 'styleUrl').text = f'#{color_id}'

        line = ET.SubElement(pm, 'LineString')
        ET.SubElement(line, 'tessellate').text = '1'
        ET.SubElement(line, 'altitudeMode').text = 'clampToGround'

        # KML coordinate order: longitude,latitude,altitude
        coord_str = '\n'.join(
            f"          {lon},{lat},0"
            for lat, lon in p['coords']
        )
        ET.SubElement(line, 'coordinates').text = '\n' + coord_str + '\n        '

# ── write file ────────────────────────────────────────────────────────────────

raw_xml   = ET.tostring(kml, encoding='unicode')
pretty    = minidom.parseString(raw_xml).toprettyxml(indent='  ')
# minidom adds its own declaration; replace with clean UTF-8 one
clean_xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(pretty.split('\n')[1:])

outfile = '2021_flighttracks.kml'
with open(outfile, 'w', encoding='utf-8') as f:
    f.write(clean_xml)

print(f"Saved: {outfile}")
print(f"\n{'Site':<40} {'Passes':>6}")
print('-' * 48)
for site in sorted(passes_by_site):
    print(f"{site:<40} {len(passes_by_site[site]):>6}")
