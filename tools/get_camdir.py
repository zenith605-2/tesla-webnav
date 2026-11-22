"""방향 확인 도구(tsnavi/check.html) 결과를 받아 tools/cam_checked.json 으로 저장 (11/22).
build_cams.py 가 씀: 숫자 = 사람이 로드뷰로 본 단속 방향(무엇보다 우선), 'none' = 카메라 없음(뺌), 'both' = 양방향(방향 -1 유지), 'badpos' = 좌표가 길 위가 아님(아직 그대로 둠, 목록만).
사용: python3 tools/get_camdir.py   (필요: .log_token)
"""
import json, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TOK = (ROOT / '.log_token').read_text().strip()
d = json.loads(urllib.request.urlopen(urllib.request.Request('https://tsnavi-relay.zenithworks.workers.dev/camdir', headers={'x-log': TOK, 'User-Agent': 'tsnavi-tools'}), timeout=30).read())
(ROOT / 'tools/cam_checked.json').write_text(json.dumps(d, ensure_ascii=False, indent=0))
vals = [x['v'] if isinstance(x, dict) else x for x in d.values()]
print('위치 고침', sum(1 for x in d.values() if isinstance(x, dict)))
print('확인 결과', len(d), '곳 (방향', sum(1 for v in vals if isinstance(v, (int, float))), '· 없음', sum(1 for v in vals if v == 'none'), '· 양방향', sum(1 for v in vals if v == 'both'), ')')
