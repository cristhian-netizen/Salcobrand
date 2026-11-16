// Local disposable fixtures exercise approval, report filters and actual file downloads.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WS = require("../web/node_modules/next/dist/compiled/ws");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const base = "http://localhost:3002";
  const marker = await fetch(base + "/api/profile-qa").then((r) => r.json());
  assert.equal(marker.environment, "profile-qa");
  const folder = path.resolve(".local/reports-qa");
  fs.mkdirSync(folder, { recursive: true });
  const tab = await fetch("http://127.0.0.1:9225/json/new?about:blank", {
    method: "PUT",
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
    const result = await call("Runtime.evaluate", {
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
    for (let attempt = 0; attempt < 240; attempt++) {
      if (await evaluate(expression)) return;
      await pause(250);
    }
    throw Error(
      "Timeout " +
        expression +
        "\n" +
        (await evaluate("document.body.innerText.slice(0,1000)")),
    );
  }
  const click = (label) =>
    evaluate(
      `Array.from(document.querySelectorAll('main button')).find(b=>b.textContent.trim()===${JSON.stringify(label)}&&!b.disabled).click()`,
    );
  async function login(profile) {
    await call("Network.clearBrowserCookies");
    await call("Page.navigate", { url: base });
    await wait('!!document.querySelector("input[name=username]")');
    await wait(
      'Object.keys(document.querySelector("form")).some(k=>k.startsWith("__reactProps"))',
    );
    await evaluate(
      `document.querySelector('input[name=username]').value='local-${profile}';document.querySelector('input[name=password]').value='Isolated-local-password-2026!';document.querySelector('form').requestSubmit()`,
    );
    await wait('!!document.querySelector("nav[aria-label=Principal]")');
  }
  async function reports() {
    await evaluate(`location.hash='/reportes'`);
    await wait(
      `document.querySelector('main h1')?.textContent==='Reportes y exportaciones'&&!!document.querySelector('main table')`,
    );
    await wait(
      `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent.trim()==='Descargar Excel'&&!b.disabled)`,
    );
  }
  async function setFilter(label, value) {
    await evaluate(
      `(()=>{const label=Array.from(document.querySelectorAll('.sb-toolbar label')).find(e=>e.childNodes[0].textContent===${JSON.stringify(label)});const input=label.querySelector('input,select');const prototype=input.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,${JSON.stringify(value)});input.dispatchEvent(new Event(input.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`,
    );
  }
  async function review(id, status, note = "") {
    await evaluate(`location.hash='/gondolas/point-a/lectura/${id}'`);
    await wait(
      `document.querySelector('main h1')?.textContent==='Lectura #${id}'&&!!document.querySelector('main textarea')&&Array.from(document.querySelectorAll('main .sb-hint')).some(e=>e.textContent.startsWith('Lectura #${id} ·'))`,
    );
    await evaluate(
      `(()=>{const select=document.querySelector('main form select');select.value=${JSON.stringify(status)};select.dispatchEvent(new Event('change',{bubbles:true}));})()`,
    );
    if (note)
      await evaluate(
        `(()=>{const textarea=document.querySelector('main textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(textarea,${JSON.stringify(note)});textarea.dispatchEvent(new Event('input',{bubbles:true}));})()`,
      );
    const unchanged = await evaluate(
      `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent.trim()==='Guardar revisión'&&b.disabled)`,
    );
    if (unchanged) return;
    await click("Guardar revisión");
    await wait(
      `Array.from(document.querySelectorAll('main [role=status]')).some(e=>e.textContent.includes('Revisión guardada'))`,
    );
  }
  async function screenshot(name, width, height) {
    await call("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width < 600,
    });
    await pause(450);
    assert(
      await evaluate("document.documentElement.scrollWidth<=innerWidth"),
      "Horizontal page overflow",
    );
    assert(
      await evaluate(
        `Array.from(document.querySelectorAll('.sb-metric')).every(e=>e.getBoundingClientRect().right<=innerWidth)`,
      ),
    );
    const image = await call("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    fs.writeFileSync(
      path.join(folder, name + ".png"),
      Buffer.from(image.data, "base64"),
    );
  }
  try {
    await call("Page.enable");
    await call("Browser.setDownloadBehavior", {
      behavior: "allow",
      downloadPath: folder,
    });
    await login("analyst");
    await reports();
    const initial = await evaluate(
      `fetch('/api/reports/measurements').then(r=>r.json())`,
    );
    assert.equal(initial.rows.length, 2);
    const approvedId = initial.rows[0].id;
    const rejectedId = initial.rows[1].id;
    await review(approvedId, "Aprobado");
    await review(rejectedId, "Rechazado", "Imagen de prueba incompleta");
    await reports();
    const reviewed = await evaluate(
      `fetch('/api/reports/measurements').then(r=>r.json())`,
    );
    assert.equal(reviewed.totals.approved, 1);
    assert.equal(reviewed.totals.rejected, 1);
    assert.equal(
      reviewed.totals.average_score,
      reviewed.rows.find((r) => r.id === approvedId).score,
    );
    await setFilter("Estado", "En revisión");
    await wait(
      `document.querySelector('main .sb-empty')?.textContent.includes('No hay mediciones')`,
    );
    await click("Limpiar filtros");
    await wait(`document.querySelectorAll('main tbody tr').length===2`);
    await setFilter("Desde", "2099-01-01");
    await wait(
      `document.querySelector('main .sb-empty')?.textContent.includes('No hay mediciones')`,
    );
    await setFilter("Hasta", "2020-01-01");
    await wait(
      `document.querySelector('main [role=alert]')?.textContent.includes('Desde')`,
    );
    await click("Limpiar filtros");
    await wait(`document.querySelectorAll('main tbody tr').length===2`);
    await screenshot("reports-desktop", 1440, 1000);
    const buttons = await evaluate(
      `Array.from(document.querySelectorAll('.sb-head button')).map(b=>{const r=b.getBoundingClientRect();return {top:r.top,bottom:r.bottom}})`,
    );
    assert.equal(buttons[0].top, buttons[1].top, "Download button alignment");
    assert.equal(buttons[0].bottom, buttons[1].bottom);
    await screenshot("reports-mobile", 390, 844);
    await screenshot("reports-desktop", 1440, 1000);
    await click("Descargar Excel");
    for (
      let attempt = 0;
      attempt < 120 &&
      !fs.existsSync(path.join(folder, "Neuravision_Mediciones.xlsx"));
      attempt++
    )
      await pause(250);
    assert(
      fs.existsSync(path.join(folder, "Neuravision_Mediciones.xlsx")),
      "Actual Excel download",
    );
    await wait(
      `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent.trim()==='Descargar CSV'&&!b.disabled)`,
    );
    await click("Descargar CSV");
    for (
      let attempt = 0;
      attempt < 120 &&
      !fs.existsSync(path.join(folder, "Neuravision_Mediciones.csv"));
      attempt++
    )
      await pause(250);
    assert(fs.existsSync(path.join(folder, "Neuravision_Mediciones.csv")));
    const csv = fs.readFileSync(
      path.join(folder, "Neuravision_Mediciones.csv"),
      "utf8",
    );
    assert(csv.includes("Medición hecha por"));
    assert(!csv.includes("Caras reportadas"));
    for (const profile of ["admin", "viewer"]) {
      await login(profile);
      await reports();
      await evaluate(`location.hash='/gondolas/point-a/lectura/${approvedId}'`);
      await wait(
        `document.querySelector('main h1')?.textContent==='Lectura #${approvedId}'`,
      );
      assert.equal(
        await evaluate('!!document.querySelector("main textarea")'),
        false,
      );
    }
    await login("replenisher");
    assert.equal(
      await evaluate(
        `Array.from(document.querySelectorAll('nav button')).some(b=>b.textContent==='Reportes')`,
      ),
      false,
    );
    assert.equal(
      await evaluate(
        `fetch('/api/reports/measurements.xlsx').then(r=>r.status)`,
      ),
      403,
    );
    console.log(
      "PASS approval/rejection through UI, report filters, approved-only metrics, Excel/CSV downloads, profiles and mobile",
    );
  } finally {
    await call("Page.close");
    socket.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
