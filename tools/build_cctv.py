"""전국 도로 CCTV 목록(국가교통정보센터 ITS) -> 웹 내비용 칸 파일.

ITS 는 클라우드 서버(Supabase·GitHub Actions) 접속을 막아서, 이 스크립트는 국내 집 맥에서 돌린다.
영상 주소(cctvurl)는 받을 때마다 같고(접속 때 서명된 주소로 넘겨줌), 고속도로(ex)+국도(its) 2회 호출로 전국을 받는다.
출력: docs/cctv/<위도칸>_<경도칸>.json  [[위도, 경도, 이름, 주소, 'ex'|'its'], ...]  (0.5° 칸)
      docs/cctv-ver.json  {"ver", "n", "at"}
필요: .its_key (커밋 금지)
사용: python3 tools/build_cctv.py            (받고 만들기)
      python3 tools/build_cctv.py --push     (만들고 tesla-webnav 저장소에 올리기)
"""
import hashlib, json, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
KEY = (ROOT / '.its_key').read_text().strip()
OUT = ROOT / 'docs/cctv'

def fetch(t):
    u = (f'https://openapi.its.go.kr:9443/cctvInfo?apiKey={KEY}&type={t}&cctvType=4'
         '&minX=124&maxX=132&minY=33&maxY=39&getType=json')
    with urllib.request.urlopen(u, timeout=120) as r:
        return json.load(r)['response']['data']

rows = []
for t in ('ex', 'its'):
    for c in fetch(t):
        try:
            la, lo = float(c['coordy']), float(c['coordx'])
        except (TypeError, ValueError):
            continue
        if not (33 < la < 39 and 124 < lo < 132) or not c.get('cctvurl', '').startswith('https://'):
            continue
        rows.append([round(la, 5), round(lo, 5), (c.get('cctvname') or '').strip(), c['cctvurl'], t])
if len(rows) < 5000:
    raise SystemExit(f'CCTV 너무 적음: {len(rows)}')
OUT.mkdir(parents=True, exist_ok=True)
for f in OUT.glob('*.json'):
    f.unlink()
tiles = {}
for r in rows:
    tiles.setdefault(f'{int(r[0] * 2) / 2:.1f}_{int(r[1] * 2) / 2:.1f}', []).append(r)
for k, v in tiles.items():
    (OUT / f'{k}.json').write_text(json.dumps(v, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
body = json.dumps(sorted(rows), ensure_ascii=False)
ver = {'ver': hashlib.sha1(body.encode()).hexdigest()[:10], 'n': len(rows), 'tiles': len(tiles), 'at': time.strftime('%Y-%m-%d %H:%M')}
(ROOT / 'docs/cctv-ver.json').write_text(json.dumps(ver), encoding='utf-8')
print('CCTV', len(rows), '곳,', len(tiles), '칸', ver)
if '--push' in sys.argv:
    g = lambda *a: subprocess.run(['git', '-C', str(ROOT), *a], check=True)
    if subprocess.run(['git', '-C', str(ROOT), 'diff', '--quiet', '--', 'docs/cctv', 'docs/cctv-ver.json']).returncode == 0 and \
       not subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--others', '--exclude-standard', 'docs/cctv'], capture_output=True, text=True).stdout:
        print('변화 없음'); sys.exit()
    g('pull', '--rebase', '-q'); g('add', 'docs/cctv', 'docs/cctv-ver.json')
    g('commit', '-q', '-m', 'CCTV 목록 갱신 ' + ver['at']); g('push', '-q'); print('올림')
