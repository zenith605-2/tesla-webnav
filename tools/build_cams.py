"""경찰청 무인단속카메라 표준데이터 -> 웹 네비용 가벼운 JSON.

입력: data/raw/cameras_all.json (data.go.kr 15028200)
출력: 지정한 경로에 [위도, 경도, 제한속도, 종류, 구간, 보호구역] 배열
  종류: 'S' 과속, 'X' 신호+과속, 'R' 신호만(제한속도 없음)
  단속구분 4 이면서 제한속도 없음 = 주정차 등 기타 단속으로 보고 뺀다
  (공식 코드표 미확인. 2026-11-20 분당 데이터 대조: 4·0 은 시장앞·은행앞, 2 는 교차로 '신호과속')
  구간: 0 없음, 1 구간단속 시작, 2 구간단속 끝
  보호구역: 0 없음, 1 노인 등, 2 어린이
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(out_path):
    raw = json.load(open(ROOT / 'data/raw/cameras_all.json', encoding='utf-8'))
    out, seen = [], set()
    for x in raw:
        try:
            la, lo = float(x['LATITUDE']), float(x['LONGITUDE'])
        except ValueError:
            continue
        if not (33 < la < 39 and 124 < lo < 132):
            continue
        lim_s = x['LMTT_VE'].strip()
        lim = int(lim_s) if lim_s.isdigit() else 0
        se = x['REGLT_SE'].strip().lstrip('0')
        if lim == 0 and se in ('4', '99', ''):
            continue
        if lim == 0:
            kind = 'R'
        elif se in ('2', '1+2', '1+02', '3'):
            kind = 'X'
        else:
            kind = 'S'
        sec = {'1': 1, '01': 1, '2': 2, '02': 2}.get(x['REGLT_SCTN_LC_SE'].strip(), 0)
        zone = {'2': 2, '02': 2, '1': 1, '01': 1}.get(x['PRTCAREA_TYPE'].strip(), 0)
        key = (round(la, 5), round(lo, 5), lim, sec)
        if key in seen:
            continue
        seen.add(key)
        out.append([round(la, 5), round(lo, 5), lim, kind, sec, zone])
    body = json.dumps(out, separators=(',', ':'))
    Path(out_path).write_text(body, encoding='utf-8')
    ref = max((x.get('REFERENCE_DATE') or '') for x in raw)
    ver = {'ver': hashlib.sha1(body.encode()).hexdigest()[:10], 'ref': ref, 'count': len(out)}
    Path(out_path).with_name('cams-ver.json').write_text(json.dumps(ver), encoding='utf-8')
    print(len(raw), '->', len(out), 'cameras,', Path(out_path).stat().st_size // 1024, 'KB', ver)


if __name__ == '__main__':
    main(sys.argv[1])
