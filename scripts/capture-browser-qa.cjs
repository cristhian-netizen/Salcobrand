// Actual local application, authenticated remote development model, user-provided photo.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WS = require("../web/node_modules/next/dist/compiled/ws");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const base = process.env.CAPTURE_QA_URL || "http://localhost:3001";
  assert(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
  const proofFile = path.resolve(".local/capture-dev/proof.json");
  const proof = JSON.parse(fs.readFileSync(proofFile, "utf8"));
  const debug = "http://127.0.0.1:9225";
  const tab = await fetch(debug + "/json/new?about:blank", {
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
  const evaluate = async (expression) => {
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
  };
  const wait = async (expression, seconds = 60) => {
    const start = Date.now();
    while (Date.now() - start < seconds * 1000) {
      if (await evaluate(expression)) return;
      await pause(250);
    }
    throw Error(
      "Timeout " +
        expression +
        "\n" +
        (await evaluate("document.body.innerText.slice(0,1200)")),
    );
  };
  const click = (text) =>
    evaluate(
      `Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}&&!b.disabled).click()`,
    );
  async function login(username) {
    await call("Page.navigate", { url: base });
    await wait('!!document.querySelector("input[name=username]")');
    await wait(
      'Object.keys(document.querySelector("form")).some(key=>key.startsWith("__reactProps"))',
    );
    await evaluate(
      `document.querySelector('input[name=username]').value=${JSON.stringify(username)};document.querySelector('input[name=password]').value='Isolated-local-password-2026!';document.querySelector('form').requestSubmit()`,
    );
    await wait('!!document.querySelector("nav[aria-label=Principal]")');
    const current = await evaluate("fetch('/api/auth/me').then(r=>r.json())");
    assert.equal(current.environment, "capture-dev");
  }
  async function inspect(readingId, name) {
    const reading = await evaluate(
      `fetch('/api/readings/'+${readingId}).then(r=>r.json())`,
    );
    assert.equal(reading.point_id, "pdv-001");
    assert(reading.products.length > 0, "Actual model products");
    assert(reading.total_facings > 0, "Actual model facings");
    assert.equal(
      reading.engine.remote.base_url,
      "https://salcobrand-dev.neuramorphic.ai",
    );
    await wait(
      'Array.from(document.querySelectorAll(".sb-photos img")).some(i=>i.complete&&i.naturalWidth>0)',
    );
    const product = reading.products.find(
      (p) => p.image_index != null && p.item_index != null,
    );
    if (product) {
      const crop = await evaluate(
        `fetch('/api/readings/${readingId}/crops/${product.image_index}/${product.item_index}.jpg').then(async r=>{const b=await r.blob();const i=await createImageBitmap(b);return {status:r.status,type:b.type,width:i.width,height:i.height}})`,
      );
      assert.equal(crop.status, 200);
      assert.equal(crop.type, "image/jpeg");
      assert(crop.width > 0 && crop.height > 0);
    }
    const folder = path.dirname(proofFile);
    await call("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await pause(400);
    const screenshot = await call("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    fs.writeFileSync(
      path.join(folder, name + ".png"),
      Buffer.from(screenshot.data, "base64"),
    );
    await call("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: true,
    });
    await evaluate(`document.querySelector('button[aria-label="Cerrar menú"]')?.click()`);
    await pause(400);
    assert.equal(
      await evaluate(`Array.from(document.querySelectorAll('.sb-metric')).every(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=visualViewport.width})`),
      true,
      "Mobile metrics must fit inside the visible viewport",
    );
    assert.equal(
      await evaluate("document.documentElement.scrollWidth<=innerWidth"),
      true,
      "Mobile reading overflow",
    );
    const mobile = await call("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    fs.writeFileSync(
      path.join(folder, name + "-mobile.png"),
      Buffer.from(mobile.data, "base64"),
    );
    await call("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });
    return reading;
  }
  try {
    await call("Page.enable");
    await call("Network.clearBrowserCookies");
    await login("local-analyst");
    await evaluate(
      `localStorage.setItem('nv-capture-job:local-analyst',${JSON.stringify(proof.job_id)});location.hash='/escanear/pdv-001'`,
    );
    await wait(
      'document.querySelector("main h1")?.textContent.startsWith("Lectura #") || Array.from(document.querySelectorAll("main button")).some(b=>b.textContent==="Recuperar resultado")',
    );
    const recovery = await evaluate(
      'Array.from(document.querySelectorAll("main button")).some(b=>b.textContent==="Recuperar resultado")',
    );
    if (recovery) await click("Recuperar resultado");
    await wait(
      'document.querySelector("main h1")?.textContent.startsWith("Lectura #")',
      180,
    );
    const firstId = await evaluate(
      'Number(document.querySelector("main h1").textContent.split("#")[1])',
    );
    const first = await inspect(firstId, "capture-real-analyst");
    proof.status = "done";
    proof.reading_id = first.id;
    proof.remote = first.engine.remote;
    proof.products = first.products.length;
    proof.facings = first.total_facings;
    fs.writeFileSync(proofFile, JSON.stringify(proof, null, 2));
    await evaluate("location.reload()");
    await wait(
      `document.querySelector('main h1')?.textContent==='Lectura #${first.id}'`,
    );
    console.log(
      "PASS recovered real measurement",
      JSON.stringify({
        local: first.id,
        remote: first.engine.remote.reading_id,
        products: first.products.length,
        facings: first.total_facings,
      }),
    );
    if (process.env.CAPTURE_QA_PHOTO) {
      await click("Cerrar sesión");
      await wait('!!document.querySelector("input[name=username]")');
      await login("local-replenisher");
      let secondJob =
        proof.browser_capture?.job_id ||
        (await evaluate(
          'localStorage.getItem("nv-capture-job:local-replenisher")',
        ));
      if (secondJob)
        await evaluate(
          `localStorage.setItem('nv-capture-job:local-replenisher',${JSON.stringify(secondJob)})`,
        );
      await evaluate('location.hash="/escanear/pdv-001"');
      if (!secondJob) {
        await wait(
          '!!document.querySelector("input[type=file]")&&!document.querySelector("input[type=file]").disabled',
        );
        const doc = await call("DOM.getDocument");
        const input = await call("DOM.querySelector", {
          nodeId: doc.root.nodeId,
          selector: "input[type=file]",
        });
        await call("DOM.setFileInputFiles", {
          nodeId: input.nodeId,
          files: [path.resolve(process.env.CAPTURE_QA_PHOTO)],
        });
        await wait(
          'document.querySelectorAll(".sb-previews figure").length===1',
        );
        await wait(
          'Array.from(document.querySelectorAll("main button")).some(b=>b.textContent==="Analizar góndola"&&!b.disabled)',
        );
        await click("Analizar góndola");
        await wait(
          '!!localStorage.getItem("nv-capture-job:local-replenisher")',
        );
        secondJob = await evaluate(
          'localStorage.getItem("nv-capture-job:local-replenisher")',
        );
      }
      proof.browser_capture = { job_id: secondJob };
      fs.writeFileSync(proofFile, JSON.stringify(proof, null, 2));
      await evaluate("location.reload()");
      await wait(
        'document.querySelector("main h1")?.textContent.startsWith("Lectura #")',
        900,
      );
      const ownId = await evaluate(
        'Number(document.querySelector("main h1").textContent.split("#")[1])',
      );
      const own = await inspect(ownId, "capture-real-replenisher");
      assert.equal(own.captured_by, "local-replenisher");
      assert.equal(
        await evaluate(`fetch('/api/readings/${first.id}').then(r=>r.status)`),
        403,
      );
      assert.equal(
        await evaluate(
          `fetch('/api/analysis-jobs/${proof.job_id}').then(r=>r.status)`,
        ),
        404,
      );
      proof.browser_capture = {
        job_id: secondJob,
        reading_id: own.id,
        remote: own.engine.remote,
        products: own.products.length,
        facings: own.total_facings,
      };
      console.log(
        "PASS real browser upload, reload and scoped history",
        JSON.stringify(proof.browser_capture),
      );
    }
    fs.writeFileSync(proofFile, JSON.stringify(proof, null, 2));
    console.log("PASS capture API real, images, crops and mobile");
    await click("Cerrar sesión");
  } finally {
    socket.close();
    await fetch(debug + "/json/close/" + tab.id);
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
