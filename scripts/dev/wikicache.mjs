// wikicache.mjs — serve a page's Wikipedia/Wikimedia requests from a disk cache (for cdp.mjs scripts:
// enableWikiCache(send, on)), so repeated measurement loads don't hit Wikimedia: 2026-10-31 a few dozen
// cold guide loads got this machine 429s, and a 429'd hero collapses 320px — a shift that isn't the
// page's. A miss is fetched once, one at a time, with the dev User-Agent, and kept if it is a 200.
// WC_DIR (default <tmpdir>/wg-wikicache), WC_OFFLINE=1 (a miss answers 503 instead of fetching: warm the
// cache with one sequential run first, then run in parallel). Served responses skip the emulated slow
// link: photos arrive at local speed, the same for every tree compared.
import fs from 'node:fs'; import crypto from 'node:crypto'; import os from 'node:os'; import path from 'node:path';
const DIR = (process.env.WC_DIR || path.join(os.tmpdir(), 'wg-wikicache')) + '/';
fs.mkdirSync(DIR, { recursive: true });
const UA = 'WanderGrade-dev/1.0 (hello@wandergrade.com)';
const KEEP = ['content-type', 'access-control-allow-origin', 'cache-control', 'last-modified', 'etag'];
let chain = Promise.resolve();
export const stats = { hit: 0, miss: 0, fail: 0, offline: 0 };
async function getEntry(url) {
  const key = crypto.createHash('sha1').update(url).digest('hex');
  const meta = DIR + key + '.json', body = DIR + key + '.bin';
  if (fs.existsSync(meta) && fs.existsSync(body)) { stats.hit++; return { ...JSON.parse(fs.readFileSync(meta, 'utf8')), body: fs.readFileSync(body) }; }
  if (process.env.WC_OFFLINE === '1') { stats.offline++; return { status: 503, headers: [['content-type', 'text/plain']], body: Buffer.from('offline') }; }
  const p = chain.then(async () => {
    if (fs.existsSync(meta) && fs.existsSync(body)) return { ...JSON.parse(fs.readFileSync(meta, 'utf8')), body: fs.readFileSync(body) };
    stats.miss++;
    try {
      const r = await fetch(url, { headers: { 'User-Agent': UA, 'Api-User-Agent': UA }, signal: AbortSignal.timeout(15000) });
      const buf = Buffer.from(await r.arrayBuffer());
      const headers = [...r.headers].filter(([k]) => KEEP.includes(k.toLowerCase()));
      if (r.status === 200) { fs.writeFileSync(body, buf); fs.writeFileSync(meta, JSON.stringify({ url, status: 200, headers })); }
      else stats.fail++;
      return { status: r.status, headers, body: buf };
    } catch (e) { stats.fail++; return { status: 504, headers: [['content-type', 'text/plain']], body: Buffer.from(String(e)) }; }
  });
  chain = p.catch(() => {});
  return p;
}
export async function enableWikiCache(send, on) {
  on(async (d) => {
    if (d.method !== 'Fetch.requestPaused') return;
    const { requestId, request } = d.params;
    const e = await getEntry(request.url);
    const hs = e.headers.map(([name, value]) => ({ name, value }));
    if (!hs.some((h) => h.name.toLowerCase() === 'access-control-allow-origin')) hs.push({ name: 'Access-Control-Allow-Origin', value: '*' });
    await send('Fetch.fulfillRequest', { requestId, responseCode: e.status, responseHeaders: hs, body: e.body.toString('base64') });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*://*.wikipedia.org/*' }, { urlPattern: '*://*.wikimedia.org/*' }] });
}
