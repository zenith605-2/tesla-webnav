# tesla-webnav

테슬라 브라우저용 웹 내비 시험판의 단속 카메라 데이터.

- `tools/fetch_cams.py`: 경찰청 전국무인교통단속카메라표준데이터(data.go.kr 15028200)를 받는다.
- `tools/build_cams.py docs/cams.json`: 가벼운 카메라 파일과 `cams-ver.json`(버전)을 만든다.
- `.github/workflows/cams.yml`: 매일 03:20(한국 시간)에 위 두 단계를 돌리고 바뀌었으면 올린다.
- `docs/` 는 GitHub Pages 로 제공된다.
