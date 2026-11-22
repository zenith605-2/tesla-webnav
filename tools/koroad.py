"""한국도로교통공단 월별 '교통과학장비 운영정보 안내리스트'(경찰청 신규설치·이전설치·속도변경)로
표준데이터(data.go.kr 15028200)가 아직 못 따라온 카메라를 채운다 (11/22).

입력: data/raw/koroad/*.xlsx  (블로그 koroadblog '전국 신규 과속/단속 카메라 설치장소 공개' 첨부)
대조: 장비번호 = 표준데이터 MNLSS_REGLT_CAMERA_MANAGE_NO
 - 신규인데 표준데이터에 없음 → 주소를 티맵 주소검색(fullAddrGeo)으로 좌표 → 추가
 - 이전설치인데 표준데이터 기준일이 이전일보다 앞 → 새 주소 좌표로 옮김
 - 속도변경인데 표준데이터 기준일이 변경일보다 앞 → 제한속도만 바꿈
출력: tools/cam_koroad.json (cam_sources.load_raw 가 반영), data/koroad_report.txt, 좌표 캐시 data/koroad_geo.json
실행: .venv/bin/python tools/koroad.py   (openpyxl 필요, .tmap_key 사용 — 키는 출력하지 않음)
"""
import datetime, glob, json, re, time, urllib.parse, urllib.request
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
RAW = json.load(open(ROOT / 'data/raw/cameras_all.json', encoding='utf-8'))
BY = {(x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or '').strip(): x for x in RAW}
GEO_F = ROOT / 'data/koroad_geo.json'
GEO = json.load(open(GEO_F)) if GEO_F.exists() else {}
KEY = (ROOT / '.tmap_key').read_text().strip()
REG = {'서울': '서울', '부산': '부산', '대구': '대구', '인천': '인천', '광주': '광주', '대전': '대전', '울산': '울산', '세종': '세종',
       '경기남부': '경기', '경기북부': '경기', '강원': '강원', '충북': '충북', '충남': '충남', '전북': '전북', '전남': '전남',
       '경북': '경북', '경남': '경남', '제주': '제주'}


def day(v):
    if isinstance(v, datetime.datetime): return v.strftime('%Y-%m-%d')
    s = str(v or '').strip()
    m = re.match(r'(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})', s)
    if not m: return ''
    y = int(m.group(1)); y = y + 2000 if y < 100 else y
    return f'{y:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'


def geo(q):
    if q in GEO: return GEO[q]
    u = 'https://apis.openapi.sk.com/tmap/geo/fullAddrGeo?version=1&coordType=WGS84GEO&fullAddr=' + urllib.parse.quote(q)
    r = None
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'appKey': KEY, 'Accept': 'application/json'}), timeout=20))
        c = d['coordinateInfo']['coordinate'][0]
        la, lo = c.get('lat') or c.get('newLat'), c.get('lon') or c.get('newLon')
        fl = c.get('matchFlag') or c.get('newMatchFlag') or ''
        if la and lo: r = [float(la), float(lo), fl]
    except Exception:
        r = None
    GEO[q] = r
    time.sleep(0.15)
    return r


def queries(reg, loc):
    """설치장소 글에서 주소 후보: 번지까지 자른 앞부분, 괄호 속 '동 번지'"""
    t = re.sub(r'\s+', ' ', loc).strip()
    if not t.startswith(reg) and not re.match(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충|전|경|제주)', t): t = reg + ' ' + t
    out = []
    head = t.split('(')[0]
    m = re.match(r'^(.*?\d+(?:-\d+)?)(?:\s|$|번지)', head)
    if m and re.search(r'[동리가로길]\s?(산\s?)?\d', m.group(1)): out.append(m.group(1))
    sg = re.match(r'^(\S+\s+\S+[시군구](?:\s+\S+[구])?)', t)
    for p in re.findall(r'\(([^()]*?\d+(?:-\d+)?)[,)]', t):
        if re.search(r'[동리가]\s?(산\s?)?\d', p) and sg: out.append(sg.group(1) + ' ' + p.split(',')[0])
    return out


def poi(gu, name):
    """번지 없는 설치장소: '구 + 건물·교차로 이름'으로 티맵 장소 검색. 결과 주소에 그 구가 있어야 받음"""
    q = 'P:' + gu + ' ' + name
    if q in GEO: return GEO[q]
    u = 'https://apis.openapi.sk.com/tmap/pois?version=1&count=3&reqCoordType=WGS84GEO&resCoordType=WGS84GEO&searchKeyword=' + urllib.parse.quote(gu.split()[-1] + ' ' + name)
    r = None
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'appKey': KEY, 'Accept': 'application/json'}), timeout=20))
        for p in d['searchPoiInfo']['pois']['poi']:
            addr = ' '.join(str(p.get(k) or '') for k in ('upperAddrName', 'middleAddrName', 'lowerAddrName'))
            core = re.sub(r'(초교|초등학교)$', '초', re.sub(r'\s', '', name.split()[0]))
            core = re.sub(r'[34]$', '', core)
            pn = re.sub(r'(초등학교)', '초', re.sub(r'\s', '', p.get('name', '')))
            if gu.split()[-1][:2] in addr and len(core) >= 2 and core in pn and not re.search(r'(로|길)$', core) and not re.search(r'(로|길)$', pn):  # 도로 이름만으로는 위치가 안 됨
                r = [float(p['noorLat']), float(p['noorLon']), 'POI ' + p.get('name', '')]
                break
    except Exception:
        r = None
    GEO[q] = r
    time.sleep(0.15)
    return r


