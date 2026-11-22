"""한국도로교통공단 블로그(koroadblog)의 월별 '신규 단속카메라 설치장소 공개' 글에서 엑셀 첨부를 받아
data/raw/koroad/ 에 넣는다. 이미 받은 파일 이름은 건너뜀 (11/22).
매달 한 번: python3 tools/koroad_fetch.py && .venv/bin/python tools/koroad.py && python3 tools/build_cams.py docs/cams.json
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / 'data/raw/koroad'
D.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (iPhone)', 'Referer': 'https://m.blog.naver.com/koroadblog'}


def get(u, raw=False):
    r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
    return r if raw else r.decode('utf-8', 'ignore')


posts = {}
for q in ('교통과학장비', '단속카메라'):
    for pg in range(1, 15):
        d = json.loads(get(f'https://m.blog.naver.com/api/blogs/koroadblog/search/post?query={urllib.parse.quote(q)}&page={pg}'))
        L = d['result'].get('list') or []
        if not L: break
        for x in L:
            ti = re.sub('<[^>]+>', '', x.get('title') or '')
            if re.search(r'20\d\d\s*년\s*\d+\s*월', ti) and '카메라' in ti:
                posts[str(x['logNo'])] = ti
        time.sleep(0.4)
have = {p.name for p in D.glob('*.xlsx')}
new = 0
for no, ti in sorted(posts.items()):
    try:
        h = get(f'https://m.blog.naver.com/PostView.naver?blogId=koroadblog&logNo={no}')
    except Exception:
        continue
    for u in sorted(set(re.findall(r'https://download\.blog\.naver\.com/open/[^"\' ]+\.xlsx', h))):
        fn = urllib.parse.unquote(u.rsplit('/', 1)[1]).strip()
        if fn in have: continue
        try:
            b = get(u, raw=True)
        except Exception:
            continue
        if b[:2] != b'PK': continue  # 엑셀(zip) 아님
        (D / fn).write_bytes(b); have.add(fn); new += 1
        print('받음', fn)
        time.sleep(0.8)
    time.sleep(0.5)
print('글', len(posts), '새 파일', new, '전체', len(have))
