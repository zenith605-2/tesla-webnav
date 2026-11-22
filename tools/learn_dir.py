"""주행 기록으로 '방향 모르는' 카메라의 단속 방향을 배운다 (11/22, 운전자 손 안 대고).

원리: 우측 통행이라 내 방향 카메라 기둥은 진행 방향 오른쪽(가까이)에 선다.
  카메라 옆(25m 안)을 지날 때 오른쪽 15m 안 → 내 진행 방향을 단속,  왼쪽 10m 넘게 → 맞은편 방향을 단속.
  -6~+3m 처럼 애매하면(도로 한가운데·좁은 길) 기록 안 함.
  같은 카메라에서 방향이 2번 이상 30° 안으로 맞으면 확정 → tools/cam_learned.json {"위도,경도": 방위각}
  build_cams.py 가 방향 모르는(-1) 카메라에만 씀. 관측은 data/learn_obs.json 에 쌓음(같은 날 같은 카메라는 1번만).
사용: python3 tools/learn_dir.py 2026-11-22 [2026-11-21 ...]
"""
import json, math, sys, glob
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
C = json.load(open(ROOT / 'docs/cams.json'))
OBS_F, OUT = ROOT / 'data/learn_obs.json', ROOT / 'tools/cam_learned.json'
OBS = json.load(open(OBS_F)) if OBS_F.exists() else {}
G = {}
for c in C:
    G.setdefault((round(c[0], 2), round(c[1], 2)), []).append(c)


def dist(a, b, c, d):
    x = (d - b) * math.cos(math.radians((a + c) / 2)) * 111320
    return math.hypot(x, (c - a) * 111320)


def brg(a, b, c, d):
    y = math.sin(math.radians(d - b)) * math.cos(math.radians(c))
    x = math.cos(math.radians(a)) * math.sin(math.radians(c)) - math.sin(math.radians(a)) * math.cos(math.radians(c)) * math.cos(math.radians(d - b))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def adiff(a, b):
    return (b - a + 540) % 360 - 180


for day in sys.argv[1:]:
    rows = []
    for f in sorted(glob.glob(str(ROOT / f'data/logs/{day}/*.json'))):
        if Path(f).name.startswith('u'):
            continue  # 이용자 기록(동의분)은 쓰지 않음, 개발 차량 기록만
        try:
            rows += [r for r in json.load(open(f)).get('rows', []) if r[0] == 'f']
        except Exception:
            continue
    rows.sort(key=lambda r: r[1])
    best = {}  # 카메라별로 가장 가까이 지난 순간
    for r in rows:
        la, lo, h, v = r[2], r[3], r[5], r[6]
        if h is None or v is None or v < 3:
            continue
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for c in G.get((round(la, 2) + dy / 100, round(lo, 2) + dx / 100), []):
                    if c[7] != -1:
                        continue
                    d = dist(la, lo, c[0], c[1])
                    if d > 25:
                        continue
                    k = f'{c[0]},{c[1]}'
                    if k not in best or d < best[k][0]:
                        lat = d * math.sin(math.radians(adiff(h, brg(la, lo, c[0], c[1]))))
                        best[k] = (d, h, lat)
    n = 0
    for k, (d, h, lat) in best.items():
        if 3 < lat <= 15:
            b = round(h)
        elif lat < -10:
            b = round((h + 180) % 360)
        else:
            continue
        o = OBS.setdefault(k, {})
        o[day] = b
        n += 1
    print(day, '지나간 방향 모르는 카메라', len(best), '관측', n)

json.dump(OBS, open(OBS_F, 'w'))
learned = {}
for k, o in OBS.items():
    bs = list(o.values())
    for b in bs:
        agree = [x for x in bs if abs(adiff(b, x)) < 30]
        if len(agree) >= 2:
            learned[k] = round(sum(agree) / len(agree)) % 360 if max(agree) - min(agree) < 180 else b
            break
json.dump(learned, open(OUT, 'w'), indent=0)
print('확정', len(learned), '/ 관측한 카메라', len(OBS))
