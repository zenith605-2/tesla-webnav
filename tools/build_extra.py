"""과속방지턱 + 슈퍼차저·휴게소·졸음쉼터 -> 웹 내비용 가벼운 JSON.

받기(키 없음):
  과속방지턱: 국토부 전국과속방지턱표준데이터 data.go.kr 15028195 (위경도 그대로)
              + OpenStreetMap traffic_calming=bump/hump/table (공공데이터에 없는 지역 보충)
  슈퍼차저·휴게소·졸음쉼터: OpenStreetMap (Overpass API)
출력 (지정한 폴더에):
  bumps.json  [[위도, 경도], ...]
  pois.json   {"sc": [[위도, 경도, 이름, 충전기 수]], "rest": [[위도, 경도, 이름, 종류]]}
              종류: 'S' 휴게소, 'R' 졸음쉼터·쉼터
  extra-ver.json  {"ver", "bumps", "sc", "rest"}
사용: python tools/build_extra.py docs        (받고 만들기)
      python tools/build_extra.py docs --cached (data/ 에 받아 둔 것으로만 만들기)
"""
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / 'data/raw'
OSM = ROOT / 'data/osm'
UA = {'User-Agent': 'Mozilla/5.0 (webnav-data)'}
OVERPASS = 'https://overpass-api.de/api/interpreter'
SC_NAMES = json.load(open(ROOT / 'tools/sc_names.json', encoding='utf-8')) if (ROOT / 'tools/sc_names.json').exists() else {}  # 슈퍼차저 한글 이름(티맵 역지오코딩으로 한 번 만듦)
KR = 'area["ISO3166-1"="KR"][admin_level=2]->.k;'


