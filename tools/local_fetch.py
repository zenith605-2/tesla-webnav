"""공공데이터포털에 시·군·지방경찰청이 따로 올린 단속카메라 파일을 모아 data/raw/local/ 에 받는다 (11/22).
표준데이터(15028200)에 빠진 카메라를 찾는 대조용. 주정차·버스전용·번호인식·방범 CCTV 는 뺌.
받는 법: 상세 페이지의 publicDataDetailPk → POST /tcs/dss/selectFileDataDownload.do → atchFileId → /cmm/cmm/fileDownload.do
"""
import json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / 'data/raw/local'
D.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0'}


def get(u, data=None, raw=False):
    req = urllib.request.Request(u, data=data, headers=UA)
    r = urllib.request.urlopen(req, timeout=60).read()
    return r if raw else r.decode('utf-8', 'ignore')


seen = {}
for kw in ('무인교통단속카메라', '무인단속카메라', '단속카메라', '과속단속', '무인단속장비', '교통단속 카메라', '신호위반 단속'):
    for pg in range(1, 25):
        t = get('https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=FILE&keyword=' + urllib.parse.quote(kw) + f'&currentPage={pg}&perPage=40')
        items = re.findall(r'<a href="/data/(\d+)/fileData\.do">(.*?)</a>', t, re.S)
        if not items: break
        for i, ti in items:
            seen.setdefault(i, re.sub(r'<[^>]+>|\s+', ' ', ti).strip())
        time.sleep(0.3)
SKIP = r'주정차|주차|번호인식|방범|쓰레기|버스전용|5등급|운행차|이동식|이동형|연도별|운영대수|단속 현황|단속현황|건수|실적|과태료|SHP|통계'
rel = {k: v for k, v in seen.items() if re.search(r'단속', v) and re.search(r'카메라|과속|무인|장비|CCTV', v) and not re.search(SKIP, v)}
print('찾음', len(seen), '받을 것', len(rel))
meta = {}
for pk, ti in sorted(rel.items()):
    try:
        h = get(f'https://www.data.go.kr/data/{pk}/fileData.do')
        m = re.search(r'publicDataDetailPk" name="publicDataDetailPk" value="([^"]+)', h)
        tt = re.search(r'<title>([^<|]+)', h)
        name = (tt.group(1).strip() if tt else ti)
        if not m: continue
        j = json.loads(get('https://www.data.go.kr/tcs/dss/selectFileDataDownload.do', urllib.parse.urlencode(
            {'publicDataPk': pk, 'publicDataDetailPk': m.group(1), 'fileDetailSn': '1', 'publicDataTyCode': 'PR0051'}).encode()))
        if not j.get('atchFileId'): continue
        b = get(f"https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={j['atchFileId']}&fileDetailSn={j.get('fileDetailSn') or 1}", raw=True)
        ext = 'xlsx' if b[:2] == b'PK' else 'csv'
        fn = re.sub(r'[\\/:*?"<>|]', '_', name)[:90] + '.' + ext
        (D / fn).write_bytes(b)
        meta[pk] = {'name': name, 'file': fn, 'size': len(b)}
        print('받음', fn, len(b))
    except Exception as e:
        print('실패', pk, ti[:40], str(e)[:60])
    time.sleep(0.6)
json.dump(meta, open(D / '_meta.json', 'w'), ensure_ascii=False, indent=1)
print('파일', len(meta))
