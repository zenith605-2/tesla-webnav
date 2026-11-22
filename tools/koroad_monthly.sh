#!/bin/bash
# 매달 한 번 (launchd com.zenith.tsnavi-koroad, 매달 25일 09:30): 한국도로교통공단 블로그 새 월별 목록을 받아
# 표준데이터에 아직 없는 신규·이전·속도변경을 cams.json 에 반영하고 tesla-webnav 에 올린다 (11/22 사용자 요청)
set -e
cd /Users/zenith/Game_Project/tesla-webnav
LOG=data/koroad_monthly.log
{
  echo "== $(date '+%F %T')"
  python3 tools/koroad_fetch.py
  .venv/bin/python tools/koroad.py 2>&1 | grep -v -i warn
  python3 tools/build_cams.py docs/cams.json | tail -1
  if ! git diff --quiet -- tools/cam_koroad.json docs/cams.json docs/cams-ver.json; then
    git add tools/cam_koroad.json docs/cams.json docs/cams-ver.json
    git commit -qm "공단 월별 단속카메라 목록 자동 반영 ($(date +%Y-%m))"
    git push -q && echo "올림"
  else
    echo "바뀐 것 없음"
  fi
} >> "$LOG" 2>&1
