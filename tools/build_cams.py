"""경찰청 무인단속카메라 표준데이터 -> 웹 네비용 가벼운 JSON.

입력: data/raw/cameras_all.json (data.go.kr 15028200)
출력: 지정한 경로에 [위도, 경도, 제한속도, 종류, 구간, 보호구역, 도로이름, 단속방향] 배열
  단속방향: 찍는 차의 진행 방위각(0~359), 모르면 -1. tools/build_cam_dir.py 가 오픈스트리트맵으로 계산한 tools/cam_dir.json (11/21)
  도로이름: 그 카메라가 단속하는 도로(ROAD_ROUTE_NM). 교차로에서 옆길을 찍는 카메라를 거르는 데 씀 (11/21)
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
    from cam_sources import load_raw  # 경찰청 + 경기도 추가분 (11/22)
    raw = load_raw()
    dp = ROOT / 'tools/cam_dir.json'
    DIR = json.load(open(dp)) if dp.exists() else {}
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
        road = (x.get('ROAD_ROUTE_NM') or '').strip().replace(' ', '')
        out.append([round(la, 5), round(lo, 5), lim, kind, sec, zone, road, DIR.get(f'{round(la, 5)},{round(lo, 5)}', -1)])
    # 주행 기록으로 배운 방향(tools/learn_dir.py → cam_learned.json): 방향 모르는(-1) 카메라에만 (11/22)
    lp = ROOT / 'tools/cam_learned.json'
    LEARN = json.load(open(lp)) if lp.exists() else {}
    for c in out:
        if c[7] == -1 and f'{c[0]},{c[1]}' in LEARN:
            c[7] = LEARN[f'{c[0]},{c[1]}']
    # 사람이 로드뷰로 확인한 결과(tools/get_camdir.py → cam_checked.json): 방향은 무엇보다 우선, 'none' 은 뺌 (11/22)
    kp = ROOT / 'tools/cam_checked.json'
    CHK = json.load(open(kp)) if kp.exists() else {}
    if CHK:
        keep = []
        for c in out:
            v = CHK.get(f'{c[0]},{c[1]}')
            if isinstance(v, dict):  # 지도에서 고친 실제 위치 (11/22)
                if v.get('fix'):
                    c[0], c[1] = round(v['fix'][0], 5), round(v['fix'][1], 5)
                v = v.get('v')
            if v == 'none':
                continue
            if isinstance(v, (int, float)):
                c[7] = int(v)
            keep.append(c)
        out = keep
    # 직접 확인한 카메라(tools/cam_extra.json): 경찰청 자료에 아직 없는 새 카메라. 같은 자리(30m)·같은 속도가 자료에 들어오면 자동으로 빠짐 (11/22)
    ep = ROOT / 'tools/cam_extra.json'
    for e in (json.load(open(ep, encoding='utf-8')) if ep.exists() else []):
        same = [c for c in out if abs(c[0] - e['la']) < 0.0003 and abs(c[1] - e['lo']) < 0.0004 and c[2] == e['lim']]
        if same:
            for c in same:  # 직접 확인한 방향이 있으면 그걸로 (예: 로드뷰로 본 옥정로2길 서쪽 전용)
                if e.get('dir', -1) >= 0:
                    c[7] = e['dir']
            continue
        out.append([e['la'], e['lo'], e['lim'], e.get('kind', 'S'), 0, e.get('zone', 0), e.get('road', ''), e.get('dir', -1)])
    body = json.dumps(out, separators=(',', ':'))
    Path(out_path).write_text(body, encoding='utf-8')
    ref = max((x.get('REFERENCE_DATE') or '') for x in raw)
    ver = {'ver': hashlib.sha1(body.encode()).hexdigest()[:10], 'ref': ref, 'count': len(out)}
    Path(out_path).with_name('cams-ver.json').write_text(json.dumps(ver), encoding='utf-8')
    print(len(raw), '->', len(out), 'cameras,', Path(out_path).stat().st_size // 1024, 'KB', ver)


if __name__ == '__main__':
    main(sys.argv[1])
