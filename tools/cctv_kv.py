"""CCTV 영상 주소를 자주 새로 받아 중계(Cloudflare KV)에 올린다 (11/22).

이유: ITS cctvurl 은 받을 때마다 끝의 인증 문자열이 바뀌고 하루 안에 만료된다(401).
      git(docs/cctv)에 자주 올리면 저장소가 매번 2.3MB 씩 커지므로, 중계 KV 한 칸에 통째로 넣는다.
      ITS 는 클라우드 IP 를 막아서 집 맥에서 돈다(launchd 3시간마다, ITS 호출 2회 → 월 약 480건, 한도 1,000).
형식: 첫 줄 = {"ver","at","n","idx":{"<칸>":[시작,길이]}} , 그 뒤 = 칸 JSON 들을 이어 붙인 글 (중계는 잘라서 내려줌)
필요: .its_key, .admin_token (커밋 금지)
사용: python3 tools/cctv_kv.py
"""
import hashlib, json, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
KEY = (ROOT / '.its_key').read_text().strip()
TOK = (ROOT / '.admin_token').read_text().strip()
RELAY = 'https://tsnavi-relay.zenithworks.workers.dev/'
LOG = ROOT / 'data/cctv_kv.log'


def log(s):
    line = time.strftime('%m-%d %H:%M ') + s
    print(line)
    with LOG.open('a') as f:
        f.write(line + '\n')


# 지난번 주소가 아직 살아 있는지(주소 수명 재기)
try:
    meta = json.loads(urllib.request.urlopen(urllib.request.Request(RELAY + 'cctv2/ver', headers={'User-Agent': 'tsnavi-tools'}), timeout=20).read())
    if meta.get('probe'):
        try:
            st = urllib.request.urlopen(urllib.request.Request(meta['probe'], headers={'User-Agent': 'Mozilla/5.0'}), timeout=20).status
        except urllib.error.HTTPError as e:
            st = e.code
        log(f'지난 주소({meta.get("at")}) 상태 {st}')
except Exception as e:
    log(f'지난 정보 없음 {e}')


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
    log(f'CCTV 너무 적음: {len(rows)}')
    raise SystemExit(1)
tiles = {}
for r in rows:
    tiles.setdefault(f'{int(r[0] * 2) / 2:.1f}_{int(r[1] * 2) / 2:.1f}', []).append(r)
parts, idx, pos = [], {}, 0
for k in sorted(tiles):
    s = json.dumps(tiles[k], ensure_ascii=False, separators=(',', ':'))
    idx[k] = [pos, len(s)]
    parts.append(s)
    pos += len(s)
body = ''.join(parts)
head = {'ver': hashlib.sha1(body.encode()).hexdigest()[:10], 'at': time.strftime('%Y-%m-%d %H:%M'), 'n': len(rows),
        'probe': rows[len(rows) // 2][3], 'idx': idx}
pack = json.dumps(head, ensure_ascii=False, separators=(',', ':')) + '\n' + body
req = urllib.request.Request(RELAY + 'admin/cctvpack', data=pack.encode(), method='POST',
                             headers={'x-admin': TOK, 'Content-Type': 'text/plain; charset=utf-8', 'User-Agent': 'tsnavi-tools'})
r = json.loads(urllib.request.urlopen(req, timeout=60).read())
log(f'올림 {len(rows)}곳 {len(tiles)}칸 {len(pack) // 1024}KB {r}')
