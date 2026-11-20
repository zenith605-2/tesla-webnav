"""내비 안내 음성 조각 만들기 (제미나이 TTS, 리도 Supabase 중계의 관리자 경로 사용).

각 조각을 한 번만 만들어 actparty-site/t/vo/<키>.m4a 로 저장하고, 페이지가 이어 붙여 재생한다.
  python3 tools/make_voice.py            # 없는 것만 만들기
  python3 tools/make_voice.py --force    # 전부 다시
  python3 tools/make_voice.py --voice Aoede
필요: tesla-webnav/.admin_token (WEBNAV_ADMIN 과 같은 값, 커밋 금지), ffmpeg
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / 'actparty-site/t/vo'
RAW = ROOT / 'data/voice/raw'
URL = 'https://chgodrjjalsrgyxuwjyq.supabase.co/functions/v1/webnav/admin/tts'
MODEL = 'gemini-3.8-flash-tts'
VOICE = sys.argv[sys.argv.index('--voice') + 1] if '--voice' in sys.argv else 'Kore'
FORCE = '--force' in sys.argv

DISTS = list(range(50, 1001, 50)) + [1500, 2000]
TT = {11: '직진', 12: '좌회전', 13: '우회전', 14: '유턴', 16: '8시 방향 좌회전', 17: '10시 방향 좌회전', 18: '2시 방향 우회전',
      19: '4시 방향 우회전', 101: '오른쪽 고속도로 입구', 102: '왼쪽 고속도로 입구', 103: '고속도로 입구', 104: '오른쪽 고속도로 출구',
      105: '왼쪽 고속도로 출구', 106: '고속도로 출구', 111: '오른쪽 도시고속도로 입구', 112: '왼쪽 도시고속도로 입구', 113: '도시고속도로 입구',
      114: '오른쪽 도시고속도로 출구', 115: '왼쪽 도시고속도로 출구', 116: '도시고속도로 출구', 117: '오른쪽 방향', 118: '왼쪽 방향',
      119: '지하차도', 120: '고가도로', 121: '터널', 122: '교량', 123: '지하차도 옆길', 124: '고가도로 옆길', 131: '회전교차로',
      185: '경유지', 201: '목적지'}


def dist_ko(n):
    if n < 1000:
        return f'{n}미터'
    return {1000: '1킬로미터', 1500: '1.5킬로미터', 2000: '2킬로미터'}[n]


def phrases():
    p = {}
    for n in DISTS:
        p[f'd{n}'] = f'전방 {dist_ko(n)},'
        p[f'a{n}'] = f'{dist_ko(n)} 앞'
    for n in range(20, 121, 10):
        p[f'lim{n}'] = f'제한속도 {n},'
    p.update({
        'cam_s': '과속 단속 카메라입니다.', 'cam_sig': '신호 단속 카메라입니다.', 'cam_sx': '신호 과속 단속 카메라입니다.',
        'sec_start': '구간 단속 시작입니다.', 'sec_end': '구간 단속이 끝났습니다.', 'child': '어린이 보호구역,',
        'reroute': '경로를 다시 찾습니다.', 'arrive': '목적지에 도착했습니다.', 'via_arrive': '경유지에 도착했습니다.',
        'via_add': '경유지를 추가했습니다.', 'start': '경로 안내를 시작합니다.',
    })
    for code, name in TT.items():
        p[f't{code}'] = f'{name}입니다.'
    return p


def tts(text):
    tok = (ROOT / '.admin_token').read_text().strip()
    body = json.dumps({'text': text, 'voice': VOICE, 'model': MODEL}).encode()
    for i in range(10):
        try:
            req = urllib.request.Request(URL, data=body, headers={'x-admin': tok, 'Content-Type': 'application/json'})
            d = json.load(urllib.request.urlopen(req, timeout=120))
            return base64.b64decode(d['data'])
        except Exception as e:  # 한도·일시 오류면 쉬었다가 다시
            print('  재시도', i + 1, text, e)
            time.sleep(min(60, 6 * (i + 1)))
    raise SystemExit('실패: ' + text)


def make(item):
    key, text = item
    out = OUT / f'{key}.m4a'
    if out.exists() and not FORCE:
        return key, 'skip'
    wav = RAW / f'{key}.wav'
    if not wav.exists() or FORCE:
        wav.write_bytes(tts(text))
    # 앞뒤 무음 자르고 10% 빠르게, 크기 고르게 → AAC 64k
    af = ('silenceremove=start_periods=1:start_threshold=-45dB,areverse,'
          'silenceremove=start_periods=1:start_threshold=-45dB,areverse,atempo=1.1,loudnorm=I=-15:TP=-1.5:LRA=7')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-af', af, '-ac', '1', '-ar', '24000',
                    '-c:a', 'aac', '-b:a', '64k', str(out)], check=True)
    return key, 'ok'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    p = phrases()
    with ThreadPoolExecutor(2) as ex:
        for key, st in ex.map(make, p.items()):
            if st == 'ok':
                print('만듦', key, p[key])
    (OUT / 'list.json').write_text(json.dumps({'voice': VOICE, 'model': MODEL, 'keys': sorted(p)}, ensure_ascii=False))
    total = sum(f.stat().st_size for f in OUT.glob('*.m4a'))
    print(len(p), '조각,', total // 1024, 'KB')


if __name__ == '__main__':
    main()
