// Exercise actual local HTTP + Next UI with synthetic accounts only.
const assert = require('node:assert/strict');
const WebSocket = globalThis.WebSocket || require('../web/node_modules/next/dist/compiled/ws');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const base = process.env.PROFILE_QA_URL || 'http://localhost:3001';
const debug = process.env.PROFILE_QA_CDP || 'http://127.0.0.1:9225';

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const item = JSON.parse(event.data);
    if (!item.id) return;
    const job = pending.get(item.id); pending.delete(item.id);
    item.error ? job.reject(Error(item.error.message)) : job.resolve(item.result);
  };
  return {socket, call: (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq; pending.set(id, {resolve, reject}); socket.send(JSON.stringify({id, method, params}));
  })};
}

(async () => {
  assert(['localhost', '127.0.0.1'].includes(new URL(base).hostname), 'QA must be local');
  const marker = await fetch(base + '/api/profile-qa').then(r => r.json());
  assert.equal(marker.environment, 'profile-qa', 'Do not send QA logins to a remote backend');
  const expected = {
    admin: {scan: false, review: false, report: true, manage: true},
    analyst: {scan: true, review: true, report: true, manage: false},
    replenisher: {scan: true, review: false, report: false, manage: false},
    viewer: {scan: false, review: false, report: true, manage: false},
  };
  for (const [role, rights] of Object.entries(expected)) {
    const tab = await fetch(debug + '/json/new?about:blank', {method: 'PUT'}).then(r => r.json());
    const c = await connect(tab.webSocketDebuggerUrl);
    const evaluate = async expression => {
      const result = await c.call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
      if (result.exceptionDetails) throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const wait = async expression => {
      for (let n = 0; n < 300; n++) { if (await evaluate(expression)) return; await pause(150); }
      throw Error(role + ': timeout ' + expression + '\n' + await evaluate('document.body.innerText.slice(0,700)'));
    };
    try {
      await c.call('Page.enable');
      await c.call('Network.clearBrowserCookies');
      await c.call('Page.navigate', {url: base});
      await wait('!!document.querySelector("input[name=username]")');
      await wait('Object.keys(document.querySelector("form")).some(key=>key.startsWith("__reactProps"))');
      await evaluate(`document.querySelector('input[name=username]').value=${JSON.stringify('local-' + role)};document.querySelector('input[name=password]').value='Isolated-local-password-2026!';document.querySelector('form').requestSubmit()`);
      await wait('!!document.querySelector("nav[aria-label=Principal]")');
      const labels = await evaluate('Array.from(document.querySelectorAll("nav[aria-label=Principal] button")).map(b=>b.textContent.trim())');
      for (const [label, enabled] of [['Escanear góndola', rights.scan], ['Revisión', rights.review], ['Reportes', rights.report], ['Personas y roles', rights.manage], ['Planogramas', rights.manage]]) {
        assert.equal(labels.includes(label), enabled, `${role}: ${label}`);
      }
      for (const label of ['Puntos de venta','Infraestructura','Productos']) assert.equal(labels.includes(label),rights.manage,`${role}: ${label}`);
      await evaluate('location.hash="/gondolas/point-a"');
      await wait('!!document.querySelector("main h1") && document.querySelector("main h1").textContent==="point-a"');
      const buttons = await evaluate('Array.from(document.querySelectorAll("main button")).map(b=>b.textContent.trim())');
      assert.equal(buttons.includes('CSV'), rights.report, `${role}: CSV action`);
      assert.equal(buttons.includes('Nueva lectura'), rights.scan, `${role}: scan action`);
      assert.equal(buttons.includes('Eliminar góndola'), false, `${role}: preserve historical point`);
      assert.equal(buttons.includes('Administrar góndolas del PDV'), rights.manage, `${role}: infrastructure action`);
      const count = await evaluate('document.querySelectorAll("main table tbody tr").length');
      assert.equal(count, role === 'replenisher' ? 1 : 2, `${role}: visible reading authors`);
      if (!rights.review) {
        await evaluate('location.hash="/revision"');
        await wait('document.querySelector("main h1")?.textContent.startsWith("Buenos") || document.querySelector("main h1")?.textContent.startsWith("Buenas")');
      }
      if (rights.manage) {
        await require('./management-browser-checks.cjs')(evaluate,wait,c);
        await require('./catalog-browser-checks.cjs')(evaluate,wait,c);
        await evaluate('location.hash="/usuarios"');
        await wait('document.querySelector("main h1")?.textContent==="Personas y roles"');
        await evaluate('Array.from(document.querySelectorAll("main button")).find(b=>b.textContent.includes("Crear usuario")).click()');
        await wait('!!document.querySelector("[role=dialog] select")');
        assert.equal(await evaluate('Array.from(document.querySelectorAll("[role=dialog] label")).find(label=>label.firstChild.textContent==="Rol").querySelector("select").options.length'), 4);
        await evaluate('Array.from(document.querySelectorAll("[role=dialog] button")).find(b=>b.textContent==="Cancelar").click()');
      }
      await c.call('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
      await pause(200);
      assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'), true, role + ': mobile overflow');
      await evaluate('Array.from(document.querySelectorAll("button")).find(b=>b.textContent.trim()==="Cerrar sesión").click()');
      await wait('!!document.querySelector("input[name=username]")');
      console.log('PASS UI', role);
    } finally {
      c.socket.close();
      await fetch(debug + '/json/close/' + tab.id);
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
