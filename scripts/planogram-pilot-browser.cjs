// Real, explicitly scoped pilot. The proof file prevents another photo submission on rerun.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WS = require("../web/node_modules/next/dist/compiled/ws");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const base = "http://localhost:3001";
  const proofPath = path.resolve(".local/planogram-pilot/proof.json");
  const proof = JSON.parse(fs.readFileSync(proofPath, "utf8"));
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
    const result = JSON.parse(event.data);
    if (!result.id) return;
    const request = pending.get(result.id);
    pending.delete(result.id);
    result.error
      ? request.reject(Error(result.error.message))
      : request.resolve(result.result);
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
  async function wait(expression, seconds = 90) {
    const started = Date.now();
    while (Date.now() - started < seconds * 1000) {
      if (await evaluate(expression)) return;
      await pause(300);
    }
    throw Error(
      "Timeout " +
        expression +
        "\n" +
        (await evaluate("document.body.innerText.slice(-1200)")),
    );
  }
  const click = (text) =>
    evaluate(
      `Array.from(document.querySelectorAll('main button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}&&!b.disabled).click()`,
    );
  function save() {
    const latest = JSON.parse(fs.readFileSync(proofPath, "utf8"));
    fs.writeFileSync(
      proofPath,
      JSON.stringify({ ...latest, ...proof }, null, 2),
    );
  }
  try {
    await call("Page.enable");
    await call("Network.clearBrowserCookies");
    await call("Page.navigate", { url: base });
    await wait('!!document.querySelector("input[name=username]")');
    await wait(
      'Object.keys(document.querySelector("form")).some(k=>k.startsWith("__reactProps"))',
    );
    await evaluate(
      `document.querySelector('input[name=username]').value='local-replenisher';document.querySelector('input[name=password]').value='Isolated-local-password-2026!';document.querySelector('form').requestSubmit()`,
    );
    await wait('!!document.querySelector("nav[aria-label=Principal]")');
    const me = await evaluate(`fetch('/api/auth/me').then(r=>r.json())`);
    assert.equal(me.environment, "capture-dev");
    if (!proof.job_id) {
      await evaluate(
        `localStorage.removeItem('nv-capture-job:local-replenisher');localStorage.removeItem('nv-capture-job:local-replenisher:request');location.hash='/escanear/pdv-001'`,
      );
      await wait(
        '!!document.querySelector("input[type=file]")&&!document.querySelector("input[type=file]").disabled',
      );
      await wait(
        `document.querySelector('main')?.textContent.includes('Se compara con DESODORANTES')`,
      );
      const document = await call("DOM.getDocument");
      const input = await call("DOM.querySelector", {
        nodeId: document.root.nodeId,
        selector: "input[type=file]",
      });
      const photo = process.env.PILOT_PHOTO;
      assert(photo, "Set PILOT_PHOTO to the user-provided image");
      await call("DOM.setFileInputFiles", {
        nodeId: input.nodeId,
        files: [path.resolve(photo)],
      });
      await wait('document.querySelectorAll(".sb-previews figure").length===1');
      await wait(
        `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent==='Analizar góndola'&&!b.disabled)`,
      );
      await click("Analizar góndola");
      await wait(`!!localStorage.getItem('nv-capture-job:local-replenisher')`);
      proof.job_id = await evaluate(
        `localStorage.getItem('nv-capture-job:local-replenisher')`,
      );
      save();
      console.log("SUBMITTED", proof.job_id);
    } else {
      await evaluate(
        `localStorage.setItem('nv-capture-job:local-replenisher',${JSON.stringify(proof.job_id)});location.hash='/escanear/pdv-001'`,
      );
    }
    await evaluate("location.reload()");
    if (process.argv.includes("--wait")) {
      await wait(
        `document.querySelector('main h1')?.textContent.startsWith('Lectura #')||Array.from(document.querySelectorAll('main button')).some(b=>b.textContent==='Recuperar resultado')`,
        1000,
      );
      if (
        await evaluate(
          `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent==='Recuperar resultado')`,
        )
      ) {
        await click("Recuperar resultado");
        await wait(
          `document.querySelector('main h1')?.textContent.startsWith('Lectura #')`,
          1000,
        );
      }
      const job = await evaluate(
        `fetch('/api/analysis-jobs/'+${JSON.stringify(proof.job_id)}).then(r=>r.json())`,
      );
      assert.equal(job.status, "done");
      const r = job.reading;
      assert.equal(r.planogram_id, proof.local_plan_id);
      assert.equal(r.captured_by, "local-replenisher");
      assert.equal(r.compliance.total_expected_facings, proof.expected_facings);
      assert.equal(r.compliance.items.length, proof.positions);
      assert(r.products.length > 0);
      await wait(
        `Array.from(document.querySelectorAll('.sb-photos img')).some(i=>i.complete&&i.naturalWidth>0)`,
      );
      proof.reading_id = r.id;
      proof.remote = r.engine.remote;
      proof.detected_facings = r.total_facings;
      proof.compliance_pct = r.compliance.compliance_pct;
      proof.needs_review = r.needs_review;
      save();
      const screenshot = await call("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      fs.writeFileSync(
        path.resolve(".local/planogram-pilot/capture-result.png"),
        Buffer.from(screenshot.data, "base64"),
      );
      console.log(
        "REAL PLANOGRAM PILOT",
        JSON.stringify({
          reading: r.id,
          remote: r.engine.remote.reading_id,
          facings: r.total_facings,
          expected: r.compliance.total_expected_facings,
          compliance: r.compliance.compliance_pct,
          needs_review: r.needs_review,
        }),
      );
    }
    if (process.argv.includes("--inspect")) {
      await evaluate(`location.hash='/mediciones'`);
      await wait(
        `document.querySelector('main h1')?.textContent==='Mediciones'&&Array.from(document.querySelectorAll('main tbody tr')).some(r=>r.textContent.includes('#${proof.reading_id}'))`,
      );
      const rows = await evaluate(
        `Array.from(document.querySelectorAll('main tbody tr')).map(r=>r.textContent)`,
      );
      assert(rows.every((text) => text.includes("local-replenisher")));
      assert(
        !(await evaluate(
          `Array.from(document.querySelectorAll('main button')).some(b=>b.textContent==='Descargar Excel')`,
        )),
      );
      await call("Emulation.setDeviceMetricsOverride", {
        width: 390,
        height: 844,
        deviceScaleFactor: 1,
        mobile: true,
      });
      await pause(400);
      assert(
        await evaluate("document.documentElement.scrollWidth<=innerWidth"),
      );
      let screenshot = await call("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      fs.writeFileSync(
        path.resolve(".local/planogram-pilot/measurements-mobile.png"),
        Buffer.from(screenshot.data, "base64"),
      );
      await call("Emulation.setDeviceMetricsOverride", {
        width: 1440,
        height: 1000,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await evaluate(
        `(async()=>{await fetch('/api/auth/logout',{method:'POST'});await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'local-admin',password:'Isolated-local-password-2026!'})});location.hash='/planogramas';location.reload();})()`,
      );
      await wait(
        `document.querySelector('main h1')?.textContent==='Planogramas'&&!!document.querySelector('main tbody tr')`,
      );
      await click("Editar");
      await wait(
        `document.querySelectorAll('.ct-positions tbody tr').length===82&&document.querySelector('.ct-reference canvas')?.dataset.renderedPage==='1'`,
      );
      assert(
        await evaluate(
          `document.querySelector('[role=dialog]').textContent.includes('numeración por producto')`,
        ),
      );
      assert(
        !(await evaluate(
          `document.querySelector('[role=dialog]').textContent.includes('Carga masiva')`,
        )),
      );
      const names = await evaluate(
        `Array.from(document.querySelector('.ct-positions select').options).filter(o=>o.value&&!o.value.startsWith('legacy:')).map(o=>o.textContent.split(' · ')[0])`,
      );
      assert(
        names.every(
          (name, index) =>
            index === 0 ||
            names[index - 1].localeCompare(name, "es", {
              sensitivity: "base",
            }) <= 0,
        ),
        "Alphabetical product selector",
      );
      await click("Siguiente");
      await wait(
        `document.querySelector('.ct-reference').textContent.includes('Página 2 de 6')&&document.querySelector('.ct-reference canvas')?.dataset.renderedPage==='2'`,
      );
      await evaluate(
        `document.querySelector('.ct-reference').scrollIntoView({block:'start'})`,
      );
      await pause(500);
      screenshot = await call("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      fs.writeFileSync(
        path.resolve(".local/planogram-pilot/planogram-pdf.png"),
        Buffer.from(screenshot.data, "base64"),
      );
      for (let page=3;page<=6;page++) {
        await click('Siguiente');
        await wait(`document.querySelector('.ct-reference canvas')?.dataset.renderedPage==='${page}'`);
      }
      for (let page=5;page>=1;page--) {
        await click('Anterior');
        await wait(`document.querySelector('.ct-reference canvas')?.dataset.renderedPage==='${page}'`);
      }
      await click("Cancelar");
      proof.measurement_ui_verified = true;
      proof.pdf_ui_verified = true;
      proof.pdf_pages_rendered = [1,2,3,4,5,6];
      proof.product_selector_alphabetical = true;
      save();
      console.log(
        "PASS inherited measurement filters, own history, PDF pages, original numbering, alphabetic selector and mobile",
      );
    }
  } finally {
    await call("Page.close");
    socket.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
