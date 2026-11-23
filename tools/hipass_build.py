"""톨게이트 하이패스 차로 (11/23 사용자 요청: 톨게이트 앞에서 하이패스 차로 번호를 보여 주기).
한국도로공사 공공데이터 (data.ex.co.kr, 무료):
 - 영업소 차로 운영현황  /openapi/trafficOprgPrcd/tolofCrgwOpPrss  : 영업소×방향별 1~30차로 종류
 - 영업소 위치정보      /openapi/locationinfo/locationinfoUnit     : 영업소 좌표
키: .ex_key 가 있으면 그것, 없으면 예시 키 test (서비스용은 data.ex.co.kr 무료 키로 바꾸기).
민자고속도로 영업소는 자료에 없음.
출력 docs/hipass.json: [[위도, 경도, 이름, 'C'(폐쇄식)|'O'(개방식), {방향: 차로문자열}], ...]
  방향: 입구·출구 (폐쇄식) / 가는 방향 이름 (개방식, 상행·하행 포함) → 개방식은 dirs 에 [위도,경도] 도 붙임
  차로 문자열 한 글자 = 한 차로 (1차로부터): H 하이패스, M 다차로 하이패스, B 하이패스+현금, T 현금, F 화물 하이패스, G 화물 현금, S 정산기, X 미운영
매달 koroad_monthly.sh 에서 실행.
"""
import json, re, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KF = ROOT / '.ex_key'
KEY = KF.read_text().strip() if KF.exists() else 'test'
UA = {'User-Agent': 'Mozilla/5.0'}


def api(path, extra=''):
    out, page = [], 1
    while True:
        u = f'https://data.ex.co.kr/openapi/{path}?key={KEY}&type=json&numOfRows=99&pageNo={page}{extra}'
        d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
        rows = d.get('list') or d.get('lcsTrafficLists') or []
        out += rows
        tot = int(d.get('count') or 0)
        if not rows or len(out) >= tot or page > 50: break
        page += 1
    return out


def kind(v):
    v = v or ''
    if not v: return ''
    if '미운영' in v or v == '토목차로': return 'X'
    if '화물' in v: return 'F' if '하이패스' in v else 'G'
    if '다차로' in v: return 'M'
    if '하이패스' in v and 'TCS' in v: return 'B'
    if '하이패스' in v: return 'H'
    if '정산기' in v: return 'S'
    if 'TCS' in v: return 'T'
    return 'X'


def norm(n):
    n = re.sub(r'\(.*?\)', '', n or '')
    n = re.sub(r'하이패스\s*전용|영업소|요금소|톨게이트|\s', '', n)
    return n


# 개방식 '가는 방향' 이름 → 대략 좌표 (방향 고르기용: 진행 방향과 이 지점 방위가 맞는 쪽)
DIRC = {'판교': (37.39, 127.11), '부산': (35.18, 129.08), '서울': (37.57, 126.98), '퇴계원': (37.65, 127.14), '일산': (37.66, 126.77),
        '순천': (34.95, 127.49), '영암': (34.80, 126.70), '성서': (35.85, 128.50), '인천': (37.46, 126.71), '남이': (36.57, 127.43),
        '하남': (37.54, 127.21), '목포': (34.81, 126.39), '일로': (34.85, 126.50), '지천': (35.89, 128.47), '동대구': (35.88, 128.63),
        '마산': (35.21, 128.58), '김해': (35.23, 128.89), '춘천': (37.88, 127.73), '안양': (37.39, 126.95), '상행': (37.57, 126.98)}

lanes = api('trafficOprgPrcd/tolofCrgwOpPrss')
locs = api('locationinfo/locationinfoUnit')
L = {}
for u in locs:
    try: L.setdefault(norm(u['unitName']), (float(u['yValue']), float(u['xValue'])))
    except (TypeError, ValueError): pass
out, miss = {}, []
for r in lanes:
    nm = r.get('tolofNm') or ''
    k = norm(nm)
    if k not in L:
        miss.append(nm); continue
    s = ''.join(kind(r.get(f'odn{i}CrgwiClssNm')) for i in range(1, 31)).rstrip('X')
    if not s or not re.search('[HMB]', s): continue
    la, lo = L[k]
    key = (round(la, 5), round(lo, 5))
    e = out.setdefault(key, [key[0], key[1], k, 'O' if r.get('crgwKindNm') == '개방식' else 'C', {}])
    dn = (r.get('crgwDrnm') or '').strip()
    e[4][dn] = s
res = list(out.values())
# 상행 반대쪽(하행)은 서울에서 먼 쪽: 좌표 없이 남겨 두면 화면에서 상행이 아니면 하행
(ROOT / 'docs/hipass.json').write_text(json.dumps({'tg': res, 'dirc': DIRC}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('영업소', len(res), '방향', sum(len(e[4]) for e in res), '이름 못 맞춤', len(miss), sorted(set(miss))[:40])
