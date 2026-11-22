"""카메라 원본 읽기: 경찰청 전국 표준데이터 + 경기데이터드림에만 있는 카메라(tools/cam_gg.tsv) (11/22).

cam_gg.tsv: 경기데이터드림 「무인 교통단속 카메라 현황(제공표준)」(경찰청 제공, 2025-09 기준) 중
경찰청 전국 자료에 장비번호가 없는 과속 카메라 291대. 열: 장비번호 위도 경도 제한속도 단속구분 보호구역 도로명 설치장소
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_raw():
    raw = json.load(open(ROOT / 'data/raw/cameras_all.json', encoding='utf-8'))
    have = {(x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or '').strip() for x in raw}
    gp = ROOT / 'tools/cam_gg.tsv'
    if gp.exists():
        for line in gp.read_text(encoding='utf-8').splitlines():
            f = line.split('\t')
            if len(f) < 8 or f[0] in have:
                continue
            plc = f[7]
            raw.append({'MNLSS_REGLT_CAMERA_MANAGE_NO': f[0], 'LATITUDE': f[1], 'LONGITUDE': f[2], 'LMTT_VE': f[3],
                        'REGLT_SE': '1' if f[4] == '99' else f[4], 'PRTCAREA_TYPE': f[5], 'ROAD_ROUTE_NM': f[6], 'ITLPC': plc,
                        'REGLT_SCTN_LC_SE': '1' if plc.startswith('시점') else '2' if plc.startswith('종점') else '',
                        'REFERENCE_DATE': '2025-09-08', 'SIGNGU_NM': '', 'CTPRVN_NM': '경기도', 'SRC': 'gg'})
    # 한국도로교통공단 월별 신규·이전·속도변경(tools/koroad.py → cam_koroad.json): 표준데이터가 아직 못 따라온 것만 (11/22)
    kp = ROOT / 'tools/cam_koroad.json'
    if kp.exists():
        by = {(x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or '').strip(): x for x in raw}
        for e in json.load(open(kp, encoding='utf-8')):
            x = by.get(e['id'])
            if x is not None and (x.get('REFERENCE_DATE') or '') >= e['date']:
                continue  # 표준데이터가 따라옴
            if e['act'] == 'speed' and x is not None:
                x['LMTT_VE'] = str(e['lim'])
            elif e['act'] == 'move' and x is not None:
                x['LATITUDE'], x['LONGITUDE'], x['ITLPC'] = str(e['la']), str(e['lo']), e['loc']
            elif e['act'] == 'new' and x is None:
                raw.append({'MNLSS_REGLT_CAMERA_MANAGE_NO': e['id'], 'LATITUDE': str(e['la']), 'LONGITUDE': str(e['lo']), 'LMTT_VE': str(e['lim']),
                            'REGLT_SE': e['se'], 'PRTCAREA_TYPE': e['zone'], 'ROAD_ROUTE_NM': '', 'ITLPC': e['loc'], 'REGLT_SCTN_LC_SE': e['sec'],
                            'REFERENCE_DATE': e['date'], 'SIGNGU_NM': '', 'CTPRVN_NM': '', 'SRC': 'koroad', 'DIRX': e.get('dir', -1)})
    # 지방경찰청 운영 장비 목록(tools/local_merge.py → cam_local.json): 장비번호가 표준데이터에 생기면 자동으로 빠짐 (11/22)
    lp = ROOT / 'tools/cam_local.json'
    if lp.exists():
        have2 = {(x.get('MNLSS_REGLT_CAMERA_MANAGE_NO') or '').strip() for x in raw}
        for e in json.load(open(lp, encoding='utf-8')):
            if e['id'] in have2: continue
            raw.append({'MNLSS_REGLT_CAMERA_MANAGE_NO': e['id'], 'LATITUDE': str(e['la']), 'LONGITUDE': str(e['lo']), 'LMTT_VE': str(e['lim']),
                        'REGLT_SE': e['se'], 'PRTCAREA_TYPE': e['zone'], 'ROAD_ROUTE_NM': '', 'ITLPC': e['loc'], 'REGLT_SCTN_LC_SE': e['sec'],
                        'REFERENCE_DATE': e.get('date') or '', 'SIGNGU_NM': '', 'CTPRVN_NM': '', 'SRC': 'local', 'DIRX': -1})
    return raw
