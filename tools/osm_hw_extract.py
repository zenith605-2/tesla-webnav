"""OSM 에서 고속도로 본선(motorway)·IC/JC·터널·휴게소·요금소 위치를 뽑아 data/osm/hw.json 에 저장 (11/22).
도로공사 구간단속(data/raw/ex_section_utf8.csv)은 좌표 없이 '시설물 이름'만 있어서, 이 자료로 위치를 잡는다.
실행: .venv/bin/python tools/osm_hw_extract.py
"""
import json
from pathlib import Path
import osmium

ROOT = Path(__file__).resolve().parent.parent
PBF = ROOT / 'data/osm/south-korea-latest.osm.pbf'


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.pois = []   # [name, la, lo, kind]
        self.ways = []   # [name, ref, oneway, [[la,lo],...]]

    def node(self, n):
        t = n.tags
        nm = t.get('name')
        if not nm:
            return
        hw = t.get('highway')
        if hw in ('motorway_junction', 'services', 'rest_area', 'toll_gantry') or t.get('barrier') == 'toll_booth':
            self.pois.append([nm, n.location.lat, n.location.lon, hw or 'toll'])

    def way(self, w):
        t = w.tags
        hw = t.get('highway')
        try:
            pts = [[nd.location.lat, nd.location.lon] for nd in w.nodes]
        except Exception:
            return
        if not pts:
            return
        nm = t.get('name') or ''
        if hw in ('motorway', 'trunk') or (hw in ('motorway_link',) and nm):
            if hw in ('motorway', 'trunk'):
                self.ways.append([nm, t.get('ref') or '', t.get('oneway') or '', pts, hw])
            tn = t.get('tunnel:name') or (nm if '터널' in nm else '')
            if t.get('tunnel') and tn:
                self.pois.append([tn, pts[0][0], pts[0][1], 'tunnel_a'])
                self.pois.append([tn, pts[-1][0], pts[-1][1], 'tunnel_b'])
            bn = t.get('bridge:name') or (nm if nm.endswith('교') else '')
            if t.get('bridge') and bn:
                self.pois.append([bn, pts[0][0], pts[0][1], 'bridge_a'])
                self.pois.append([bn, pts[-1][0], pts[-1][1], 'bridge_b'])
        if hw in ('services', 'rest_area') and nm:
            m = pts[len(pts) // 2]
            self.pois.append([nm, m[0], m[1], hw])


h = H()
h.apply_file(str(PBF), locations=True)
out = ROOT / 'data/osm/hw.json'
json.dump({'pois': h.pois, 'ways': [w for w in h.ways if w[4] == 'motorway' or w[0].endswith('고속도로')]}, open(out, 'w'), ensure_ascii=False)
print('pois', len(h.pois), 'ways', len(h.ways), out)
