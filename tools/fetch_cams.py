"""경찰청 전국무인교통단속카메라표준데이터(data.go.kr 15028200)를 받아 data/raw/cameras_all.json 에 저장.

공공데이터포털 화면의 다운로드 버튼이 쓰는 JSON 경로를 그대로 쓴다 (키 필요 없음).
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PK = '15028200'
BASE = 'https://www.data.go.kr'
HEAD = {'User-Agent': 'Mozilla/5.0', 'Referer': f'{BASE}/data/{PK}/standard.do', 'X-Requested-With': 'XMLHttpRequest'}


def get(url):
    req = urllib.request.Request(url, headers=HEAD)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    col = get(f'{BASE}/download/columList.json?pk={PK}&ext=JSON')
    t = col['tableVO']
    total = int(col['totalCount'])
    rows = []
    for page in range(1, total // 10000 + 2):
        q = [('colNmList', c) for c in t['colNmList']] + [
            ('totalCount', total), ('svcTableNm', t['svcTableNm']), ('perPage', 10000), ('page', page)]
        d = get(f'{BASE}/download/standard.json?publicDataPk={PK}&' + urllib.parse.urlencode(q))
        part = d if isinstance(d, list) else next(v for v in d.values() if isinstance(v, list))
        rows += part
        time.sleep(1)
    if len(rows) < total * 0.95:
        raise SystemExit(f'받은 행이 너무 적음: {len(rows)} / {total}')
    out = ROOT / 'data/raw/cameras_all.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    print('받음', len(rows), '/', total)


if __name__ == '__main__':
    main()
