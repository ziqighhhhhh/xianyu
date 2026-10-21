// PWA/browser smoke: node scripts/smoke_pwa.js
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');

const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9333;
const BASE = 'http://127.0.0.1:8000';

function getJson(pathname) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: PORT, path: pathname }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });
}

async function main() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'fap-pwa-'));
  const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
    `--user-data-dir=${profile}`, '--no-first-run', '--disable-gpu', 'about:blank',
  ], { stdio: 'ignore', detached: false });

  try {
    let list;
    for (let i = 0; i < 60; i++) {
      try { list = await getJson('/json/list'); break; } catch (e) { await new Promise((r) => setTimeout(r, 250)); }
    }
    if (!list) throw new Error('Edge CDP did not start');
    const page = list.find((t) => t.type === 'page');
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let seq = 0;
    const pending = new Map();
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    };
    const send = (method, params = {}) => new Promise((res) => {
      const id = ++seq; pending.set(id, res); ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async (expression) => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      return r.result && r.result.result ? r.result.result.value : undefined;
    };
    const checks = [];
    const check = (name, ok) => {
      if (!ok) throw new Error('FAIL ' + name);
      checks.push(name);
    };

    await send('Page.enable');
    await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: BASE + '/?pwa-smoke=1' });
    await new Promise((r) => setTimeout(r, 1200));
    const login = await evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})}).then(r=>r.status)`);
    check('login', login === 200);
    await send('Page.reload');
    await new Promise((r) => setTimeout(r, 2200));
    check('app shell', await evaluate("!!document.querySelector('.sidebar') && !!document.querySelector('#view')"));
    check('manifest', await evaluate("!!document.querySelector('link[rel=manifest]')"));
    const swReady = await evaluate("navigator.serviceWorker.ready.then(r=>!!r.active)");
    check('service worker ready', swReady === true);
    await send('Page.reload');
    await new Promise((r) => setTimeout(r, 1500));
    check('service worker controls page', await evaluate("!!navigator.serviceWorker.controller"));

    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(__dirname, '..', 'shots', 'pwa-smoke.png'), Buffer.from(screenshot.result.data, 'base64'));

    await send('Network.emulateNetworkConditions', { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
    await send('Page.reload');
    await new Promise((r) => setTimeout(r, 2200));
    const offlineState = await evaluate("({href:location.href,title:document.title,sidebar:!!document.querySelector('.sidebar'),controller:!!navigator.serviceWorker.controller})");
    check('offline shell/data', !!(offlineState && offlineState.controller && offlineState.sidebar));
    const offlineShot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(path.join(__dirname, '..', 'shots', 'pwa-offline.png'), Buffer.from(offlineShot.result.data, 'base64'));
    await send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });

    console.log(`PWA smoke: ${checks.length} checks passed`);
    for (const name of checks) console.log('  ok', name);
    ws.close();
    return 0;
  } finally {
    edge.kill();
    await new Promise((r) => setTimeout(r, 500));
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* Edge may still hold the profile */ }
  }
}

main().then((code) => process.exit(code)).catch((err) => {
  console.error(err.message);
  process.exit(1);
});
