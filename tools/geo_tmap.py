"""단속카메라 방향 설명(A→B)의 지명 중 오픈스트리트맵에 없는 것(아파트·건물 등)을 티맵 장소 검색으로 찾는다 (11/22).

입력: data/osm/tmap_need.json  ['지명|위도0.1|경도0.1', ...]  (build_cam_dir.py 가 만듦)
출력: data/osm/tmap_geo.json   {'지명|위도0.1|경도0.1': [위도, 경도] 또는 None}  (gitignore, 방향 계산에만 쓰고 공개 안 함)
조건: 카메라 근처(0.1° 칸 가운데에서 10km 안) 결과만, 하루 한도 아끼려고 1초에 5건, 중간 저장.
사용: python3 tools/geo_tmap.py [최대건수]
"""
import json, sys, time, urllib.parse, urllib.request, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
KEY = (ROOT / '.tmap_key').read_text().strip()
NEED = json.load(open(ROOT / 'data/osm/tmap_need.json'))
OUT = ROOT / 'data/osm/tmap_geo.json'
TG = json.load(open(OUT)) if OUT.exists() else {}
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 9000


def dkm(a, b, c, d):
    x = (d - b) * math.cos(math.radians((a + c) / 2)) * 111.32
    return math.hypot(x, (c - a) * 111.32)


n = hit = 0
for k in NEED:
    if k in TG:
        continue
    if n >= MAX:
        break
    name, la, lo = k.rsplit('|', 2)
    la, lo = float(la), float(lo)
    q = urllib.parse.urlencode({'version': 1, 'searchKeyword': name, 'centerLat': la, 'centerLon': lo,
                                'radius': 10, 'count': 3, 'searchtypCd': 'R', 'reqCoordType': 'WGS84GEO', 'resCoordType': 'WGS84GEO'})
    try:
        req = urllib.request.Request('https://apis.openapi.sk.com/tmap/pois?' + q, headers={'appKey': KEY, 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
        pois = ((json.loads(body) if body else {}).get('searchPoiInfo') or {}).get('pois', {}).get('poi', []) if body else []
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print('한도', n); break
        pois = []
    except Exception as e:
        print('오류', k, e); time.sleep(2); continue
    best = None
    for p in pois:
        try:
            pla, plo = float(p.get('frontLat') or p['noorLat']), float(p.get('frontLon') or p['noorLon'])
        except (KeyError, ValueError, TypeError):
            continue
        if dkm(la, lo, pla, plo) < 10:
            best = [round(pla, 5), round(plo, 5)]
            break
    TG[k] = best
    n += 1
    hit += bool(best)
    if n % 200 == 0:
        OUT.write_text(json.dumps(TG, ensure_ascii=False))
        print(n, '건, 찾음', hit, flush=True)
    time.sleep(0.2)
OUT.write_text(json.dumps(TG, ensure_ascii=False))
print('끝', n, '건, 찾음', hit)
