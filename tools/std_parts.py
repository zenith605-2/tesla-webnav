"""표준데이터 합본(fetch_cams.py)은 기관별 최신 파일을 늦게 따라간다 (11/22 확인: 양산시 합본 5월 기준, 기관 파일 11/16 등록).
표준데이터 상세의 '데이터 목록'(기관별 파일 126개)을 받아, 합본보다 기준일이 새로운 기관은 그 기관 행을 통째로 바꾼다.
data/raw/cameras_all.json 을 고쳐 씀. 매일 cams.yml 에서 fetch_cams.py 다음에 실행.
"""
import csv, io, json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data/raw/cameras_all.json'
UA = {'User-Agent': 'Mozilla/5.0'}
COL = {'무인교통단속카메라관리번호': 'MNLSS_REGLT_CAMERA_MANAGE_NO', '시도명': 'CTPRVN_NM', '시군구명': 'SIGNGU_NM', '도로종류': 'ROAD_KND',
       '도로노선번호': 'ROAD_ROUTE_NO', '도로노선명': 'ROAD_ROUTE_NM', '도로노선방향': 'ROAD_ROUTE_DRC', '소재지도로명주소': 'RDNMADR',
       '소재지지번주소': 'LNMADR', '위도': 'LATITUDE', '경도': 'LONGITUDE', '설치장소': 'ITLPC', '단속구분': 'REGLT_SE', '제한속도': 'LMTT_VE',
       '단속구간위치구분': 'REGLT_SCTN_LC_SE', '과속단속구간길이': 'OVRSPD_REGLT_SCTN_LT', '보호구역구분': 'PRTCAREA_TYPE',
       '설치연도': 'INSTALLATION_YEAR', '관리기관명': 'INSTITUTION_NM', '관리기관전화번호': 'PHONE_NUMBER', '데이터기준일자': 'REFERENCE_DATE'}


def get(u, data=None):
    return urllib.request.urlopen(urllib.request.Request(u, data=data, headers=UA), timeout=60).read()


parts = []
for p in range(1, 40):
    t = get(f'https://www.data.go.kr/tcs/dss/stdFileList.do?publicDataPk=15028200&pageIndex={p}&searchKeyword2=').decode('utf-8', 'ignore')
    got = re.findall(r'data-public-pk="([^"]+)"', t)
    if not got: break
    parts += [g for g in got if g not in parts]
    time.sleep(0.3)
raw = json.load(open(OUT, encoding='utf-8'))
latest = {}
for x in raw:
    k = (x.get('INSTITUTION_NM') or '').strip()
    latest[k] = max(latest.get(k, ''), x.get('REFERENCE_DATE') or '')
rep, newer = 0, {}
for pk in parts:
    try:
        j = json.loads(get('https://www.data.go.kr/tcs/dss/selectFileDataDownload.do', urllib.parse.urlencode(
            {'publicDataPk': '15028200', 'publicDataDetailPk': pk, 'fileDetailSn': '1', 'publicDataTyCode': 'PR0051'}).encode()))
        b = get(f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={j['atchFileId']}&fileDetailSn={j.get('fileDetailSn') or 1}")
    except Exception as e:
        print('실패', pk, str(e)[:60]); continue
    txt = None
    for enc in ('utf-8-sig', 'cp949'):
        try: txt = b.decode(enc); break
        except UnicodeDecodeError: pass
    if not txt: continue
    rows = [{COL.get(k.strip().lstrip('﻿'), k): (v or '').strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(txt))]
    for r in rows:  # 같은 기관이 여러 파일에 나뉘어 있음(경찰청은 시·군별 파일) → 기관별로 모두 모음, 같은 장비는 새 기준일
        inst = r.get('INSTITUTION_NM', '')
        if not inst: continue
        m = newer.setdefault(inst, {})
        k = r.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or (r.get('LATITUDE'), r.get('LONGITUDE'), r.get('LMTT_VE'))
        if k not in m or r.get('REFERENCE_DATE', '') > m[k].get('REFERENCE_DATE', ''): m[k] = r
    time.sleep(0.4)
cnt = {}
for x in raw:
    k = (x.get('INSTITUTION_NM') or '').strip(); cnt[k] = cnt.get(k, 0) + 1
upd = {}
for inst, m in newer.items():
    d = max(r.get('REFERENCE_DATE', '') for r in m.values())
    if d > latest.get(inst, ''): upd[inst] = (d, m)
newer = upd
if newer:
    keep, summary = [], []
    for x in raw:
        inst = (x.get('INSTITUTION_NM') or '').strip()
        if inst not in newer: keep.append(x); continue
        d, m = newer[inst]
        if len(m) >= 0.9 * cnt.get(inst, 0): continue  # 기관 전체가 담긴 파일 → 통째로 바꿈
        k = x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or (x.get('LATITUDE'), x.get('LONGITUDE'), x.get('LMTT_VE'))
        if k in m and m[k].get('REFERENCE_DATE', '') > (x.get('REFERENCE_DATE') or ''): continue  # 새 행으로 바꿈
        if k in m: m.pop(k)  # 합본 쪽이 같거나 새로움
        keep.append(x)
    for inst, (d, m) in newer.items():
        keep += list(m.values())
        summary.append(f"{inst}: 합본 {latest.get(inst, '없음')} {cnt.get(inst, 0)}행 → 기관 파일 {d} {len(m)}행 ({'통째로' if len(m) >= 0.9 * cnt.get(inst, 0) else '장비별 갱신'})")
    if len(keep) < len(raw) * 0.97:
        raise SystemExit(f'행이 너무 많이 줄어 중단: {len(raw)} → {len(keep)}')
    OUT.write_text(json.dumps(keep, ensure_ascii=False), encoding='utf-8')
    print('\n'.join(summary))
print('기관 파일', len(parts), '더 새로운 기관', len(newer), '행', len(raw), '→', len(keep) if newer else len(raw))
