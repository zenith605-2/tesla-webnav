"""단속카메라마다 '어느 방향으로 달리는 차를 찍는지'(방위각)를 오픈스트리트맵 도로에 맞춰 미리 계산한다.

왜: 공공데이터에는 방향 각도가 없어서, 길 왼쪽 20~30m 에 찍힌 카메라를 잡으려고 범위를 넓히면
    분리도로 반대편 카메라까지 뜬다. 방향을 알면 위치 범위는 넓게 두고 방향으로 거를 수 있다. (11/21 제미나이 논의)

방법
  1) 카메라 반경 45m 안의 차도(highway=motorway~residential)를 모두 모은다 (pyosmium, 노드 위치 포함).
  2) 카메라마다 가까운 도로 조각과 그 진행 방향 후보를 만든다.
     - 일방통행(oneway=yes/-1, motorway, 회전교차로): 그 방향 하나. 분리도로는 차로마다 따로 그려져 있어 여기서 갈린다.
     - 양방향 도로: 점수 계산에만 쓰고 방향은 정하지 않음(-1). 좌표가 반대편으로 벗어난 카메라가 있어서 (만삼로 사례)
  3) 점수 = 거리 + 도로 이름이 다르면 벌점 + 램프(_link)·골목 벌점. 1등과 2등의 방향이 45° 넘게 다르고
     점수 차가 작으면(교차로 모서리 등) 판단 안 함(-1).
  4) 결과: tools/cam_dir.json {"위도,경도": 방위각 또는 -1}  → build_cams.py 가 8번째 칸으로 붙인다.

실행: .venv/bin/python tools/build_cam_dir.py   (data/osm/south-korea-latest.osm.pbf 필요, Geofabrik)
지도 데이터 © OpenStreetMap contributors (ODbL)
"""
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parent.parent
PBF = ROOT / 'data/osm/south-korea-latest.osm.pbf'
OUT = ROOT / 'tools/cam_dir.json'
R_SEARCH = 45.0
ROADS = {'motorway': 0, 'trunk': 0, 'primary': 0, 'secondary': 0, 'tertiary': 0, 'unclassified': 2,
         'residential': 4, 'living_street': 6,
         'motorway_link': 8, 'trunk_link': 8, 'primary_link': 8, 'secondary_link': 8, 'tertiary_link': 8}
CELL = 0.001  # 약 100m
GENERIC = ('시청', '군청', '구청', '도청', '경찰서', '터미널', '교육청', '우체국', '면사무소', '행정복지센터', '주민센터', '공항', '종합운동장', '보건소', '소방서', '법원', '세무서', '역', 'IC', '톨게이트', '휴게소', '읍사무소')
CITY = {'서울': (37.5665, 126.9780), '서울시': (37.5665, 126.9780), '부산': (35.1796, 129.0756), '인천': (37.4563, 126.7052), '대구': (35.8714, 128.6014),
        '광주': (35.1595, 126.8526), '대전': (36.3504, 127.3845), '울산': (35.5384, 129.3114), '세종': (36.4800, 127.2890), '수원': (37.2636, 127.0286),
        '성남': (37.4200, 127.1267), '용인': (37.2411, 127.1776), '고양': (37.6584, 126.8320), '의정부': (37.7381, 127.0337), '춘천': (37.8813, 127.7298),
        '청주': (36.6424, 127.4890), '천안': (36.8151, 127.1139), '전주': (35.8242, 127.1480), '포항': (36.0190, 129.3435), '창원': (35.2281, 128.6811)}
MISS = [] if '--miss' in sys.argv else None  # 못 찾은 지명 보기
_tg = Path(__file__).resolve().parent.parent / 'data/osm/tmap_geo.json'
TG = json.load(open(_tg)) if _tg.exists() else {}  # '지명|위도0.1|경도0.1' → [위도, 경도] 또는 None(검색해도 없음)
NEED = set()  # 아직 티맵에 물어보지 않은 지명


def cams():
    from cam_sources import load_raw  # 경찰청 + 경기도 추가분 (11/22)
    raw = load_raw()
    out = {}
    for x in raw:
        try:
            la, lo = float(x['LATITUDE']), float(x['LONGITUDE'])
        except ValueError:
            continue
        if not (33 < la < 39 and 124 < lo < 132):
            continue
        k = f'{round(la, 5)},{round(lo, 5)}'
        out.setdefault(k, (la, lo, (x.get('ROAD_ROUTE_NM') or '').strip().replace(' ', ''), x.get('ITLPC') or ''))
    return out


