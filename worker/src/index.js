// TS내비 중계 (Cloudflare Workers). 키는 Cloudflare 비밀 값에만 둔다: TMAP_KEY, ADMIN, LOG
//   /ping                 상태 (키 값은 돌려주지 않음)
//   /tmap/<경로>?<쿼리>    티맵 API 대신 호출 (허용 경로만)
//   /inc?lat&lon          티맵 교통정보에서 돌발(사고·공사·통제) 지점만 골라 줌 (3분 캐시)
//   /feedback (POST)      의견 보내기 → KV fb/<날짜>-<시각>-<난수>  (IP 당 하루 5건, 1,000자, 위치 없음)
//   /log (POST, k=LOG)    시험용 주행 기록 → KV log/<날짜>/<세션>-<시각>
//   /admin/logs (x-admin) ?d=접두어 목록, ?f=키 내용
// 무료 요금제는 한도를 넘으면 막힐 뿐 요금이 나가지 않는다.

const TMAP_PATHS = new Set(['pois', 'pois/search/around', 'routes', 'routes/prediction', 'geo/reversegeocoding', 'road/matchToRoads500', 'road/nearToRoad']);
const ORIGINS = ['https://zenithworks.app', 'https://www.zenithworks.app', 'https://actparty.app', 'null'];
// 한 사람(IP)이 무료 한도를 다 쓰지 못하게 하루 한도 (같은 서버 조각 안에서 세는 대략값)
const IP_DAY = { routes: 60, 'routes/prediction': 20, 'road/matchToRoads500': 20, feedback: 5, kakao: 60 };
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
const QUOTA = { routes: 1000, traffic: 1000, match: 200, kakao: 2000 }; // 카카오는 아이혜택 앱과 무료 쿼터를 나눠 쓰므로 하루 2,000에서 스스로 멈춤
export class Counter {
  constructor(ctx) { this.ctx = ctx; }
  async fetch(req) {
    const u = new URL(req.url), d = u.searchParams.get('d'), k = u.searchParams.get('k');
    if (u.pathname === '/inc') { const key = d + '|' + k, n = ((await this.ctx.storage.get(key)) || 0) + 1; await this.ctx.storage.put(key, n); return new Response(String(n)); }
    const out = {};
    for (const q of Object.keys(QUOTA)) out[q] = (await this.ctx.storage.get(d + '|' + q)) || 0;
    return Response.json(out);
  }
}
function count(env, ctx, k) {
  if (!env.CNT) return;
  const stub = env.CNT.get(env.CNT.idFromName('day'));
  ctx.waitUntil(stub.fetch('https://cnt/inc?d=' + kst().slice(0, 10) + '&k=' + k).catch(() => {}));
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
      return new Response(JSON.stringify({ date: kst().slice(0, 10), used, limit: QUOTA }), { headers: { ...h, 'Content-Type': 'application/json', 'Cache-Control': 'max-age=30' } });
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
        if (!/^(fb|log)\//.test(k)) return json({ error: 'bad key' }, 400, h);
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

    if (path === 'log' && req.method === 'POST') {
      if (!env.LOG || (req.headers.get('x-log') || url.searchParams.get('k')) !== env.LOG) return json({ error: 'forbidden' }, 403, h);
      const body = await req.text();
      if (body.length > 400000) return json({ error: 'too big' }, 413, h);
      const sid = (url.searchParams.get('sid') || 'x').replace(/[^a-z0-9]/gi, '').slice(0, 16), t = kst();
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

    // 카카오모빌리티 길찾기 (비밀 값 KAKAO_KEY). 하루 전체 3,000회에서 멈춤
    if (path === 'kakao/directions') {
      if (!env.KAKAO_KEY) return json({ error: '서버에 카카오 키가 없습니다' }, 503, h);
      if (overDay(ip, 'kakao')) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      try {
        const used = await (await env.CNT.get(env.CNT.idFromName('day')).fetch('https://cnt/get?d=' + kst().slice(0, 10))).json();
        if ((used.kakao || 0) >= QUOTA.kakao) return json({ error: '오늘 카카오 무료 한도(LIMIT)를 다 썼습니다' }, 429, h);
      } catch { /* 카운터 실패해도 진행 */ }
      const q = new URLSearchParams();
      for (const k of ['origin', 'destination', 'waypoints', 'priority', 'car_fuel', 'avoid', 'alternatives', 'road_details', 'summary']) { const v = url.searchParams.get(k); if (v) q.set(k, v); }
      count(env, ctx, 'kakao');
      const r = await fetch('https://apis-navi.kakaomobility.com/v1/directions?' + q, { headers: { Authorization: 'KakaoAK ' + env.KAKAO_KEY } });
      return new Response(await r.arrayBuffer(), { status: r.status, headers: { ...h, 'Content-Type': 'application/json' } });
    }

    if (path.startsWith('tmap/')) {
      const p = path.slice(5);
      if (!TMAP_PATHS.has(p) && !/^pois\/\d+$/.test(p)) return json({ error: '허용되지 않은 경로' }, 404, h);
      if (IP_DAY[p] && overDay(ip, p)) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
      if (!env.TMAP_KEY) return json({ error: '서버에 티맵 키가 없습니다' }, 503, h);
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
