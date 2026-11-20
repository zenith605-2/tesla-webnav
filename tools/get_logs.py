"""주행 기록 내려받기: python3 tools/get_logs.py [YYYY-MM-DD]  → data/logs/<날짜>/*.json
페이지에서 ?log=1 로 켠 차의 기록만 있다. 필요: .admin_token (커밋 금지)"""
import json, sys, urllib.request, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
U = 'https://chgodrjjalsrgyxuwjyq.supabase.co/functions/v1/webnav/admin/logs'
TOK = (ROOT / '.admin_token').read_text().strip()
day = sys.argv[1] if len(sys.argv) > 1 else (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime('%Y-%m-%d')
def get(q):
    return urllib.request.urlopen(urllib.request.Request(U + q, headers={'x-admin': TOK}), timeout=60).read()
out = ROOT / 'data/logs' / day
out.mkdir(parents=True, exist_ok=True)
names = [x['name'] for x in json.loads(get('?d=' + day)) if x['name'].endswith('.json')]
for n in names:
    p = out / n
    if not p.exists():
        p.write_bytes(get('?f=' + day + '/' + n))
print(len(names), '개 →', out)