def norm(s):
    return (s or '').replace(' ', '')


class Roads(osmium.SimpleHandler):
    def __init__(self, grid):
        super().__init__()
        self.grid = grid
        self.ways = []
        self.names = defaultdict(list)   # 지명·교차로·건물 등 이름 → 위치들 (설치장소 글 '(A→B)' 찾기용)
        self.places = {}
        self.generic = defaultdict(list)  # '시청'·'경찰서' 같은 일반 명사 → 그런 이름으로 끝나는 곳들

    def add_name(self, tags, loc):
        nm = tags.get('name') or tags.get('name:ko')
        if not nm:
            return
        k = norm(nm)
        keys = {k}
        # 역: 오픈스트리트맵엔 '수원'처럼 '역' 없이 적힌 경우가 많음
        if tags.get('railway') in ('station', 'halt') or tags.get('public_transport') == 'station' or tags.get('station'):
            if not k.endswith('역'):
                keys.add(k + '역')
        # 나들목·분기점: '이천' / '이천나들목' → '이천IC'
        if tags.get('highway') == 'motorway_junction' or k.endswith(('나들목', '분기점', 'IC', 'JC', '톨게이트')):
            base = re.sub(r'(나들목|분기점|IC|JC|톨게이트)$', '', k)
            keys.update({base + 'IC', base + 'JC', base + '나들목', base + '분기점', base + '톨게이트'})
        for kk in keys:
            self.names[kk].append(loc)
        if tags.get('place'):
            self.places.setdefault(k, []).append(loc)
        for g in GENERIC:
            if k.endswith(g):
                self.generic[g].append(loc)

    def node(self, n):
        if 'name' in n.tags or 'name:ko' in n.tags:
            self.add_name(n.tags, (n.location.lat, n.location.lon))

    def way(self, w):
        hw = w.tags.get('highway')
        if 'name' in w.tags:
            try:
                n0 = w.nodes[len(w.nodes) // 2]
                self.add_name(w.tags, (n0.location.lat, n0.location.lon))
            except Exception:
                pass
        if hw not in ROADS:
            return
        try:
            pts = [(n.location.lat, n.location.lon) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(pts) < 2:
            return
        if not any((int(la / CELL), int(lo / CELL)) in self.grid for la, lo in pts):
            # 노드 사이가 길어 칸을 건너뛸 수 있으니 중간점도 본다
            mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:])]
            if not any((int(la / CELL), int(lo / CELL)) in self.grid for la, lo in mids):
                return
        ow = w.tags.get('oneway', '')
        jn = w.tags.get('junction', '')
        one = 1 if (ow in ('yes', 'true', '1') or hw == 'motorway' or jn in ('roundabout', 'circular')) else (-1 if ow == '-1' else 0)
        if ow == 'no':
            one = 0
        name = norm(w.tags.get('name')) or norm(w.tags.get('ref'))
        self.ways.append((pts, one, hw, name))


def dkm(a, b, c, d):
    return math.hypot((a - c) * 111.32, (b - d) * 111.32 * math.cos(math.radians(a)))


def bearing(A, B):
    kx = math.cos(math.radians(A[0]))
    return (math.degrees(math.atan2((B[1] - A[1]) * kx, B[0] - A[0])) + 360) % 360


def adiff(a, b):
    return abs((a - b + 180) % 360 - 180)


def xy(la0, lo0, la, lo):
    kx = 111320 * math.cos(math.radians(la0))
    return (lo - lo0) * kx, (la - la0) * 111320


