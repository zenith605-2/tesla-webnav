"""주행 기록·의견 내려받기 (Cloudflare Workers 중계의 KV).
  python3 tools/get_logs.py [YYYY-MM-DD]   → data/logs/<날짜>/*.json  (주행 기록)
  python3 tools/get_logs.py fb             → data/feedback/*.json     (의견 보내기 전부)
필요: .admin_token (커밋 금지)"""
import datetime, json, sys, urllib.parse, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
U = 'https://tsnavi-relay.zenithworks.workers.dev/admin/logs'
TOK = (ROOT / '.admin_token').read_text().strip()
arg = sys.argv[1] if len(sys.argv) > 1 else (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
def get(q):
    return urllib.request.urlopen(urllib.request.Request(U + q, headers={'x-admin': TOK, 'User-Agent': 'tsnavi-tools'}), timeout=60).read()
prefix, out = ('fb/', ROOT / 'data/feedback') if arg == 'fb' else (f'log/{arg}/', ROOT / 'data/logs' / arg)
out.mkdir(parents=True, exist_ok=True)
keys = [x['name'] for x in json.loads(get('?d=' + urllib.parse.quote(prefix)))]
for k in keys:
    p = out / (k.split('/')[-1] + '.json')
    if not p.exists():
        p.write_bytes(get('?f=' + urllib.parse.quote(k)))
print(len(keys), '개 →', out)
if arg == 'fb':
    for p in sorted(out.glob('*.json'))[-20:]:
        d = json.loads(p.read_text())
        print(d.get('at', '')[:16], '|', d.get('text', ''))
