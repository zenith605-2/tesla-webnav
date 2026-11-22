"""지방경찰청이 따로 올린 '운영 중 장비 목록'(장비번호 있음)으로 표준데이터에 빠진 카메라를 채운다 (11/22).
 - 경기남부경찰청 고정식 무인단속장비 설치장소현황(data.go.kr, tools/local_fetch.py 로 받음): 장비번호·기능·설치장소, 제한속도 없음
 - 충북경찰청 청주시 무인교통단속장비: 전산번호·주소·제한속도
장비번호가 표준데이터·공단 월별목록(cam_koroad.json)에 없을 때만 → 주소(번지)를 티맵 주소검색으로 좌표.
제한속도 없으면: 같은 자리 300m 안 기존 카메라(같은 도로 이름 우선)의 제한속도, 없으면 넣지 않음.
기존 카메라 60m 안에 같은 제한속도·같은 구간 구분이 있으면 장비번호만 다른 같은 카메라로 보고 넣지 않음.
출력: tools/cam_local.json (cam_sources.load_raw 가 반영), data/local_report.txt
"""
import csv, io, json, math, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = json.load(open(ROOT / 'data/raw/cameras_all.json', encoding='utf-8'))
IDS = {(x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or '').strip() for x in RAW}
KO = {e['id'] for e in json.load(open(ROOT / 'tools/cam_koroad.json'))}
C = json.load(open(ROOT / 'docs/cams.json'))
GEO_F = ROOT / 'data/koroad_geo.json'
GEO = json.load(open(GEO_F)) if GEO_F.exists() else {}
KEY = (ROOT / '.tmap_key').read_text().strip()


def dist(a, b, c, d):
    return math.hypot((d - b) * math.cos(math.radians((a + c) / 2)) * 111320, (c - a) * 111320)


def geo(q):
    if q in GEO: return GEO[q]
    u = 'https://apis.openapi.sk.com/tmap/geo/fullAddrGeo?version=1&coordType=WGS84GEO&fullAddr=' + urllib.parse.quote(q)
    r = None
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'appKey': KEY, 'Accept': 'application/json'}), timeout=20))
        c = d['coordinateInfo']['coordinate'][0]
        la, lo = c.get('lat') or c.get('newLat'), c.get('lon') or c.get('newLon')
        if la and lo: r = [float(la), float(lo), c.get('matchFlag') or c.get('newMatchFlag') or '']
    except Exception:
        r = None
    GEO[q] = r
    time.sleep(0.15)
    return r


def addr(prefix, loc):
    """주소 후보: 지번(동·리 + 번지), 도로명(로·길 + 건물번호), 괄호 속 지번"""
    t = re.sub(r'\s+', ' ', loc).strip()
    if prefix and not t.startswith(prefix): t = prefix + ' ' + t
    head = t.split('(')[0]
    sg = re.match(r'^(\S+\s+\S+[시군](?:\s+\S+구)?)', t)
    out = []
    m = re.match(r'^(.*?(?:동|리|가|읍|면)\s?(?:산\s?)?\d+(?:-\d+)?)', head)
    if m: out.append(m.group(1))
    m = re.match(r'^(.*?(?:로|길)\s?\d+(?:-\d+)?)', head)
    if m: out.append(m.group(1))
    for p in re.findall(r'\(([^()]*?(?:동|리|가)\s?(?:산\s?)?\d+(?:-\d+)?)\)', t):
        if sg: out.append(sg.group(1) + ' ' + p)
    return out


def rd(f):
    b = open(f, 'rb').read()
    for enc in ('utf-8-sig', 'cp949'):
        try: return list(csv.DictReader(io.StringIO(b.decode(enc))))
        except UnicodeDecodeError: pass
    return []


SRC = [
    ('경찰청 경기도남부경찰청_고정식 무인단속장비 설치장소현황_*.csv', '경기', '장비번호', None),
    ('경찰청 충청북도경찰청_청주시 무인교통단속장비_*.csv', '', '전산번호', '제한속도'),
]
out, rep, st = [], [], {}
for pat, pre, idc, limc in SRC:
    fs = sorted((ROOT / 'data/raw/local').glob(pat))
    if not fs: continue
    for r0 in rd(fs[-1]):
        r = {k.strip(): (v or '').strip() for k, v in r0.items() if k}
        eid = r.get(idc, '')
        if not eid or eid in IDS or eid in KO:
            continue
        loc = r.get('설치장소') or r.get('주소') or ''
        fn = r.get('기능', '')
        sec = '1' if '시점' in loc else '2' if '종점' in loc else ''
        g = None
        for q in addr(pre, loc):
            g = geo(q)
            if g: break
        if not g:
            st['주소못찾음'] = st.get('주소못찾음', 0) + 1; rep.append(f'주소못찾음 {eid} {loc}'); continue
        la, lo = round(g[0], 5), round(g[1], 5)
        lim = int(re.findall(r'\d+', r.get(limc, ''))[-1]) if limc and re.findall(r'\d+', r.get(limc, '')) else 0
        near = sorted((dist(la, lo, c[0], c[1]), c) for c in C if abs(c[0] - la) < 0.005 and abs(c[1] - lo) < 0.006)
        if not lim:
            cand = [c for d, c in near if d < 300 and c[2] >= 30 and (not sec or c[4] == int(sec) or c[2] >= 60)]
            lim = cand[0][2] if cand else 0
        if not lim:
            st['제한속도모름'] = st.get('제한속도모름', 0) + 1; rep.append(f'제한속도모름 {eid} {la},{lo} {loc}'); continue
        if any(d < 60 and c[2] == lim and str(c[4] or '') == (sec or '0').replace('0', '') or (d < 60 and c[2] == lim and not sec and c[4] == 0) for d, c in near):
            st['이미있음(번호만 다름)'] = st.get('이미있음(번호만 다름)', 0) + 1; continue
        out.append({'id': eid, 'act': 'new', 'la': la, 'lo': lo, 'lim': lim, 'date': r.get('운영일자', ''), 'loc': loc,
                    'se': '1+2' if '신호' in fn else '1', 'zone': '2' if ('어린이' in loc or '초교' in loc or '초등' in loc) and lim <= 30 else '',
                    'sec': sec, 'dir': -1, 'flag': g[2], 'src': fs[-1].name[:30]})
        st['추가'] = st.get('추가', 0) + 1
        rep.append(f'추가 {eid} {lim} {la},{lo} {loc}')
json.dump(GEO, open(GEO_F, 'w'), ensure_ascii=False)
json.dump(out, open(ROOT / 'tools/cam_local.json', 'w'), ensure_ascii=False, indent=0)
(ROOT / 'data/local_report.txt').write_text('\n'.join(rep), encoding='utf-8')
print(st)