def main():
    C = cams()
    grid = set()
    for la, lo, _, _ in C.values():
        ci, cj = int(la / CELL), int(lo / CELL)
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                grid.add((ci + a, cj + b))
    h = Roads(grid)
    h.apply_file(str(PBF), locations=True, idx='flex_mem')
    print('roads near cameras:', len(h.ways), file=sys.stderr)
    # 도로 조각 격자
    seg_grid = defaultdict(list)
    for wi, (pts, one, hw, name) in enumerate(h.ways):
        for si in range(len(pts) - 1):
            a, b = pts[si], pts[si + 1]
            cells = {(int(a[0] / CELL), int(a[1] / CELL)), (int(b[0] / CELL), int(b[1] / CELL)),
                     (int((a[0] + b[0]) / 2 / CELL), int((a[1] + b[1]) / 2 / CELL))}
            for c in cells:
                seg_grid[c].append((wi, si))
    out, stat = {}, defaultdict(int)
    # 지명 앞부분으로도 찾기: '서울' → '서울특별시'
    pref = defaultdict(list)
    for nm, locs in h.places.items():
        for L in range(2, len(nm)):
            pref[nm[:L]].extend(locs)

    def geo(name, la, lo):
        name = re.sub(r'(방면|방향|쪽|방|시내|일대)$', '', norm(re.sub(r'[()\[\]]', '', name)))
        if len(name) < 2:
            return None
        # 큰 도시 이름은 그 도시 시청 좌표로 (11/22: '서울→탄천종합운동장' 의 '서울'이 근처 '서울○○' 가게로 잡혀 방향이 뒤집힘)
        if name in CITY:
            return CITY[name]
        locs = h.names.get(name) or pref.get(name) or []
        lim = 60
        if not locs and name in GENERIC:
            locs, lim = h.generic.get(name, []), 20
        if not locs:
            # 학교 줄임말 (11/22 실차: '옥빛중->옥빛고교' 를 못 찾아 방향 모름 → 반대편 차선 경고)
            for pat, rep in ((r'초교$', '초등학교'), (r'초$', '초등학교'), (r'여중$', '여자중학교'), (r'중교$', '중학교'), (r'중$', '중학교'),
                             (r'여고$', '여자고등학교'), (r'고교$', '고등학교'), (r'고$', '고등학교')):
                if re.search(pat, name):
                    locs = h.names.get(re.sub(pat, rep, name)) or []
                    if locs:
                        break
        if not locs:
            for suf in ('시청', '군청', '시', '군', '읍', '면', '동'):
                locs = h.names.get(name + suf) or []
                if locs:
                    break
        best = None
        for p in locs:
            d = dkm(la, lo, *p)
            if d < lim and (best is None or d < best[0]):
                best = (d, p)
        if best:
            return best[1]
        # 오픈스트리트맵에 없는 지명(아파트·건물 등)은 티맵 장소 검색 결과(tools/geo_tmap.py 가 만든 data/osm/tmap_geo.json)로 (11/22)
        tk = f'{name}|{round(la, 1)}|{round(lo, 1)}'
        if TG.get(tk):
            return tuple(TG[tk])
        if tk not in TG:
            NEED.add(tk)
        return None

    def text_brg(txt, la, lo):
        m = re.search(r'([가-힣A-Za-z0-9]+)\s*(?:->|→|⇒|=>|>)\s*([가-힣A-Za-z0-9]+)', txt)
        if not m:
            return None
        A, B = geo(m.group(1), la, lo), geo(m.group(2), la, lo)
        # 설명 글 오류 찾기 (11/22 실차: 양주 옥정 카메라에 '교문사거리(구리시청→동구릉역)'): 양쪽 지명이 서로 3km 안(짧은 구간)인데 둘 다 카메라에서 3km 넘게 멀면 좌표가 틀린 것. 고속도로 '(구리→용인)' 같은 도시 방향은 둘 사이가 멀어서 안 걸림
        if A and B and dkm(*A, *B) < 3 and min(dkm(la, lo, *A), dkm(la, lo, *B)) > 3:
            BAD.append(f'{round(la, 5)},{round(lo, 5)}')
            return None  # 설명 글이 다른 동네 것 → 글로 방향을 정하지 않음 (카메라는 남김: 경기도 자료·로드뷰로 보니 좌표는 맞고 글만 틀린 경우였음)
        if MISS is not None:
            if not A:
                MISS.append(m.group(1))
            if not B:
                MISS.append(m.group(2))
        if A and B and dkm(*A, *B) > 0.2:
            return bearing(A, B)
        if B and dkm(la, lo, *B) > 0.3:
            return bearing((la, lo), B)
        if A and dkm(la, lo, *A) > 0.3:
            return bearing(A, (la, lo))
        return None

    BAD = []
    ROADB = {}
    SRC = {}
    for k, (la, lo, cname, itlpc) in C.items():
        tb = text_brg(itlpc, la, lo) if itlpc else None
        if tb is not None:
            stat['text_found'] += 1
        ci, cj = int(la / CELL), int(lo / CELL)
        cand = {}
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for wi, si in seg_grid.get((ci + a, cj + b), ()):
                    pts, one, hw, name = h.ways[wi]
                    A, B = pts[si], pts[si + 1]
                    ax, ay = xy(la, lo, *A)
                    bx, by = xy(la, lo, *B)
                    dx, dy = bx - ax, by - ay
                    L2 = dx * dx + dy * dy
                    if L2 < 0.01:
                        continue
                    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
                    px, py = ax + dx * t, ay + dy * t
                    d = math.hypot(px, py)
                    if d > R_SEARCH:
                        continue
                    brg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
                    # 카메라가 조각 진행 방향의 오른쪽이면 +
                    lat = (dx * (0 - ay) - dy * (0 - ax)) / math.sqrt(L2)
                    lat = -lat
                    pen = ROADS[hw] + (0 if not cname or not name or cname in name or name in cname else 6)
                    dirs = []
                    if one == 1:
                        dirs = [(brg, 0)]
                    elif one == -1:
                        dirs = [((brg + 180) % 360, 0)]
                    else:
                        if abs(lat) < 4:
                            dirs = [(brg, 3), ((brg + 180) % 360, 3)]  # 가운데: 방향 못 정함 → 둘 다
                        elif lat > 0:
                            dirs = [(brg, 0), ((brg + 180) % 360, 10)]
                        else:
                            dirs = [((brg + 180) % 360, 0), (brg, 10)]
                    for dd, extra in dirs:
                        sc = d + pen + extra
                        kk = (wi, round(dd / 10))
                        if kk not in cand or cand[kk][0] > sc:
                            cand[kk] = (sc, dd, d, hw, name, one)
        if not cand:
            out[k] = -1
            stat['no_road'] += 1
            continue
        L = sorted(cand.values())
        best = L[0]
        ROADB[k] = int(round(best[1])) % 180  # 방향 확인 도구용: 가장 그럴듯한 도로의 축(0~179, 양쪽 방향 버튼)
        # 설치장소 글 방향이 있으면: 25m 안 도로 방향 중 글과 40° 안으로 맞는 것 (이름 맞는 도로 우선)
        if tb is not None:
            ok = [c for c in L if c[2] <= 25 and adiff(c[1], tb) < 40]
            if ok:
                out[k] = int(round(ok[0][1])) % 360
                SRC[k] = 't'  # 설치장소 글로 정함(가장 믿을 만함)
                stat['text_pick'] += 1
            else:
                out[k] = -1
                stat['text_conflict'] += 1
            continue
        # 2등 중 방향이 크게 다른 것
        rival = next((c for c in L[1:] if abs((c[1] - best[1] + 180) % 360 - 180) > 45), None)
        if rival and rival[0] - best[0] < 6:
            out[k] = -1
            stat['ambiguous'] += 1
            continue
        # 양방향 도로에서 '오른쪽에 있으니 이 방향' 판단은 원본 좌표가 반대편으로 20m 넘게 벗어난 경우가 있어 틀린다
        # (11/21 만삼로 카메라: 남행 단속인데 북행으로 계산됨) → 방향은 분리도로(일방통행 차로)에 15m 안으로 붙은 것만
        if not best[5] or best[2] > 15:
            out[k] = -1
            stat['twoway_or_far'] += 1
            continue
        out[k] = int(round(best[1])) % 360
        stat['oneway'] += 1
    OUT.write_text(json.dumps(out, separators=(',', ':')))
    (ROOT / 'data/osm/cam_dir_src.json').write_text(json.dumps(SRC))
    # 방향 확인 도구(tsnavi/check.html)가 쓰는 도로 축: 방향 모르는 카메라만 (11/22)
    (ROOT / 'docs/cam_road.json').write_text(json.dumps({k: v for k, v in ROADB.items() if out.get(k, -1) == -1}, separators=(',', ':')))
    (ROOT / 'data/osm/tmap_need.json').write_text(json.dumps(sorted(NEED), ensure_ascii=False))
    print('티맵에 물어볼 지명', len(NEED))
    (ROOT / 'tools/cam_bad.json').write_text(json.dumps(sorted(set(BAD)), ensure_ascii=False, indent=0))
    print('설명 글이 다른 동네라 글 방향을 안 쓴 카메라', len(set(BAD)))
    if MISS is not None:
        from collections import Counter
        (ROOT / 'data/osm/miss.txt').write_text('\n'.join(f'{n}\t{c}' for n, c in Counter(MISS).most_common()))
    print(dict(stat), 'total', len(out), file=sys.stderr)


if __name__ == '__main__':
    main()
