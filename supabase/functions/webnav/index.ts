// 테슬라 웹 내비 중계: 키를 서버에만 두고 차 브라우저 요청을 대신 보낸다.
//   /webnav/tmap/<경로>?<쿼리>   -> https://apis.openapi.sk.com/tmap/<경로>  (appKey = 비밀 값 TMAP_KEY)
//   /webnav/ev/<기능>?<쿼리>     -> 한국환경공단 전기차 충전소 API (serviceKey = 비밀 값 DATA_GO_KR_KEY, 넣었을 때만)
//   /webnav/ping                 -> 상태 확인 (키 값은 절대 돌려주지 않음)
// 지금은 사용자 혼자 시험하는 단계라 제한은 가볍게: IP 당 분당 120회, 인스턴스당 하루 3,000회.
// 옮길 때: 이 파일을 다른 곳(다른 Supabase 프로젝트, Cloudflare Workers 등)에 올리고 비밀 값만 다시 넣으면 된다.

const TMAP_PATHS = new Set(['pois', 'pois/search/around', 'routes', 'routes/prediction', 'geo/reversegeocoding']);
const EV_OPS = new Set(['getChargerInfo', 'getChargerStatus']);
const ORIGINS = ['https://actparty.app', 'null', 'file://'];
const PER_MIN = 120;
const PER_DAY = 3000;

const perIp = new Map<string, { t: number; n: number }>();
let day = '';
let dayCount = 0;

function cors(origin: string | null): Record<string, string> {
  const ok = !origin || ORIGINS.includes(origin) || /^http:\/\/(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?$/.test(origin);
  return {
    'Access-Control-Allow-Origin': ok ? (origin || '*') : 'https://actparty.app',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Accept',
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
  if (today !== day) { day = today; dayCount = 0; }
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
    return json({ ok: true, tmap: !!Deno.env.get('TMAP_KEY'), ev: !!Deno.env.get('DATA_GO_KR_KEY') }, 200, h);
  }
  const ip = (req.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'x';
  const lim = limited(ip);
  if (lim) return json({ error: lim }, 429, h);

  let target: string;
  const fwd: Record<string, string> = { Accept: 'application/json' };
  if (path.startsWith('tmap/')) {
    const p = path.slice(5);
    const key = Deno.env.get('TMAP_KEY');
    if (!TMAP_PATHS.has(p)) return json({ error: '허용되지 않은 경로' }, 404, h);
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
    const body = await r.arrayBuffer();
    return new Response(body, {
      status: r.status,
      headers: { ...h, 'Content-Type': r.headers.get('content-type') || 'application/json' },
    });
  } catch (_e) {
    return json({ error: '원 서버에 연결하지 못했습니다' }, 502, h);
  }
});
