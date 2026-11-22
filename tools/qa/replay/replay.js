(async function(){
  var b=[].slice.call(document.querySelectorAll('button')).find(function(x){return x.textContent.indexOf('확인하고 시작')>=0});if(b)b.click();
  var F=__F__,rows=await (await fetch('/tsnavi/_rep___SID__.json')).json();
  window.REP={al:{},err:[]};addEventListener('error',function(e){REP.err.push(String(e.message))});
  window.NOLIM=1;
  if(__NAV__){var L=rows[rows.length-1];onFix(rows[0][1],rows[0][2],5,rows[0][4],0,Date.now());startNav({name:'끝',la:L[1],lo:L[2]});await new Promise(function(r){setTimeout(r,8000)});$('rtGo').click();await new Promise(function(r){setTimeout(r,3000)})}
  var t0=rows[0][0],s0=performance.now(),i=0,rr=0,R0=NAV&&NAV.R;
  await new Promise(function(done){var iv=setInterval(function(){var lt=t0+(performance.now()-s0)*F;
    while(i<rows.length&&rows[i][0]<=lt){var r=rows[i++];onFix(r[1],r[2],r[3],r[4],r[5]==null?null:r[5]*F,Date.now())}
    if(NAV&&NAV.R!==R0){rr++;R0=NAV.R}
    if(target&&fix){var id=target.id,c=CAMS[id],d=dist(fix.la,fix.lo,c[0],c[1]),aD=alertFor(c[2]);var A=REP.al[id]||(REP.al[id]={la:c[0],lo:c[1],lim:c[2],dir:c[7],first:Math.round(d),min:1e9,warn:0,t:rows[Math.max(0,i-1)][0]});A.min=Math.min(A.min,Math.round(d));if(d<=aD)A.warn=1}
    if(i>=rows.length){clearInterval(iv);done()}},100)});
  return JSON.stringify({al:REP.al,reroute:rr,errN:errN,lastErr:lastErr,err:REP.err.slice(0,5)})
})()
