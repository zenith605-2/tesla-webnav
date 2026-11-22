// TS내비 중계 (Cloudflare Workers). 키는 Cloudflare 비밀 값에만 둔다: TMAP_KEY, ADMIN, LOG
//   /ping                 상태 (키 값은 돌려주지 않음)
//   /tmap/<경로>?<쿼리>    티맵 API 대신 호출 (허용 경로만)
//   /inc?lat&lon          티맵 교통정보에서 돌발(사고·공사·통제) 지점만 골라 줌 (3분 캐시)
//   /camfix (POST)        카메라 신고 → KV camfix/<날짜>-<시각>-<난수> (IP 당 하루 40건, 1년 보관)
//   /feedback (POST)      의견 보내기 → KV fb/<날짜>-<시각>-<난수>  (IP 당 하루 5건, 1,000자, 위치 없음)
//   /log (POST, k=LOG 또는 이용자 동의)    주행 기록 → KV log/<날짜>/<세션>-<시각>
//   /admin/logs (x-admin) ?d=접두어 목록, ?f=키 내용
// 무료 요금제는 한도를 넘으면 막힐 뿐 요금이 나가지 않는다.

const TMAP_PATHS = new Set(['pois', 'pois/search/around', 'routes', 'routes/prediction', 'geo/reversegeocoding', 'road/matchToRoads500', 'road/nearToRoad']);
const ORIGINS = ['https://zenithworks.app', 'https://www.zenithworks.app', 'https://actparty.app', 'null'];
// 한 사람(IP)이 무료 한도를 다 쓰지 못하게 하루 한도 (같은 서버 조각 안에서 세는 대략값)
const IP_DAY = { routes: 60, 'routes/prediction': 20, 'road/matchToRoads500': 20, feedback: 5, camfix: 40, log: 400, kakao: 60, naver: 40, ev: 400 };
const ipDay = new Map();
let day = '';
const incCache = new Map();

