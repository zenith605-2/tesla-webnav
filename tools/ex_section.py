"""도로공사 구간단속(data.go.kr 15104214, data/raw/ex_section_utf8.csv)을 우리 카메라 자료와 맞춰 빠진 시점·종점을 tools/cam_ex_sec.json 에 쓴다 (11/22).
자료에는 좌표가 없고 '노선·방향·시점 km·시점인근시설물·종점 km·종점인근시설물·연장'만 있다.
 1) 시설물 이름(OO IC/JC/TG/SA/터널/교)을 OSM(data/osm/hw.json, tools/osm_hw_extract.py)에서 찾고
 2) 시점·종점 후보 쌍 중 직선거리가 '연장'에 가장 맞는 쌍을 고른 뒤
 3) 그 방향 본선(일방통행 차로)에 붙인다.
 4) 우리 자료(docs/cams.json)에 같은 방향 구간 시작/끝이 1.5km 안에 있으면 넘기고, 없으면 추가 후보.
실행: python3 tools/ex_section.py   → tools/cam_ex_sec.json (build_cams.py 가 읽음), data/ex_section_report.txt
"""
import csv, json, math, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = json.load(open(ROOT / 'data/osm/hw.json'))
C = json.load(open(ROOT / 'docs/cams.json'))
# 지난번에 이 스크립트가 넣은 지점은 '이미 있음'으로 치지 않음 (빌드 결과에 섞여 있으므로)
_old = {(e['la'], e['lo']) for e in (json.load(open(ROOT / 'tools/cam_ex_sec.json')) if (ROOT / 'tools/cam_ex_sec.json').exists() else [])}
C = [c for c in C if (c[0], c[1]) not in _old]


def dist(a, b, c, d):
    return math.hypot((d - b) * math.cos(math.radians((a + c) / 2)) * 111320, (c - a) * 111320)


def brg(a, b, c, d):
    y = math.sin(math.radians(d - b)) * math.cos(math.radians(c))
    x = math.cos(math.radians(a)) * math.sin(math.radians(c)) - math.sin(math.radians(a)) * math.cos(math.radians(c)) * math.cos(math.radians(d - b))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def adiff(a, b):
    return abs((a - b + 180) % 360 - 180)


SUF = r'(나들목|분기점|톨게이트|요금소|영업소|휴게소|졸음쉼터|IC|JCT|Jct|jct|JC|TG|SA|TN|터널|교량|교|하이패스|\(.*?\))'


def base(n):
    n = re.sub(r'(인근|입구|출구|부근|앞|전방|후방|지점)', '', n or '')
    n = re.sub(SUF, '', n)
    return re.sub(r'[\s·\-]', '', n)


def kind_of(n):
    if re.search(r'TN|터널', n): return 'tunnel'
    if re.search(r'교(\s|$|입구|출구|인근)', n): return 'bridge'
    if re.search(r'SA|휴게소', n): return 'sa'
    if re.search(r'TG|요금소|톨게이트|영업소', n): return 'tg'
    return 'ic'


def route_core(r):
    m = re.search(r'\((.*?)\)', r)
    if m and '-' not in m.group(1): return m.group(1)  # 당진영덕선(청주영덕) → OSM 은 '청주영덕고속도로'
    r = re.sub(r'\(.*?\)', '', r).strip()
    if r.endswith('지선'): return r[:-2]
    return r[:-1] if r.endswith('선') else r


# 노선별 본선 조각
WAYS = HW['ways']
ALIAS = {'청주영덕': ['서산영덕', '당진영덕', '청주영덕'], '당진대전': ['서산영덕', '당진영덕', '당진대전'], '순천부산': ['남해'], '영암순천': ['남해'],
         '남해제2지': ['남해2지선', '남해제2지선'], '완주장수': ['새만금포항', '새만금전주'], '세종포천': ['세종포천', '서울세종', '구리세종'],
         '제2중부': ['제2중부', '중부'], '호남': ['호남'], '부산포항': ['부산포항', '동해'], '대구포항': ['대구포항', '새만금포항'], '포항영덕': ['포항영덕', '동해']}
def route_ways(core):
    keys = ALIAS.get(core, [core])
    return [w for w in WAYS if any(k in (w[0] or '') for k in keys)]


POIS = {}
for nm, la, lo, k in HW['pois']:
    POIS.setdefault(base(nm), []).append((la, lo, k, nm))


