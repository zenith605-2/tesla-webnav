// 테슬라 웹 내비 중계: 키를 서버에만 두고 차 브라우저 요청을 대신 보낸다.
//   /webnav/tmap/<경로>?<쿼리>   -> https://apis.openapi.sk.com/tmap/<경로>  (appKey = 비밀 값 TMAP_KEY)
//   /webnav/ev/<기능>?<쿼리>     -> 한국환경공단 전기차 충전소 API (serviceKey = 비밀 값 DATA_GO_KR_KEY, 넣었을 때만)
//   /webnav/ping                 -> 상태 확인 (키 값은 절대 돌려주지 않음)
// 지금은 사용자 혼자 시험하는 단계라 제한은 가볍게: IP 당 분당 120회, 인스턴스당 하루 3,000회.
// 옮길 때: 이 파일을 다른 곳(다른 Supabase 프로젝트, Cloudflare Workers 등)에 올리고 비밀 값만 다시 넣으면 된다.

const TMAP_PATHS = new Set(['pois', 'pois/search/around', 'routes', 'routes/prediction', 'geo/reversegeocoding', 'road/matchToRoads500', 'road/nearToRoad']);
const EV_OPS = new Set(['getChargerInfo', 'getChargerStatus']);
const ORIGINS = ['https://actparty.app', 'https://zenithworks.app', 'https://www.zenithworks.app', 'null', 'file://'];
const PER_MIN = 120;
const PER_DAY = 3000;
// 한 사람(IP)이 무료 한도를 다 써 버리지 못하게: 길찾기 하루 60회, 경로 제한속도 하루 20회 (티맵 무료는 넘으면 자동 차단이라 요금은 안 나옴)
const IP_DAY: Record<string, number> = { routes: 60, 'routes/prediction': 20, 'road/matchToRoads500': 20 };
const ipDay = new Map<string, number>();

const perIp = new Map<string, { t: number; n: number }>();
const incCache = new Map<string, { t: number; d: unknown }>();
let day = '';
let dayCount = 0;

