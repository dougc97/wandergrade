// cdp.mjs — minimal headless Chrome driver with a hard time cap.
// Usage: CDP_TIMEOUT=50 node cdp.mjs ./script.mjs
// The script's default export gets { send, evaluate, setSize, scheme, nav, shot, sleep, errs }.
// Wrap EVERY evaluate body in an IIFE: a top-level const redeclared across calls throws silently.
import { spawn } from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
const D = path.dirname(new URL(import.meta.url).pathname) + '/';
fs.mkdirSync(D + 'shots', { recursive: true });
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-'));
const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', '--user-data-dir=' + dir, '--no-first-run',
  '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars', '--window-size=1280,900', 'about:blank'], { stdio: 'ignore' });
const LIMIT = (+process.env.CDP_TIMEOUT || 60) * 1000;
let done = false;
const finish = (code) => { if (done) return; done = true; try { proc.kill('SIGKILL'); } catch {} try { fs.rmSync(dir, { recursive: true, force: true }); } catch {} process.exit(code); };
setTimeout(() => { console.log(`--- TIMEOUT after ${LIMIT / 1000}s: split the script into shorter runs ---`); finish(0); }, LIMIT);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let port = null;
for (let i = 0; i < 150 && !port; i++) { try { port = fs.readFileSync(dir + '/DevToolsActivePort', 'utf8').split('\n')[0]; } catch {} if (!port) await sleep(100); }
if (!port) { console.log('Chrome did not start'); finish(1); }
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0; const pending = new Map(); const errs = []; const listeners = [];
ws.onmessage = (ev) => {
  const d = JSON.parse(ev.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); return; }
  if (d.method === 'Runtime.exceptionThrown') errs.push('exception ' + ((d.params.exceptionDetails.exception || {}).description || d.params.exceptionDetails.text));
  if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') errs.push('console.error ' + d.params.args.map((a) => a.value || a.description).join(' '));
  if (d.method === 'Log.entryAdded' && d.params.entry.level === 'error') errs.push('log ' + d.params.entry.text + ' ' + (d.params.entry.url || ''));
  listeners.slice().forEach((f) => f(d));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
await send('Emulation.setFocusEmulationEnabled', { enabled: true });
// A JS dialog (alert/confirm/prompt) blocks Runtime.evaluate until handled: dismiss them.
listeners.push((d) => { if (d.method === 'Page.javascriptDialogOpening') { errs.push('dialog ' + (d.params.message || '').slice(0, 80)); send('Page.handleJavaScriptDialog', { accept: false }); } });
const evaluate = async (expr) => {
  // 20s cap: a hung evaluate used to stall a run until the global timeout with no clue why.
  const r = await Promise.race([send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }),
                                sleep(20000).then(() => ({ result: { exceptionDetails: { text: 'evaluate timed out after 20s' } } }))]);
  const ex = r.result && r.result.exceptionDetails;
  if (ex) return { EXC: (ex.exception && ex.exception.description) || ex.text };
  return r.result && r.result.result ? r.result.result.value : undefined;
};
// setSize(w, h, mobile): viewport emulation; mobile=true adds touch + a phone UA.
const setSize = async (w, h, mobile = false) => {
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: mobile ? 2 : 1, mobile: !!mobile });
  await send('Emulation.setTouchEmulationEnabled', { enabled: !!mobile });
  if (mobile) await send('Emulation.setUserAgentOverride', { userAgent: 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36' });
};
const scheme = (dark) => send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: dark ? 'dark' : 'light' }] });
// nav(url, settleMs): navigate, wait for load, then settle.
const nav = async (url, settleMs = 3000) => {
  const loaded = new Promise((r) => { const f = (d) => { if (d.method === 'Page.loadEventFired') { listeners.splice(listeners.indexOf(f), 1); r(); } }; listeners.push(f); });
  await send('Page.navigate', { url });
  await Promise.race([loaded, sleep(20000)]);
  await sleep(settleMs);
};
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  const p = D + 'shots/' + name + '.png';
  fs.writeFileSync(p, Buffer.from(r.result.data, 'base64'));
  return p;
};
const scriptPath = path.resolve(process.argv[2]);
try {
  const mod = await import(scriptPath);
  await mod.default({ send, evaluate, setSize, scheme, nav, shot, sleep, errs });
} catch (e) { console.log('script error', e && e.stack || e); }
console.log(`--- errors (${errs.length}) ---`); errs.slice(0, 10).forEach((e) => console.log(e));
finish(0);