def get_json(url, headers=None, data=None, timeout=240):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_bumps_public():
    pk, base = '15028195', 'https://www.data.go.kr'
    h = {'Referer': f'{base}/data/{pk}/standard.do', 'X-Requested-With': 'XMLHttpRequest'}
    col = get_json(f'{base}/download/columList.json?pk={pk}&ext=JSON', h)
    t, total, rows = col['tableVO'], int(col['totalCount']), []
    for page in range(1, total // 10000 + 2):
        q = [('colNmList', c) for c in t['colNmList']] + [
            ('totalCount', total), ('svcTableNm', t['svcTableNm']), ('perPage', 10000), ('page', page)]
        d = get_json(f'{base}/download/standard.json?publicDataPk={pk}&' + urllib.parse.urlencode(q), h)
        rows += d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
        time.sleep(1)
    if len(rows) < total * 0.95:
        raise SystemExit(f'과속방지턱 행이 너무 적음: {len(rows)} / {total}')
    return rows


def fetch_standard(pk):
    base = 'https://www.data.go.kr'
    h = {'Referer': f'{base}/data/{pk}/standard.do', 'X-Requested-With': 'XMLHttpRequest'}
    col = get_json(f'{base}/download/columList.json?pk={pk}&ext=JSON', h)
    t, total, rows = col['tableVO'], int(col['totalCount']), []
    for page in range(1, total // 10000 + 2):
        q = [('colNmList', c) for c in t['colNmList']] + [
            ('totalCount', total), ('svcTableNm', t['svcTableNm']), ('perPage', 10000), ('page', page)]
        d = get_json(f'{base}/download/standard.json?publicDataPk={pk}&' + urllib.parse.urlencode(q), h)
        rows += d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
        time.sleep(1)
    if len(rows) < total * 0.95:
        raise SystemExit(f'{pk} 행이 너무 적음: {len(rows)} / {total}')
    return rows


def overpass(q):
    for i in range(3):
        try:
            return get_json(OVERPASS, data=urllib.parse.urlencode({'data': q}).encode())
        except Exception as e:  # 서버가 바쁘면 잠깐 쉬고 다시
            print('overpass 재시도', i + 1, e)
            time.sleep(30)
    raise SystemExit('overpass 실패')


def fetch_all():
    RAW.mkdir(parents=True, exist_ok=True)
    OSM.mkdir(parents=True, exist_ok=True)
    (RAW / 'bumps_all.json').write_text(json.dumps(fetch_bumps_public(), ensure_ascii=False), encoding='utf-8')
    # 교통사고 다발지역 표준데이터(도로교통공단, data.go.kr 15029185)
    (RAW / 'accidents_all.json').write_text(json.dumps(fetch_standard('15029185'), ensure_ascii=False), encoding='utf-8')
    c = overpass('[out:json][timeout:180];' + KR +
                 '(node["traffic_calming"~"^(bump|hump|table|yes)$"](area.k););out skel;')
    (OSM / 'calming.json').write_text(json.dumps(c), encoding='utf-8')
    p = overpass('[out:json][timeout:180];' + KR +
                 '(nwr["amenity"="charging_station"]["brand"~"Tesla",i](area.k);'
                 'nwr["amenity"="charging_station"]["operator"~"Tesla|테슬라",i](area.k);'
                 'nwr["amenity"="charging_station"]["name"~"Supercharger|슈퍼차저|수퍼차저",i](area.k);'
                 'nwr["highway"~"^(services|rest_area)$"](area.k););out center tags;')
    (OSM / 'pois.json').write_text(json.dumps(p, ensure_ascii=False), encoding='utf-8')
    # 슈퍼차저: supercharge.info 커뮤니티 DB (한국 운영 중 185곳, 충전기 수·kW). OSM 은 이름(한글) 보충용
    sc = get_json('https://supercharge.info/service/supercharge/allSites', timeout=120)
    kr = [x for x in sc if (x.get('address') or {}).get('country') == 'South Korea']
    (RAW / 'superchargers_kr.json').write_text(json.dumps(kr, ensure_ascii=False), encoding='utf-8')


def ll(e):
    if 'lat' in e:
        return e['lat'], e['lon']
    c = e.get('center') or {}
    return c.get('lat'), c.get('lon')


def build(out_dir):
    out_dir = Path(out_dir)
    # 과속방지턱: 공공데이터 먼저, OSM 은 약 15m 안에 이미 있으면 뺀다
    bumps, cells = [], set()

    def add(la, lo):
        if not (33 < la < 39 and 124 < lo < 132):
            return
        cx, cy = round(la / 0.00015), round(lo / 0.00018)
        if any((cx + a, cy + b) in cells for a in (-1, 0, 1) for b in (-1, 0, 1)):
            return
        cells.add((cx, cy))
        bumps.append([round(la, 5), round(lo, 5)])

    pub = json.load(open(RAW / 'bumps_all.json', encoding='utf-8'))
    for x in pub:
        try:
            add(float(x['LATITUDE']), float(x['LONGITUDE']))
        except (ValueError, TypeError):
            pass
    n_pub = len(bumps)
    for e in json.load(open(OSM / 'calming.json'))['elements']:
        add(e['lat'], e['lon'])
    bumps.sort()

    sc, rest = [], []
    for e in json.load(open(OSM / 'pois.json', encoding='utf-8'))['elements']:
        t, (la, lo) = e.get('tags', {}), ll(e)
        if la is None:
            continue
        name = (t.get('name:ko') or t.get('name') or '').strip()
        if t.get('amenity') == 'charging_station':
            tesla = 'tesla' in (t.get('brand', '') + t.get('operator', '') + name).lower() or '테슬라' in name
            if not tesla or '주유소' in name:
                continue
            if not name or name.lower() == 'tesla supercharger':
                name = '테슬라 슈퍼차저'
            n = t.get('capacity', '')
            sc.append([round(la, 5), round(lo, 5), name.replace('수퍼차저', '슈퍼차저'), int(n) if n.isdigit() else 0])
        elif t.get('highway') == 'services':
            if not name or ('주유소' in name and '휴게소' not in name):
                continue
            rest.append([round(la, 5), round(lo, 5), name, 'S'])
        elif t.get('highway') == 'rest_area':
            if '졸음쉼터' in name:
                rest.append([round(la, 5), round(lo, 5), name, 'R'])
            elif '휴게소' in name and len(name) > 3:
                rest.append([round(la, 5), round(lo, 5), name, 'S'])
    # 같은 휴게소가 점·면으로 두 번 들어온 것 정리 (이름 같고 300m 안)
    dedup = []
    for r in rest:
        if any(r[2] == q[2] and abs(r[0] - q[0]) < 0.003 and abs(r[1] - q[1]) < 0.003 for q in dedup):
            continue
        dedup.append(r)
    rest = dedup
    # 슈퍼차저는 supercharge.info 가 있으면 그것으로 (OSM 한글 이름을 300m 안이면 빌려 씀)
    sci = RAW / 'superchargers_kr.json'
    if sci.exists():
        osm_sc, sc = sc, []
        for x in json.load(open(sci, encoding='utf-8')):
            if x.get('status') not in ('OPEN', 'CONSTRUCTION'):
                continue
            la, lo = x['gps']['latitude'], x['gps']['longitude']
            near = [o for o in osm_sc if abs(o[0] - la) < 0.003 and abs(o[1] - lo) < 0.004 and o[2] != '테슬라 슈퍼차저']
            ad = x.get('address') or {}
            rs = [r for r in rest if abs(r[0] - la) < 0.0036 and abs(r[1] - lo) < 0.0045]
            name = (near[0][2] if near else ('테슬라 슈퍼차저 · ' + rs[0][2]) if rs
                    else SC_NAMES.get(str(x['id'])) or '테슬라 슈퍼차저 · ' + (ad.get('city') or ''))
            if x['status'] == 'CONSTRUCTION':
                name += ' (공사 중)'
            # 위치·이름만 (충전기 수·kW 같은 세부는 넣지 않음, 11/21 사용자 결정)
            sc.append([round(la, 5), round(lo, 5), name])

    # 사고 다발 지역: 최근 3년치만, [위도, 경도, 유형, 사고 건수]
    acc = []
    ap = RAW / 'accidents_all.json'
    if ap.exists():
        ar = json.load(open(ap, encoding='utf-8'))
        years = [int(x['ACDNT_YEAR']) for x in ar if str(x.get('ACDNT_YEAR', '')).isdigit()]
        y0 = (max(years) - 2) if years else 0
        seen = set()
        for x in ar:
            try:
                la, lo, y = float(x['LATITUDE']), float(x['LONGITUDE']), int(x['ACDNT_YEAR'])
            except (ValueError, TypeError, KeyError):
                continue
            if y < y0 or not (33 < la < 39 and 124 < lo < 132):
                continue
            k = (round(la, 4), round(lo, 4))
            if k in seen:
                continue
            seen.add(k)
            n = x.get('OCCRRNC_CO', '0')
            acc.append([round(la, 5), round(lo, 5), (x.get('ACDNT_TYPE_SE') or '').strip(), int(n) if str(n).isdigit() else 0])
    (out_dir / 'acc.json').write_text(json.dumps(acc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    b_body = json.dumps(bumps, separators=(',', ':'))
    p_body = json.dumps({'sc': sc, 'rest': rest}, ensure_ascii=False, separators=(',', ':'))
    (out_dir / 'bumps.json').write_text(b_body, encoding='utf-8')
    (out_dir / 'pois.json').write_text(p_body, encoding='utf-8')
    a_body = (out_dir / 'acc.json').read_text(encoding='utf-8')
    ver = {'ver': hashlib.sha1((b_body + p_body + a_body).encode()).hexdigest()[:10],
           'bumps': len(bumps), 'sc': len(sc), 'rest': len(rest), 'acc': len(acc)}
    (out_dir / 'extra-ver.json').write_text(json.dumps(ver), encoding='utf-8')
    print('과속방지턱', n_pub, '+ OSM', len(bumps) - n_pub, '=', len(bumps),
          '| 슈퍼차저', len(sc), '| 휴게소·쉼터', len(rest), ver)


if __name__ == '__main__':
    if '--cached' not in sys.argv:
        fetch_all()
    build(sys.argv[1])