def near_way(la, lo, ws, maxd):
    best = None
    for w in ws:
        p = w[3]
        if abs(p[0][0] - la) > 0.3 or abs(p[0][1] - lo) > 0.3:
            # 긴 조각일 수 있어 대충만 거름
            if min(abs(q[0] - la) for q in p[::max(1, len(p) // 8)]) > 0.08: continue
        for i in range(len(p) - 1):
            a, b = p[i], p[i + 1]
            # 선분 투영
            ax, ay = 0, 0
            bx = (b[1] - a[1]) * 88000; by = (b[0] - a[0]) * 111320
            px = (lo - a[1]) * 88000; py = (la - a[0]) * 111320
            L2 = bx * bx + by * by
            t = 0 if L2 == 0 else max(0, min(1, (px * bx + py * by) / L2))
            qx, qy = bx * t, by * t
            d = math.hypot(px - qx, py - qy)
            if d <= maxd and (best is None or d < best[0]):
                best = (d, a[0] + qy / 111320, a[1] + qx / 88000, brg(a[0], a[1], b[0], b[1]), w)
    return best


def snap_dir(la, lo, ws, want):
    """want 방향(°)과 맞는 일방 본선에 붙임"""
    cands = []
    for w in ws:
        if w[2] not in ('yes', '1', 'true') and w[4] == 'trunk':
            continue
        r = near_way(la, lo, [w], 1500)
        if r and adiff(r[3], want) < 70:
            cands.append(r)
    if not cands:
        return None
    return min(cands, key=lambda r: r[0])


def cand_pts(fac, ws):
    b = base(fac)
    if not b: return []
    k = kind_of(fac)
    out = []
    for key, lst in POIS.items():
        if key == b or (len(b) >= 2 and key.startswith(b) and len(key) - len(b) <= 1):
            for la, lo, pk, nm in lst:
                ok = (k == 'tunnel' and pk.startswith('tunnel')) or (k == 'bridge' and pk.startswith('bridge')) or \
                     (k == 'sa' and pk in ('services', 'rest_area')) or (k == 'tg' and pk in ('toll', 'toll_gantry', 'motorway_junction')) or \
                     (k == 'ic' and pk in ('motorway_junction', 'toll', 'toll_gantry'))
                if ok: out.append((la, lo, nm))
    # 노선 본선에서 3km 안만
    res = []
    for la, lo, nm in out:
        if near_way(la, lo, ws, 3000): res.append((la, lo, nm))
    return res


def lim_near(la, lo, ws):
    """같은 고속도로 본선 위(60m 안) 카메라 중 가장 가까운 것의 제한속도, 없으면 100"""
    cs = sorted((dist(la, lo, c[0], c[1]), c) for c in C if c[2] >= 80 and abs(c[0] - la) < 0.3 and abs(c[1] - lo) < 0.4)
    for d, c in cs[:40]:
        if d > 30000: break
        if near_way(c[0], c[1], ws, 60): return c[2]
    return 100


rows = list(csv.DictReader(open(ROOT / 'data/raw/ex_section_utf8.csv', encoding='utf-8')))
add, rep = [], []
st = {'ok': 0, 'have': 0, 'add': 0, 'fail': 0}
for r in rows:
    core = route_core(r['노선'])
    ws = route_ways(core)
    L = float(r['연장'] or 0) * 1000
    tag = f"{r['노선']} {r['방향']}방향 {r['시점인근시설물'].strip()}→{r['종점인근시설물'].strip()} {r['연장']}km"
    if not ws:
        st['fail'] += 1; rep.append('본선없음 ' + tag); continue
    S, E = cand_pts(r['시점인근시설물'], ws), cand_pts(r['종점인근시설물'], ws)
    # 한쪽만 찾으면: 같은 노선 경찰청 구간단속 지점(연장 ±35% 거리)을 반대쪽 기준으로 (예: 갈현터널은 OSM 에 이름 없음)
    PS = [(c[0], c[1], '경찰청 구간단속') for c in C if c[4] in (1, 2) and c[2] >= 80]
    if S and not E: E = [p for p in PS if any(0.6 * L < dist(p[0], p[1], q[0], q[1]) < 1.4 * L for q in S) and near_way(p[0], p[1], ws, 300)]
    elif E and not S: S = [p for p in PS if any(0.6 * L < dist(p[0], p[1], q[0], q[1]) < 1.4 * L for q in E) and near_way(p[0], p[1], ws, 300)]
    if not S or not E:
        st['fail'] += 1; rep.append(f"시설물못찾음(시점{len(S)} 종점{len(E)}) " + tag); continue
    best = None
    for s in S:
        for e in E:
            d = dist(s[0], s[1], e[0], e[1])
            if d < 300: continue
            sc = abs(d - L * 0.92)
            if best is None or sc < best[0]: best = (sc, s, e, d)
    if not best or best[0] > max(2500, L * 0.35):
        st['fail'] += 1; rep.append(f"길이안맞음({round(best[3]) if best else '-'}m) " + tag); continue
    _, s, e, d = best
    b0 = brg(s[0], s[1], e[0], e[1])
    ss, ee = snap_dir(s[0], s[1], ws, b0), snap_dir(e[0], e[1], ws, b0)
    if not ss or not ee:
        st['fail'] += 1; rep.append('본선붙이기실패 ' + tag); continue
    st['ok'] += 1
    lim = lim_near(ss[1], ss[2], ws)
    for sec, p in ((1, ss), (2, ee)):
        have = [c for c in C if c[4] == sec and dist(p[1], p[2], c[0], c[1]) < 1500 and (c[7] < 0 or adiff(c[7], p[3]) < 60)]
        if have:
            st['have'] += 1
            continue
        st['add'] += 1
        add.append({'la': round(p[1], 5), 'lo': round(p[2], 5), 'lim': lim, 'kind': 'S', 'zone': 0, 'sec': sec,
                    'road': r['노선'], 'dir': round(p[3]),
                    'note': f"도로공사 구간단속 {'시점' if sec == 1 else '종점'} {tag} (OSM {s[2] if sec == 1 else e[2]} 기준, 직선 {round(d)}m)"})
        rep.append(('추가 ' if sec == 1 else '추가(종점) ') + f"{round(p[1],5)},{round(p[2],5)} {lim} " + tag)

# 실차로 없다고 확인된 추정 지점 (11/28: 충주분기점 근처에 반대편 차로로 붙은 충주IC~북충주IC 시점·종점)
BAD = {(37.0438, 127.73795), (37.04201, 127.74835)}
add = [e for e in add if (e['la'], e['lo']) not in BAD]
json.dump(add, open(ROOT / 'tools/cam_ex_sec.json', 'w'), ensure_ascii=False, indent=1)
(ROOT / 'data/ex_section_report.txt').write_text('\n'.join(rep), encoding='utf-8')
print(st, '추가', len(add))
