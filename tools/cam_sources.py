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
    return raw
