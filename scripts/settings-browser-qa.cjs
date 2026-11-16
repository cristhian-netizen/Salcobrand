// Exercise disposable QA, or inspect the user's local configuration without editing it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const WS = require('../web/node_modules/next/dist/compiled/ws');
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const live = process.argv.includes('--live-preview');
  const base = live ? 'http://localhost:3001' : 'http://localhost:3002';
  if (!live) assert.equal(
    (await fetch(base + '/api/profile-qa').then((r) => r.json())).environment,
    'profile-qa',
  );
  const folder = path.resolve('.local/settings-qa');
  fs.mkdirSync(folder, { recursive: true });
  const tab = await fetch('http://127.0.0.1:9225/json/new?about:blank', {
    method: 'PUT',
  }).then((r) => r.json());
  const socket = new WS(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (!data.id) return;
    const request = pending.get(data.id);
    pending.delete(data.id);
    data.error
      ? request.reject(Error(data.error.message))
      : request.resolve(data.result);
  };
  const call = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails)
      throw Error(
        result.exceptionDetails.exception?.description ||
          result.exceptionDetails.text,
      );
    return result.result.value;
  }
  async function wait(expression) {
    for (let n = 0; n < 280; n++) {
      if (await evaluate(expression)) return;
      await pause(250);
    }
    throw Error(
      'Timeout ' +
        expression +
        '\n' +
        (await evaluate('document.body.innerText.slice(-1000)')),
    );
  }
  const click = (label) =>
    evaluate(
      `Array.from(document.querySelectorAll('main button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled&&b.getClientRects().length).click()`,
    );
  const field = (label, value) =>
    evaluate(
      `(()=>{const scope=document.querySelector('[role=dialog]')||document.querySelector('main');const label=Array.from(scope.querySelectorAll('label')).find(l=>Array.from(l.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()===${JSON.stringify(label)}&&l.getClientRects().length);const input=label.querySelector('input,select');const prototype=input.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event(input.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`,
    );
  async function route(view, title) {
    await evaluate(`location.hash=${JSON.stringify('/' + view)}`);
    await wait(
      `document.querySelector('main h1')?.textContent===${JSON.stringify(title)}`,
    );
  }
  async function settings() {
    await route('configuracion', 'Configuración');
    await wait('!!document.querySelector(".settings-type input")');
  }
  async function login(profile) {
    await call('Network.clearBrowserCookies');
    await call('Page.navigate', { url: base });
    await wait('!!document.querySelector("input[name=username]")');
    await wait(
      'Object.keys(document.querySelector("form")).some(k=>k.startsWith("__reactProps"))',
    );
    await evaluate(
      `document.querySelector('input[name=username]').value='local-${profile}';document.querySelector('input[name=password]').value='Isolated-local-password-2026!';document.querySelector('form').requestSubmit()`,
    );
    await wait('!!document.querySelector("nav[aria-label=Principal]")');
  }
  const configured = (expression) =>
    wait(
      `fetch('/api/admin/settings').then(r=>r.json()).then(data=>${expression})`,
    );
  async function screenshot(name, width, height) {
    await call('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width < 600,
    });
    await pause(400);
    assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'));
    const image = await call('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    });
    fs.writeFileSync(
      path.join(folder, name + '.png'),
      Buffer.from(image.data, 'base64'),
    );
  }
  try {
    await call('Page.enable');
    await login('admin');
    await settings();
    if (live) {
      assert.equal(await evaluate(`fetch('/api/auth/me').then(r=>r.json()).then(u=>u.environment)`), 'capture-dev');
      const config = await evaluate(`fetch('/api/admin/settings').then(r=>r.json())`);
      assert.equal(await evaluate(`document.querySelectorAll('.settings-brand').length`), config.state.catalog.brands.length);
      await screenshot('live-settings-desktop', 1440, 1000);
      await evaluate(`document.querySelector('.settings-brand').scrollIntoView({block:'start'})`);
      await screenshot('live-classification-desktop', 1440, 1000);
      await screenshot('live-classification-mobile', 390, 844);
      await evaluate(`window.scrollTo(0,0)`);
      await click('Parámetros de análisis');
      await screenshot('live-analysis-mobile', 390, 844);
      await screenshot('live-analysis-desktop', 1440, 1000);
      console.log('PASS live configuration',JSON.stringify({version:config.version,types:config.state.pdvTypes.length,brands:config.state.catalog.brands.length,categories:Object.keys(config.state.catalog.categories).length}));
      return;
    }
    await click('Añadir tipo de PDV');
    const count = await evaluate(
      'document.querySelectorAll(".settings-type").length',
    );
    await field('Tipo de PDV ' + count, 'Farmacia comunitaria QA');
    await click('Guardar tipos de PDV');
    await configured(`data.state.pdvTypes.includes('Farmacia comunitaria QA')`);
    await click('Añadir marca / submarca');
    const brandCount = await evaluate(
      'document.querySelectorAll(".settings-brand").length',
    );
    await field('Marca / submarca ' + brandCount, 'Marca Configuración QA');
    await evaluate(
      `document.querySelectorAll('.settings-brand input[type=checkbox]')[${brandCount - 1}].click()`,
    );
    await click('Añadir categoría / subcategoría');
    const rows = await evaluate(
      'document.querySelectorAll(".settings-classification").length',
    );
    await field('Categoría ' + rows, 'Categoría Configuración QA');
    await evaluate(
      `(()=>{const row=document.querySelectorAll('.settings-classification')[${rows - 1}];const input=row.querySelectorAll('input')[1];Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Subcategoría QA');input.dispatchEvent(new Event('input',{bubbles:true}));const select=row.querySelector('select');select.value=Array.from(select.options).find(o=>o.textContent==='Marca Configuración QA').value;select.dispatchEvent(new Event('change',{bubbles:true}));})()`,
    );
    await click('Guardar clasificación');
    await configured(
      `data.state.catalog.exclusive['Categoría Configuración QA']==='Marca Configuración QA'&&data.state.productParameters.ownBrands.includes('Marca Configuración QA')`,
    );
    await route('pdv', 'Puntos de venta');
    await wait(
      `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent==='Crear PDV'&&!b.disabled)`,
    );
    await click('Crear PDV');
    await wait(`!!document.querySelector('[role=dialog] select')`);
    await field('Tipo de PDV', 'Farmacia comunitaria QA');
    assert.equal(
      await evaluate(
        `Array.from(document.querySelectorAll('[role=dialog] label')).find(l=>l.childNodes[0].textContent==='Tipo de PDV').querySelector('select').value`,
      ),
      'Farmacia comunitaria QA',
    );
    await click('Cancelar');
    await route('productos', 'Productos');
    await wait(
      `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent.trim()==='Crear producto'&&!b.disabled)`,
    );
    await click('Crear producto');
    await wait(`!!document.querySelector('[role=dialog] input')`);
    await field('Nombre del producto', 'Producto configurado QA');
    await field('SKU', 'CONFIG-QA');
    await field('Marca / submarca', 'Marca Configuración QA');
    await field('Categoría', 'Categoría Configuración QA');
    await field('Subcategoría', 'Subcategoría QA');
    for (const [label, value] of [
      ['Cantidad', '150'],
      ['Alto (cm)', '10'],
      ['Ancho (cm)', '5'],
      ['Espesor (cm)', '3'],
    ])
      await field(label, value);
    await click('Guardar');
    await wait(
      `!document.querySelector('[role=dialog]')&&document.querySelector('main tbody')?.textContent.includes('CONFIG-QA')`,
    );
    await settings();
    await evaluate(
      `(()=>{const row=Array.from(document.querySelectorAll('.settings-brand')).find(row=>row.querySelector('input').value==='Marca Configuración QA');row.querySelector('button').click();})()`,
    );
    await click('Guardar clasificación');
    await wait(
      `document.querySelector('main [role=alert]')?.textContent.includes('productos asociados')`,
    );
    await click('Recargar valores guardados');
    await wait(
      `Array.from(document.querySelectorAll('.settings-brand input')).some(i=>i.value==='Marca Configuración QA')`,
    );
    await click('Añadir tipo de PDV');
    const draftCount = await evaluate(
      'document.querySelectorAll(".settings-type").length',
    );
    await field('Tipo de PDV ' + draftCount, 'Borrador conservado');
    await click('Parámetros de análisis');
    await field('Margen adicional de profundidad (%)', '20');
    await click('Guardar estimación');
    await configured('data.state.productParameters.dimensionMarginPct===20');
    await click('Catálogos');
    assert.equal(
      await evaluate(
        `document.querySelectorAll('.settings-type input')[${draftCount - 1}].value`,
      ),
      'Borrador conservado',
    );
    await click('Parámetros de análisis');
    await evaluate(
      `(async()=>{const d=await fetch('/api/admin/settings').then(r=>r.json());await fetch('/api/admin/settings/score',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({version:d.version,value:{redMax:45,yellowMax:85}})});})()`,
    );
    await click('Guardar semáforo');
    await wait(
      `document.querySelector('main [role=alert]')?.textContent.includes('otra sesión')`,
    );
    await click('Recargar valores guardados');
    await wait(
      `Array.from(document.querySelectorAll('main label')).find(l=>l.childNodes[0]?.textContent.trim()==='Límite superior rojo')?.querySelector('input').value==='45'`,
    );
    await field('Límite superior rojo', '97');
    await field('Límite superior amarillo', '98');
    await click('Guardar semáforo');
    await configured('data.state.scoreParameters.redMax===97');
    const raw = await evaluate(
      `fetch('/api/points/point-a').then(r=>r.json())`,
    );
    assert(raw.readings.every((r) => r.standards.score_band === 'bad'));
    await field('Antigüedad máxima de una ausencia reciente (días)', '14');
    await click('Guardar objetivos');
    await configured('data.state.kpiParameters.freshDays===14');
    await click('Catálogos');
    await screenshot('settings-desktop', 1440, 1000);
    await screenshot('settings-mobile', 390, 844);
    await screenshot('settings-desktop', 1440, 1000);
    await evaluate('location.reload()');
    await wait(`!!document.querySelector('.settings-type input')`);
    assert(
      await evaluate(
        `Array.from(document.querySelectorAll('.settings-brand input')).some(i=>i.value==='Marca Configuración QA')`,
      ),
    );
    for (const profile of ['analyst', 'replenisher', 'viewer']) {
      await login(profile);
      assert(
        !(await evaluate(
          `Array.from(document.querySelectorAll('nav button')).some(b=>b.textContent==='Configuración')`,
        )),
      );
      assert.equal(
        await evaluate(`fetch('/api/admin/settings').then(r=>r.status)`),
        403,
      );
    }
    console.log(
      'PASS configuration UI, new PDV types, dependent product classifications, own brands, protected references, conflict recovery, independent drafts, colors, persistence, roles and mobile',
    );
  } finally {
    await call('Page.close');
    socket.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
