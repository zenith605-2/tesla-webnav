import { spawn } from 'node:child_process';
import { writeFileSync, readFileSync } from 'node:fs';
const [url, dir, stepsFile] = process.argv.slice(2);
const steps = JSON.parse(readFileSync(stepsFile, 'utf8'));
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=9334','--window-size=1250,780','--allow-file-access-from-files','--user-data-dir=/tmp/tesor/shot/prof2','about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets; for (let i = 0; i < 40; i++) { try { targets = await (await fetch('http://127.0.0.1:9334/json')).json(); break; } catch { await sleep(250); } }
const page = targets.find((t) => t.type === 'page'); const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
let id = 0; const pending = new Map();
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') console.log('EXCEPTION:', m.params.exceptionDetails.exception?.description?.slice(0,300) || m.params.exceptionDetails.text); });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Runtime.enable'); await send('Page.enable');
await send('Browser.grantPermissions', { permissions: ['geolocation'] }).catch(()=>{});
await send('Page.navigate', { url });
for (const s of steps) {
  if (s.wait) await sleep(s.wait);
  if (s.js) { const r = await send('Runtime.evaluate', { expression: s.js, awaitPromise: true, returnByValue: true }); console.log((s.name||'js')+':', JSON.stringify(r.result?.value ?? r.exceptionDetails?.exception?.description ?? r).slice(0, s.full ? 100000 : 1500)); }
  if (s.shot) { const sh = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(dir + '/' + s.shot, Buffer.from(sh.data, 'base64')); console.log('shot', s.shot); }
}
ws.close(); chrome.kill();