function cors(origin) {
  const ok = !origin || ORIGINS.includes(origin) || /^http:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?$/.test(origin);
  return {
    'Access-Control-Allow-Origin': ok ? (origin || '*') : 'https://zenithworks.app',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Accept, x-log, x-admin',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}
const json = (b, s, h) => new Response(JSON.stringify(b), { status: s, headers: { ...h, 'Content-Type': 'application/json; charset=utf-8' } });
const kst = () => new Date(Date.now() + 9 * 3600e3).toISOString();

function overDay(ip, what) {
  const today = kst().slice(0, 10);
  if (today !== day) { day = today; ipDay.clear(); }
  const k = ip + '|' + what, n = (ipDay.get(k) || 0) + 1;
  ipDay.set(k, n);
  if (ipDay.size > 50000) ipDay.clear();
  return n > IP_DAY[what];
}

// 티맵 무료 하루 한도 (SK open API 무료 요금제)
const QUOTA = { routes: 1000, traffic: 1000, match: 200, kakao: 20000, ev: 8000 }; // 카카오맵 무료 쿼터 월 300만(아이혜택 앱과 공유) 중 TS내비는 하루 2만(월 최대 60만)에서 스스로 멈춤
const evCache = new Map(); // statId → { t, v:[[충전기, 상태, 갱신, kW, 종류]] }
// 차량 연동 방: 폰(phone)이 보낸 속도·기어를 같은 QR 코드의 차 화면(car)에 그대로 넘김. 값은 메모리에만.
// 차량 연동 방: 폰(phone)이 보낸 속도·기어를 같은 QR 의 차 화면(car)에 넘김. 값은 메모리에만.
// 차 화면은 {use:<폰 id>} 로 "지금 운전자의 폰"을 고르고, 방은 그걸 모든 폰에 알려 다른 폰은 쉬게 한다.
export class LinkHub {
  constructor(ctx) { this.ctx = ctx; this.last = null; this.use = null; }
  _note() {
    const n = JSON.stringify({ hub: 1, phone: this.ctx.getWebSockets('phone').length, car: this.ctx.getWebSockets('car').length, use: this.use });
    for (const w of this.ctx.getWebSockets()) { try { w.send(n); } catch { /* 무시 */ } }
  }
  async fetch(req) {
    const role = new URL(req.url).searchParams.get('r') === 'car' ? 'car' : 'phone';
    const pair = new WebSocketPair();
    this.ctx.acceptWebSocket(pair[1], [role]);
    if (role === 'car' && this.last) { try { pair[1].send(this.last); } catch { /* 무시 */ } }
    this._note();
    return new Response(null, { status: 101, webSocket: pair[0] });
  }
  webSocketMessage(ws, msg) {
    if (typeof msg !== 'string' || msg.length > 300) return;
    if (this.ctx.getTags(ws).includes('car')) {
      let d; try { d = JSON.parse(msg); } catch { return; }
      if ('use' in d) { this.use = typeof d.use === 'string' && /^[A-Za-z0-9]{6,40}$/.test(d.use) ? d.use : null; this._note(); }
      return;
    }
    this.last = msg;
    for (const c of this.ctx.getWebSockets('car')) { try { c.send(msg); } catch { /* 무시 */ } }
  }
  webSocketClose(ws, code) {
    try { ws.close(code === 1005 ? 1000 : code, 'bye'); } catch { /* 무시 */ }
    this._note();
  }
}
export class Counter {
  constructor(ctx) { this.ctx = ctx; }
  async fetch(req) {
    const u = new URL(req.url), d = u.searchParams.get('d'), k = u.searchParams.get('k');
    if (u.pathname === '/getk') return new Response(String((await this.ctx.storage.get(d + '|' + k)) || 0));
    if (u.pathname === '/inc') { const key = d + '|' + k, n = ((await this.ctx.storage.get(key)) || 0) + 1; await this.ctx.storage.put(key, n); return new Response(String(n)); }
    const out = {};
    for (const q of Object.keys(QUOTA)) out[q] = (await this.ctx.storage.get(d + '|' + q)) || 0;
    return Response.json(out);
  }
}
// 무료 한도의 마지막 10%는 주인 차(x-log = LOG 키) 몫으로 남긴다 (11/22). 공개 이용자는 90%에서 멈춤
const PUBLIC_SHARE = 0.9;
function isOwner(req, env) { return !!env.LOG && req.headers.get('x-log') === env.LOG; }
async function usedToday(env) { try { return await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/get?d=' + kst().slice(0, 10))).json(); } catch { return {}; } }
const BUSY = '오늘은 이용자가 많아 무료 길 안내 한도(LIMIT)를 다 썼습니다';
function count(env, ctx, k, dkey) {
  if (!env.CNT) return;
  const stub = env.CNT.get(env.CNT.idFromName('day'));
  ctx.waitUntil(stub.fetch('https://cnt/inc?d=' + (dkey || kst().slice(0, 10)) + '&k=' + k).catch(() => {}));
}
// 네이버는 넘으면 요금이 나가므로 '달' 단위로 세서 5만에서 멈춘다 (무료 월 6만)
const NAVER_MONTH = 50000;
async function naverUsed(env) {
  try { const r = await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/getk?d=' + kst().slice(0, 7) + '&k=naver')).text(); return Number(r) || 0; } catch { return 0; }
}

export default {
  async fetch(req, env, ctx) {
    const h = cors(req.headers.get('origin'));
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: h });
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/+/, '');
    const ip = req.headers.get('cf-connecting-ip') || 'x';

    if (path === 'ping') return json({ ok: true, tmap: !!env.TMAP_KEY, kv: !!env.KV }, 200, h);
    if (path === 'quota') {
      // 오늘(한국 시간) 전체 이용자가 쓴 무료 호출 수와 한도
      let used = { routes: 0, traffic: 0, match: 0 };
      try { used = await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/get?d=' + kst().slice(0, 10))).json(); } catch { /* 없으면 0 */ }
      used.naverMonth = await naverUsed(env);
      const f = isOwner(req, env) ? 1 : PUBLIC_SHARE, lim = {};
      for (const [k, v] of Object.entries({ ...QUOTA, naverMonth: NAVER_MONTH })) lim[k] = Math.floor(v * f);
      return new Response(JSON.stringify({ date: kst().slice(0, 10), used, limit: lim }), { headers: { ...h, 'Content-Type': 'application/json', 'Cache-Control': 'private, max-age=30' } });
    }

    if (path.startsWith('admin/')) {
      const xa = req.headers.get('x-admin');
      // ADMIN = 도구용 긴 키, ADMIN_PW = 사용자가 정한 관리자 페이지 비밀번호
      if (!xa || !((env.ADMIN && xa === env.ADMIN) || (env.ADMIN_PW && xa === env.ADMIN_PW))) return json({ error: 'forbidden' }, 403, h);
      if (path === 'admin/logs') {
        const f = url.searchParams.get('f');
        if (f) { const v = await env.KV.get(f); return v == null ? json({ error: 'none' }, 404, h) : new Response(v, { headers: { ...h, 'Content-Type': 'application/json' } }); }
        const out = []; let cursor;
        do { const r = await env.KV.list({ prefix: url.searchParams.get('d') || '', cursor }); out.push(...r.keys.map((k) => ({ name: k.name }))); cursor = r.list_complete ? null : r.cursor; } while (cursor && out.length < 5000);
        return json(out, 200, h);
      }
      if (path === 'admin/feedback') {
        // 의견 최근 200개를 내용까지 한 번에 (최신순)
        const r = await env.KV.list({ prefix: 'fb/' });
        const keys = r.keys.map((k) => k.name).sort().reverse().slice(0, 200);
        const items = await Promise.all(keys.map(async (k) => { try { return { key: k, ...JSON.parse(await env.KV.get(k)) }; } catch { return { key: k }; } }));
        return json(items, 200, h);
      }
      if (path === 'admin/del' && req.method === 'POST') {
        const k = url.searchParams.get('k') || '';
        if (!/^(fb|log|camfix)\//.test(k)) return json({ error: 'bad key' }, 400, h);
        await env.KV.delete(k);
        return json({ ok: true }, 200, h);
      }
      return json({ error: '없는 경로' }, 404, h);
    }

    if (env.RL) { const { success } = await env.RL.limit({ key: ip }); if (!success) return json({ error: '잠시 뒤에 다시 시도해 주세요' }, 429, h); }

    if (path === 'feedback' && req.method === 'POST') {
      if (overDay(ip, 'feedback')) return json({ error: '오늘은 더 보낼 수 없습니다' }, 429, h);
      let b = {};
      try { b = await req.json(); } catch { return json({ error: 'bad' }, 400, h); }
      const text = String(b.text || '').trim().slice(0, 1000);
      if (text.length < 2) return json({ error: '내용이 없습니다' }, 400, h);
      const t = kst();
      await env.KV.put(`fb/${t.slice(0, 10)}-${t.slice(11, 19).replace(/:/g, '')}-${crypto.randomUUID().slice(0, 6)}`,
        JSON.stringify({ at: t, type: String(b.type || '의견').slice(0, 20), text,
          loc: b.loc && isFinite(b.loc.la) && isFinite(b.loc.lo) ? { la: Math.round(b.loc.la * 1e4) / 1e4, lo: Math.round(b.loc.lo * 1e4) / 1e4, h: isFinite(b.loc.h) ? Math.round(b.loc.h) : null } : null,
          ver: String(b.ver || '').slice(0, 40), ua: (req.headers.get('user-agent') || '').slice(0, 200) }));
      return json({ ok: true }, 200, h);
    }

    if (path === 'camfix' && req.method === 'POST') {
      // 카메라 신고: 지도 꾹 눌러 제한속도(lim, 0=신호만) 또는 '없음' (11/21). 누른 지점·가까운 카메라·차 진행 방향(h, hOk=달리는 중이라 믿을 만함)만, 차 위치는 저장 안 함
      if (overDay(ip, 'camfix')) return json({ error: '오늘은 더 보낼 수 없습니다' }, 429, h);
      let b = {};
      try { b = await req.json(); } catch { return json({ error: 'bad' }, 400, h); }
      const kind = b.kind === 'add' || b.kind === 'wrong' ? b.kind : null;
      const la = +b.la, lo = +b.lo;
      if (!kind || !isFinite(la) || !isFinite(lo) || la < 33 || la > 39 || lo < 124 || lo > 132) return json({ error: 'bad' }, 400, h);
      const cam = b.cam && isFinite(b.cam.la) && isFinite(b.cam.lo) ? { la: +(+b.cam.la).toFixed(5), lo: +(+b.cam.lo).toFixed(5), lim: +b.cam.lim || 0, dir: isFinite(b.cam.dir) ? +b.cam.dir : -1 } : null;
      const t = kst();
      await env.KV.put(`camfix/${t.slice(0, 10)}-${t.slice(11, 19).replace(/:/g, '')}-${crypto.randomUUID().slice(0, 6)}`,
        JSON.stringify({ at: t, kind, la: +la.toFixed(5), lo: +lo.toFixed(5), lim: Number.isInteger(+b.lim) && +b.lim >= 0 && +b.lim <= 130 ? +b.lim : null,
          h: b.h != null && isFinite(b.h) ? Math.round(b.h) % 360 : null, hOk: !!b.hOk, kmh: isFinite(b.kmh) ? Math.round(b.kmh) : null, cam, ver: String(b.ver || '').slice(0, 40) }),
        { expirationTtl: 60 * 60 * 24 * 365 });
      return json({ ok: true }, 200, h);
    }

    if (path === 'log' && req.method === 'POST') {
      // 개발용(k=LOG) 또는 이용자가 설정에서 직접 켠 [주행 기록 보내기] (11/22, 앞에 u 붙여 구분, IP 하루 400회)
      const dev = !!env.LOG && (req.headers.get('x-log') || url.searchParams.get('k')) === env.LOG;
      if (!dev && overDay(ip, 'log')) return json({ error: '오늘은 더 보낼 수 없습니다' }, 429, h);
      const body = await req.text();
      if (body.length > 400000) return json({ error: 'too big' }, 413, h);
      const sid = (dev ? '' : 'u') + (url.searchParams.get('sid') || 'x').replace(/[^a-z0-9]/gi, '').slice(0, 16), t = kst();
      await env.KV.put(`log/${t.slice(0, 10)}/${sid}-${t.slice(11, 19).replace(/:/g, '')}`, body, { expirationTtl: 60 * 60 * 24 * 60 });
      return json({ ok: true }, 200, h);
    }

    if (path === 'inc') {
      if (!env.TMAP_KEY) return json({ error: '서버에 티맵 키가 없습니다' }, 503, h);
      const la = Math.round(Number(url.searchParams.get('lat')) * 5) / 5, lo = Math.round(Number(url.searchParams.get('lon')) * 5) / 5;
      if (!(la > 33 && la < 39 && lo > 124 && lo < 132)) return json({ error: '좌표 오류' }, 400, h);
      const ck = la + ',' + lo, hit = incCache.get(ck);
      if (hit && Date.now() - hit.t < 300e3) return json(hit.d, 200, h);
      const cacheKey = new Request('https://cache.tsnavi/inc/' + ck), cache = caches.default;
      const cached = await cache.match(cacheKey);
      if (cached) { const d = await cached.json(); incCache.set(ck, { t: Date.now(), d }); return json(d, 200, h); }
      const r = await fetch('https://apis.openapi.sk.com/tmap/traffic?version=1&format=json&reqCoordType=WGS84GEO&resCoordType=WGS84GEO&zoomLevel=11&trafficType=AUTO&centerLat=' + la + '&centerLon=' + lo, { headers: { appKey: env.TMAP_KEY, Accept: 'application/json' } });
      count(env, ctx, 'traffic');
      if (!r.ok) return json({ error: 'HTTP ' + r.status }, 502, h);
      const d = await r.json();
      const out = (d.features || []).filter((f) => f.geometry?.type === 'Point' && f.properties?.isAccidentNode === 'Y').map((f) => {
        const p = f.properties, c = f.geometry.coordinates;
        return [Math.round(c[1] * 1e5) / 1e5, Math.round(c[0] * 1e5) / 1e5, p.accidentUpperName || '', p.accidentDetailName || '', String(p.description || '').split(' / ')[0].slice(0, 160)];
      });
      const res = { at: Date.now(), list: out };
      incCache.set(ck, { t: Date.now(), d: res });
      if (incCache.size > 200) incCache.clear();
      await cache.put(cacheKey, new Response(JSON.stringify(res), { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'max-age=300' } }));
      return json(res, 200, h);
    }

    // 차량 연동 웹소켓: /link/ws?c=<QR 코드 값>&r=car|phone
    if (path === 'link/ws') {
      if (!env.LINK) return json({ error: 'no link' }, 503, h);
      if (req.headers.get('upgrade') !== 'websocket') return json({ error: 'websocket only' }, 426, h);
      const c = url.searchParams.get('c') || '';
      if (!/^[A-Za-z0-9]{20,40}$/.test(c)) return json({ error: 'bad code' }, 400, h);
      if (url.searchParams.get('r') === 'car' && !/^https:\/\/(zenithworks\.app|zenith605-2\.github\.io)$/.test(req.headers.get('origin') || '')) return json({ error: 'forbidden' }, 403, h);
      return env.LINK.get(env.LINK.idFromName(c)).fetch(req);
    }

    // 환경부(한국환경공단) 충전기 실시간 상태 (비밀 값 EV_KEY). 충전소 번호로 묶어 5분 동안 같이 씀, 하루 8천 회에서 멈춤
    if (path === 'ev') {
      if (!env.EV_KEY) return json({ error: '서버에 충전기 키가 없습니다' }, 503, h);
      const ids = [...new Set((url.searchParams.get('ids') || '').split(',').filter((x) => /^[A-Z0-9]{2,14}$/.test(x)))].slice(0, 25);
      if (!ids.length) return json({}, 200, h);
      if (overDay(ip, 'ev')) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      const now = Date.now(), need = ids.filter((id) => { const c = evCache.get(id); return !c || now - c.t > 300000; });
      if (need.length) {
        let used = 0;
        try { used = (await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/get?d=' + kst().slice(0, 10))).json()).ev || 0; } catch { /* 카운터 실패해도 진행 */ }
        if (used + need.length <= QUOTA.ev) {
          await Promise.all(need.map(async (id) => {
            count(env, ctx, 'ev');
            try {
              const r = await fetch('https://apis.data.go.kr/B552584/EvCharger/getChargerInfo?serviceKey=' + env.EV_KEY + '&pageNo=1&numOfRows=100&dataType=JSON&statId=' + id, { signal: AbortSignal.timeout(8000) });
              const d = await r.json(), it = (d.items && d.items.item) || [];
              evCache.set(id, { t: Date.now(), v: it.map((x) => [x.chgerId, x.stat, x.statUpdDt, x.output || '', x.chgerType || '']) });
            } catch { /* 한 곳 실패는 건너뜀 */ }
          }));
          if (evCache.size > 20000) evCache.clear();
        }
      }
      const out = {};
      for (const id of ids) { const c = evCache.get(id); if (c) out[id] = { t: c.t, c: c.v }; }
      return json(out, 200, h);
    }

    // 카카오모빌리티 길찾기 (비밀 값 KAKAO_KEY). 하루 전체 3,000회에서 멈춤
    if (path === 'kakao/directions') {
      if (!env.KAKAO_KEY) return json({ error: '서버에 카카오 키가 없습니다' }, 503, h);
      if (overDay(ip, 'kakao')) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      try {
        const used = await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/get?d=' + kst().slice(0, 10))).json();
        if ((used.kakao || 0) >= QUOTA.kakao * (isOwner(req, env) ? 1 : PUBLIC_SHARE)) return json({ error: BUSY, busy: 1 }, 429, h);
      } catch { /* 카운터 실패해도 진행 */ }
      const q = new URLSearchParams();
      for (const k of ['origin', 'destination', 'waypoints', 'priority', 'car_fuel', 'avoid', 'alternatives', 'road_details', 'summary']) { const v = url.searchParams.get(k); if (v) q.set(k, v); }
      count(env, ctx, 'kakao');
      const r = await fetch('https://apis-navi.kakaomobility.com/v1/directions?' + q, { headers: { Authorization: 'KakaoAK ' + env.KAKAO_KEY } });
      return new Response(await r.arrayBuffer(), { status: r.status, headers: { ...h, 'Content-Type': 'application/json' } });
    }

    // 네이버 클라우드 Directions 5 (비밀 값 NAVER_ID·NAVER_SECRET). 달마다 5만에서 멈춤 → 요금 0원
    if (path === 'naver/driving') {
      if (!env.NAVER_ID || !env.NAVER_SECRET) return json({ error: '서버에 네이버 키가 없습니다' }, 503, h);
      if (overDay(ip, 'naver')) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      if ((await naverUsed(env)) >= NAVER_MONTH * (isOwner(req, env) ? 1 : PUBLIC_SHARE)) return json({ error: BUSY, busy: 1 }, 429, h);
      const q = new URLSearchParams();
      for (const k of ['start', 'goal', 'waypoints', 'option', 'cartype', 'fueltype', 'lang']) { const v = url.searchParams.get(k); if (v) q.set(k, v); }
      count(env, ctx, 'naver', kst().slice(0, 7));
      const r = await fetch('https://maps.apigw.ntruss.com/map-direction/v1/driving?' + q, { headers: { 'x-ncp-apigw-api-key-id': env.NAVER_ID, 'x-ncp-apigw-api-key': env.NAVER_SECRET } });
      return new Response(await r.arrayBuffer(), { status: r.status, headers: { ...h, 'Content-Type': 'application/json' } });
    }

    if (path.startsWith('tmap/')) {
      const p = path.slice(5);
      if (!TMAP_PATHS.has(p) && !/^pois\/\d+$/.test(p)) return json({ error: '허용되지 않은 경로' }, 404, h);
      if (IP_DAY[p] && overDay(ip, p)) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      if (!env.TMAP_KEY) return json({ error: '서버에 티맵 키가 없습니다' }, 503, h);
      if (p === 'routes' || p === 'routes/prediction') { const u = await usedToday(env); if ((u.routes || 0) >= QUOTA.routes * (isOwner(req, env) ? 1 : PUBLIC_SHARE)) return json({ error: BUSY, busy: 1 }, 429, h); }
      const fwd = { Accept: 'application/json', appKey: env.TMAP_KEY };
      const init = { method: req.method === 'POST' ? 'POST' : 'GET', headers: fwd };
      if (init.method === 'POST') { fwd['Content-Type'] = req.headers.get('content-type') || 'application/json'; init.body = await req.text(); }
      let ck2 = null;
      if (p === 'road/nearToRoad') {
        const q = url.searchParams, rla = Math.round(Number(q.get('lat')) * 1000) / 1000, rlo = Math.round(Number(q.get('lon')) * 1000) / 1000;
        ck2 = new Request('https://cache.tsnavi/near/' + rla + ',' + rlo);
        const hit2 = await caches.default.match(ck2);
        if (hit2) return new Response(await hit2.arrayBuffer(), { status: 200, headers: { ...h, 'Content-Type': 'application/json' } });
      }
      try {
        const r = await fetch('https://apis.openapi.sk.com/tmap/' + p + url.search, init);
        if (p === 'routes' || p === 'routes/prediction') count(env, ctx, 'routes');
        else if (p === 'road/matchToRoads500') count(env, ctx, 'match');
        if (ck2 && r.ok) { const buf = await r.arrayBuffer(); await caches.default.put(ck2, new Response(buf, { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'max-age=600' } })); return new Response(buf, { status: 200, headers: { ...h, 'Content-Type': 'application/json' } }); }
        if (r.status === 204 || r.status === 304) return new Response(null, { status: 204, headers: h });
        return new Response(await r.arrayBuffer(), { status: r.status, headers: { ...h, 'Content-Type': r.headers.get('content-type') || 'application/json' } });
      } catch { return json({ error: '원 서버에 연결하지 못했습니다' }, 502, h); }
    }
    return json({ error: '없는 경로' }, 404, h);
  },
};