function cors(origin: string | null): Record<string, string> {
  const ok = !origin || ORIGINS.includes(origin) || /^http:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?$/.test(origin);
  return {
    'Access-Control-Allow-Origin': ok ? (origin || '*') : 'https://actparty.app',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Accept, x-log',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function json(body: unknown, status: number, h: Record<string, string>) {
  return new Response(JSON.stringify(body), { status, headers: { ...h, 'Content-Type': 'application/json; charset=utf-8' } });
}

function limited(ip: string): string | null {
  const now = Date.now();
  const today = new Date(now + 9 * 3600e3).toISOString().slice(0, 10);
  if (today !== day) { day = today; dayCount = 0; ipDay.clear(); }
  if (++dayCount > PER_DAY) return '오늘 호출 한도를 넘었습니다';
  const r = perIp.get(ip);
  if (!r || now - r.t > 60e3) { perIp.set(ip, { t: now, n: 1 }); return null; }
  if (++r.n > PER_MIN) return '잠시 뒤에 다시 시도해 주세요';
  if (perIp.size > 5000) perIp.clear();
  return null;
}

Deno.serve(async (req) => {
  const h = cors(req.headers.get('origin'));
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: h });
  const url = new URL(req.url);
  const path = url.pathname.replace(/^.*?\/webnav\/?/, '');

  if (path === 'ping') {
    return json({ ok: true, tmap: !!Deno.env.get('TMAP_KEY'), ev: !!Deno.env.get('DATA_GO_KR_KEY'), its: !!Deno.env.get('ITS_KEY') }, 200, h);
  }
  // 관리자 전용: 안내 음성 녹음용 제미나이 TTS (WEBNAV_ADMIN 토큰이 맞을 때만). 키는 서버 비밀 값 GEMINI_API_KEY.
  if (path.startsWith('admin/')) {
    const tok = Deno.env.get('WEBNAV_ADMIN');
    if (!tok || req.headers.get('x-admin') !== tok) return json({ error: 'forbidden' }, 403, h);
    const gk = Deno.env.get('GEMINI_API_KEY');
    if (!gk) return json({ error: 'no gemini key' }, 503, h);
    const G = 'https://generativelanguage.googleapis.com/v1beta/';
    if (path === 'admin/models') {
      const r = await fetch(G + 'models?pageSize=200&key=' + gk);
      const d = await r.json();
      return json({ status: r.status, models: (d.models || []).map((m: { name: string }) => m.name).filter((n: string) => /tts|audio/i.test(n)) }, 200, h);
    }
    if (path === 'admin/ask' && req.method === 'POST') {
      // 검토 회의용: 여러 번 주고받은 대화(contents)를 그대로 넘겨 답을 받는다
      const b = await req.json();
      const model = b.model || 'gemini-3.5-flash';
      const r = await fetch(G + 'models/' + model + ':generateContent?key=' + gk, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: b.contents, generationConfig: { maxOutputTokens: b.max || 4000 } }),
      });
      const d = await r.json();
      const text = (d?.candidates?.[0]?.content?.parts || []).map((p: { text?: string }) => p.text || '').join('');
      return json({ status: r.status, text, usage: d.usageMetadata, error: text ? undefined : JSON.stringify(d).slice(0, 300) }, 200, h);
    }
    if (path === 'admin/text') {
      // 키 상태 확인용: 아주 짧은 글 생성 한 번 (잔액·한도 확인)
      const model = url.searchParams.get('model') || 'gemini-3.5-flash-lite';
      const r = await fetch(G + 'models/' + model + ':generateContent?key=' + gk, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contents: [{ parts: [{ text: 'Say OK' }] }], generationConfig: { maxOutputTokens: 5 } }),
      });
      const t = await r.text();
      return json({ status: r.status, body: t.slice(0, 500) }, 200, h);
    }
    if (path === 'admin/probe') {
      // 외부 주소 연결 확인용(관리자): ?u=주소 → 상태·걸린 시간·앞부분
      const t0 = Date.now(), u = url.searchParams.get('u') || '';
      try { const r = await fetch(u.replace('ITSKEY', Deno.env.get('ITS_KEY') || ''), { signal: AbortSignal.timeout(15000) }); const t = await r.text(); return json({ status: r.status, ms: Date.now() - t0, head: t.slice(0, 200), region: Deno.env.get('SB_REGION') || '' }, 200, h); }
      catch (e) { return json({ error: String(e), ms: Date.now() - t0 }, 200, h); }
    }
    if (path === 'admin/logs') {
      const SB = Deno.env.get('SUPABASE_URL')!, SK = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
      const H = { Authorization: 'Bearer ' + SK, apikey: SK, 'Content-Type': 'application/json' };
      const f = url.searchParams.get('f');
      if (f) { const r = await fetch(`${SB}/storage/v1/object/webnav-logs/${f}`, { headers: H }); return new Response(await r.text(), { status: r.status, headers: { ...h, 'Content-Type': 'application/json' } }); }
      const r = await fetch(`${SB}/storage/v1/object/list/webnav-logs`, { method: 'POST', headers: H, body: JSON.stringify({ prefix: url.searchParams.get('d') || '', limit: 1000, sortBy: { column: 'name', order: 'asc' } }) });
      return new Response(await r.text(), { status: r.status, headers: { ...h, 'Content-Type': 'application/json' } });
    }
    if (path === 'admin/tts' && req.method === 'POST') {
      const b = await req.json();
      const model = b.model || 'gemini-2.5-flash-preview-tts';
      const r = await fetch(G + 'models/' + model + ':generateContent?key=' + gk, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: b.text }] }],
          generationConfig: { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: b.voice || 'Kore' } } } },
        }),
      });
      const d = await r.json();
      const part = d?.candidates?.[0]?.content?.parts?.find((p: { inlineData?: unknown }) => p.inlineData);
      if (!part) return json({ status: r.status, error: JSON.stringify(d).slice(0, 400) }, 502, h);
      return json({ mime: part.inlineData.mimeType, data: part.inlineData.data, usage: d.usageMetadata }, 200, h);
    }
    return json({ error: '없는 경로' }, 404, h);
  }
  // 11/21 공개용 중계는 Cloudflare Workers(tsnavi-relay)로 이사. 리도 프로젝트를 지키려고 여기서는 관리자 경로만 받는다
  return json({ error: 'moved', to: 'https://tsnavi-relay.zenithworks.workers.dev/' }, 410, h);
  // 아래는 예전 코드(쓰지 않음)
  // 의견 보내기: 누구나, 글자만(위치 없음). IP 당 하루 5건, 1,000자. 저장: webnav-logs/feedback/<날짜>-<시각>-<난수>.json
  if (path === 'feedback' && req.method === 'POST') {
    const fip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'x', fk = fip + '|fb', fn = (ipDay.get(fk) || 0) + 1;
    limited(fip); ipDay.set(fk, fn);
    if (fn > 5) return json({ error: '오늘은 더 보낼 수 없습니다' }, 429, h);
    let b: { text?: string; ver?: string } = {};
    try { b = await req.json(); } catch (_e) { return json({ error: 'bad' }, 400, h); }
    const text = String(b.text || '').trim().slice(0, 1000);
    if (text.length < 2) return json({ error: '내용이 없습니다' }, 400, h);
    const kst = new Date(Date.now() + 9 * 3600e3).toISOString();
    const SB = Deno.env.get('SUPABASE_URL')!, SK = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
    const r = await fetch(`${SB}/storage/v1/object/webnav-logs/feedback/${kst.slice(0, 10)}-${kst.slice(11, 19).replace(/:/g, '')}-${crypto.randomUUID().slice(0, 6)}.json`, {
      method: 'POST', headers: { Authorization: 'Bearer ' + SK, apikey: SK, 'Content-Type': 'application/json' },
      body: JSON.stringify({ at: kst, text, ver: String(b.ver || '').slice(0, 40), ua: (req.headers.get('user-agent') || '').slice(0, 200) }) });
    return json({ ok: r.ok }, r.ok ? 200 : 502, h);
  }
  // 주행 기록(시험용, 페이지에서 ?log=1 로 켠 차만 보냄): Storage 비공개 버킷 webnav-logs/<날짜>/<세션>-<시각>.json. 조회는 관리자 경로
  if (path === 'log' && req.method === 'POST') {
    const lk = Deno.env.get('WEBNAV_LOG');
    if (!lk || (req.headers.get('x-log') || url.searchParams.get('k')) !== lk) return json({ error: 'forbidden' }, 403, h);
    const lip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'x', ll = limited(lip);
    if (ll) return json({ error: ll }, 429, h);
    const body = await req.text();
    if (body.length > 400000) return json({ error: 'too big' }, 413, h);
    const sid = (url.searchParams.get('sid') || 'x').replace(/[^a-z0-9]/gi, '').slice(0, 16);
    const kst = new Date(Date.now() + 9 * 3600e3).toISOString();
    const SB = Deno.env.get('SUPABASE_URL')!, SK = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
    const put = () => fetch(`${SB}/storage/v1/object/webnav-logs/${kst.slice(0, 10)}/${sid}-${kst.slice(11, 19).replace(/:/g, '')}.json`, {
      method: 'POST', headers: { Authorization: 'Bearer ' + SK, apikey: SK, 'Content-Type': 'application/json', 'x-upsert': 'true' }, body });
    let r = await put();
    if (r.status === 404 || r.status === 400) {
      await fetch(`${SB}/storage/v1/bucket`, { method: 'POST', headers: { Authorization: 'Bearer ' + SK, apikey: SK, 'Content-Type': 'application/json' }, body: JSON.stringify({ id: 'webnav-logs', name: 'webnav-logs', public: false }) });
      r = await put();
    }
    return json({ ok: r.ok, status: r.status }, r.ok ? 200 : 502, h);
  }
  const ip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'x';
  const lim = limited(ip);
  if (lim) return json({ error: lim }, 429, h);

  // 돌발(사고·공사·통제): 티맵 교통정보(zoom 11, 약 100km 범위, 1MB 넘음)를 서버에서 받아 지점만 골라 보냄. 0.2° 칸마다 3분 캐시
  if (path === 'inc') {
    const key = Deno.env.get('TMAP_KEY');
    if (!key) return json({ error: '서버에 티맵 키가 없습니다' }, 503, h);
    const la = Math.round(Number(url.searchParams.get('lat')) * 5) / 5, lo = Math.round(Number(url.searchParams.get('lon')) * 5) / 5;
    if (!(la > 33 && la < 39 && lo > 124 && lo < 132)) return json({ error: '좌표 오류' }, 400, h);
    const ck = la + ',' + lo, hit = incCache.get(ck);
    if (hit && Date.now() - hit.t < 180e3) return json(hit.d, 200, h);
    const r = await fetch('https://apis.openapi.sk.com/tmap/traffic?version=1&format=json&reqCoordType=WGS84GEO&resCoordType=WGS84GEO&zoomLevel=11&trafficType=AUTO&centerLat=' + la + '&centerLon=' + lo, { headers: { appKey: key, Accept: 'application/json' } });
    if (!r.ok) return json({ error: 'HTTP ' + r.status }, 502, h);
    const d = await r.json();
    // deno-lint-ignore no-explicit-any
    const out = (d.features || []).filter((f: any) => f.geometry?.type === 'Point' && f.properties?.isAccidentNode === 'Y').map((f: any) => {
      const p = f.properties, c = f.geometry.coordinates;
      return [Math.round(c[1] * 1e5) / 1e5, Math.round(c[0] * 1e5) / 1e5, p.accidentUpperName || '', p.accidentDetailName || '', String(p.description || '').split(' / ')[0].slice(0, 160)];
    });
    const res = { at: Date.now(), list: out };
    incCache.set(ck, { t: Date.now(), d: res });
    if (incCache.size > 200) incCache.clear();
    return json(res, 200, h);
  }

  // 경로 CCTV: 국가교통정보센터 ITS (비밀 값 ITS_KEY). 영역(0.05° 칸으로 반올림) 안 고속도로(ex)+국도(its) 실시간 영상 주소. 5분 캐시
  if (path === 'cctv') {
    const key = Deno.env.get('ITS_KEY');
    if (!key) return json({ error: 'no its key', list: [] }, 503, h);
    const r5 = (v: string | null, up: boolean) => { const n = Number(v) * 20; return (up ? Math.ceil(n) : Math.floor(n)) / 20; };
    const x0 = r5(url.searchParams.get('minX'), false), x1 = r5(url.searchParams.get('maxX'), true);
    const y0 = r5(url.searchParams.get('minY'), false), y1 = r5(url.searchParams.get('maxY'), true);
    if (!(x0 > 124 && x1 < 132 && y0 > 33 && y1 < 39 && x1 - x0 <= 1.5 && y1 - y0 <= 1.5)) return json({ error: '영역 오류' }, 400, h);
    const ck = 'c' + [x0, x1, y0, y1].join(','), hit = incCache.get(ck);
    if (hit && Date.now() - hit.t < 300e3) return json(hit.d, 200, h);
    const out: unknown[] = [];
    for (const type of ['ex', 'its']) {
      try {
        const r = await fetch(`https://openapi.its.go.kr:9443/cctvInfo?apiKey=${key}&type=${type}&cctvType=1&minX=${x0}&maxX=${x1}&minY=${y0}&maxY=${y1}&getType=json`);
        const d = await r.json();
        // deno-lint-ignore no-explicit-any
        for (const c of (d?.response?.data || []) as any[]) {
          if (!c.cctvurl) continue;
          out.push([Math.round(Number(c.coordy) * 1e5) / 1e5, Math.round(Number(c.coordx) * 1e5) / 1e5, String(c.cctvname || '').trim(), c.cctvurl, type]);
        }
      } catch (_e) { /* 한쪽이 실패해도 나머지는 보냄 */ }
    }
    const res = { at: Date.now(), list: out };
    incCache.set(ck, { t: Date.now(), d: res });
    return json(res, 200, h);
  }

  let target: string;
  const fwd: Record<string, string> = { Accept: 'application/json' };
  if (path.startsWith('tmap/')) {
    const p = path.slice(5);
    const key = Deno.env.get('TMAP_KEY');
    if (!TMAP_PATHS.has(p) && !/^pois\/\d+$/.test(p)) return json({ error: '허용되지 않은 경로' }, 404, h);
    if (IP_DAY[p]) {
      const k = ip + '|' + p, n = (ipDay.get(k) || 0) + 1;
      ipDay.set(k, n);
      if (ipDay.size > 20000) ipDay.clear();
      if (n > IP_DAY[p]) return json({ error: '오늘 한도(LIMIT)를 넘었습니다' }, 429, h);
    }
    if (!key) return json({ error: '서버에 티맵 키가 없습니다' }, 503, h);
    target = 'https://apis.openapi.sk.com/tmap/' + p + url.search;
    fwd.appKey = key;
  } else if (path.startsWith('ev/')) {
    const op = path.slice(3);
    const key = Deno.env.get('DATA_GO_KR_KEY');
    if (!EV_OPS.has(op)) return json({ error: '허용되지 않은 경로' }, 404, h);
    if (!key) return json({ error: '서버에 공공데이터 키가 없습니다' }, 503, h);
    const q = new URLSearchParams(url.search);
    q.set('serviceKey', key);
    q.set('dataType', 'JSON');
    target = 'https://apis.data.go.kr/B552584/EvCharger/' + op + '?' + q.toString();
  } else {
    return json({ error: '없는 경로' }, 404, h);
  }

  const init: RequestInit = { method: req.method === 'POST' ? 'POST' : 'GET', headers: fwd };
  if (init.method === 'POST') {
    fwd['Content-Type'] = req.headers.get('content-type') || 'application/json';
    init.body = await req.text();
  }
  try {
    const r = await fetch(target, init);
    if (r.status === 204 || r.status === 304) return new Response(null, { status: 204, headers: h });
    const body = await r.arrayBuffer();
    return new Response(body, {
      status: r.status,
      headers: { ...h, 'Content-Type': r.headers.get('content-type') || 'application/json' },
    });
  } catch (_e) {
    return json({ error: '원 서버에 연결하지 못했습니다' }, 502, h);
  }
});
