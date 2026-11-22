#!/bin/bash
# 주행 기록 재생 시험: run.sh <날짜> <세션> <nav 0|1>
# 로그 f 행을 4배속으로 페이지에 넣고 analyze.py 로 놓침·헛경고·반대방향을 센다
set -e
D=$1; SID=$2; NAV=$3
TW=/Users/zenith/Game_Project/tesla-webnav
ZW=/Users/zenith/Game_Project/zenithworks
S=/private/tmp/claude-501/-Users-zenith-Game-Project/927670cb-06ba-4eed-ac28-d97237911df6/scratchpad/rep
mkdir -p $S
python3 - "$D" "$SID" <<'EOF'
import json,glob,sys
d,sid=sys.argv[1],sys.argv[2]
rows=[]
for f in sorted(glob.glob(f'/Users/zenith/Game_Project/tesla-webnav/data/logs/{d}/{sid}-*.json')):
    rows+=[[r[1],r[2],r[3],r[4],r[5],r[6]] for r in json.load(open(f))['rows'] if r[0]=='f']
rows.sort(key=lambda r:r[0])
# 0.1초 간격으로 오는 위치는 0.5초마다 하나만 (재생 속도)
out=[];lt=0
for r in rows:
    if r[0]-lt>=500: out.append(r); lt=r[0]
json.dump(out,open(f'/Users/zenith/Game_Project/zenithworks/tsnavi/_rep_{sid}.json','w'))
print('rows',len(out))
EOF
JS=$(python3 -c "
import json,sys
s=open('$TW/tools/qa/replay/replay.js').read().replace('__F__','4').replace('__SID__','$SID').replace('__NAV__','$NAV')
print(json.dumps([{'wait':9000,'name':'REP_${SID}_${NAV}','js':s}]))")
echo "$JS" > $S/rep_${SID}_${NAV}.json
cd $ZW && (python3 -m http.server 8813 >/dev/null 2>&1 &) ; sleep 1
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CH" --headless=new --remote-debugging-port=9334 --user-data-dir=$S/prof_$SID --window-size=1280,800 about:blank >/dev/null 2>&1 &
sleep 2
timeout 1500 node $TW/tools/qa/cdp_test.mjs "http://localhost:8813/tsnavi/index.html?nocache=$RANDOM" $S $S/rep_${SID}_${NAV}.json > $S/out_${SID}_${NAV}.txt 2>&1 || true
pkill -f "remote-debugging-port=9334" || true
pkill -f "http.server 8813" || true
python3 $TW/tools/qa/replay/analyze.py $SID $NAV