def landmark(loc):
    t = re.sub(r'\(.*?\)', ' ', loc)
    t = re.sub(r'(시점|종점|구간|\d+(,\d+)*차로|앞|건너편|부근|인근|맞은편|지나|전방|후방|\d+m\s*지점)', ' ', t)
    w = [x for x in t.split() if x]
    # 도로명 뒤 첫 이름(초교·교차로·사거리·4 등)
    for i, x in enumerate(w):
        if re.search(r'(로|길|대로)(\d+번길)?$', x) and i + 1 < len(w):
            return ' '.join(w[i + 1:i + 3])
    return ''  # 도로 이름 뒤에 건물·교차로 이름이 없으면 위치를 못 잡음


rows = []
for f in sorted(glob.glob(str(ROOT / 'data/raw/koroad/*.xlsx'))):
    wb = openpyxl.load_workbook(f, read_only=True)
    for ws in wb.worksheets:
        reg = REG.get(ws.title.strip(), ws.title.strip())
        for r in ws.iter_rows(values_only=True):
            if not r or not isinstance(r[0], (int, float)) or len(r) < 7: continue
            act = str(r[1] or '')
            act = 'new' if ('신규' in act or '신설' in act) else 'move' if ('이전' in act or '이설' in act) else 'speed' if '속도' in act else 'other'
            lims = re.findall(r'\d+', str(r[4] or ''))
            rows.append({'id': str(r[2] or '').strip(), 'act': act, 'form': str(r[3] or ''), 'lim': int(lims[-1]) if lims else 0,
                         'loc': str(r[5] or ''), 'date': day(r[6]), 'zone': str(r[8] or '') if len(r) > 8 else '', 'reg': reg, 'file': Path(f).name})
rows.sort(key=lambda x: x['date'])
last = {}
for x in rows:
    if x['id']: last[x['id']] = x  # 같은 장비는 가장 최근 줄만

out, rep, st = [], [], {}
for eid, x in last.items():
    raw = BY.get(eid)
    rd = (raw or {}).get('REFERENCE_DATE') or ''
    need = None
    if raw is None and x['act'] in ('new', 'move', 'other'): need = 'new'
    elif raw is not None and x['act'] == 'move' and rd < x['date']: need = 'move'
    elif raw is not None and x['act'] == 'speed' and rd < x['date'] and str(raw.get('LMTT_VE')).strip() != str(x['lim']): need = 'speed'
    if not need:
        st['이미 반영'] = st.get('이미 반영', 0) + 1; continue
    e = {'id': eid, 'act': need, 'lim': x['lim'], 'date': x['date'], 'loc': x['loc'],
         'se': '1+2' if '신호' in x['form'] else '1', 'zone': '2' if '스쿨' in x['zone'] or '어린이' in x['loc'] else '',
         'sec': '1' if re.search(r'시점', x['loc']) else '2' if re.search(r'종점', x['loc']) else ''}
    MAN = json.load(open(ROOT / 'tools/cam_koroad_manual.json', encoding='utf-8')) if (ROOT / 'tools/cam_koroad_manual.json').exists() else {}
    if eid in MAN and need in ('new', 'move'):  # 손으로 정한 위치(도로 위에 붙임, 11/22 인천 31대)
        m = MAN[eid]; e['la'], e['lo'], e['dir'], e['flag'] = m['la'], m['lo'], m.get('dir', -1), '수동'
        if m.get('lim'): e['lim'] = m['lim']
        st[need] = st.get(need, 0) + 1; out.append(e)
        rep.append(f"{need}(수동) {eid} {e['lim']} {e['la']},{e['lo']} {m.get('note','')}")
        continue
    if need in ('new', 'move'):
        g = None
        for q in queries(x['reg'], x['loc']):
            g = geo(q)
            if g: break
        if not g:
            sg = re.match(r'^(?:\S+\s+)?(\S+[시군구](?:\s+\S+구)?)', x['loc'] if x['loc'].split()[0] != x['reg'] else x['loc'].split(' ', 1)[1])
            lm = landmark(x['loc'])
            if sg and lm: g = poi(x['reg'] + ' ' + sg.group(1), re.sub(r'(\d)$', r'\1', lm).replace('4 ', '사거리 ').rstrip('4') if lm.endswith('4') else lm)
        if not g:
            st[need + ' 주소못찾음'] = st.get(need + ' 주소못찾음', 0) + 1
            rep.append(f"주소못찾음 {need} {eid} {x['lim']} {x['reg']} {x['loc']}")
            continue
        e['la'], e['lo'], e['flag'] = round(g[0], 5), round(g[1], 5), g[2]
    st[need] = st.get(need, 0) + 1
    out.append(e)
    rep.append(f"{need} {eid} {x['lim']} {e.get('la','')},{e.get('lo','')} {x['reg']} {x['loc']} ({x['date']})")

json.dump(GEO, open(GEO_F, 'w'), ensure_ascii=False)
json.dump(out, open(ROOT / 'tools/cam_koroad.json', 'w'), ensure_ascii=False, indent=0)
(ROOT / 'data/koroad_report.txt').write_text('\n'.join(rep), encoding='utf-8')
print('목록 줄', len(rows), '장비', len(last), st)
