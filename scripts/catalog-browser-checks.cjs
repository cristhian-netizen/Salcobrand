const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');

module.exports = async function catalogChecks(evaluate, wait, c) {
  const folder =
    process.env.CATALOG_QA_FILES ||
    fs.mkdtempSync(path.join(os.tmpdir(), 'salcobrand-catalog-browser-'));
  if (!process.env.CATALOG_QA_FILES) {
    const fixtureCode = `
from pathlib import Path
import sys
from pypdf import PdfWriter
from openpyxl import Workbook
from PIL import Image
folder = Path(sys.argv[1])
pdf = PdfWriter()
pdf.add_blank_page(width=300, height=400)
pdf.add_blank_page(width=300, height=400)
pdf.write(folder / 'reference.pdf')
Image.new('RGB', (80, 100), '#dceeee').save(folder / 'reference.png')
book = Workbook()
sheet = book.active
sheet.title = 'Productos'
sheet.append(['SubMarca','Categoría','SubCategoría','Nombre producto','Descripción','SKU','Tipo producto','Formato de venta','Cantidad','Alto (cm)','Espesor (cm)','Ancho (cm)','Volumen (cm³)','Precio (CLP)','Precio por kg/litro (CLP)','Código de barras'])
sheet.append(['Excel QA','Cuidado QA','QA','Producto Excel QA','Prueba','QA-XLSX','Envasado','ml',150,15,3,4,180,4990,'','0009988'])
book.save(folder / 'Productos-input.xlsx')
`;
    execFileSync(process.env.CATALOG_QA_PYTHON || 'python', [
      '-c',
      fixtureCode,
      folder,
    ]);
  }
  const suffix = Date.now().toString().slice(-8);
  const names = ['Zeta UI ' + suffix, 'Alfa UI ' + suffix];
  const planName = 'Planograma UI ' + suffix;
  const click = (text) =>
    evaluate(
      `Array.from(document.querySelectorAll('[role=dialog] button,main button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}&&!b.disabled).click()`,
    );
  const field = async (label, value) =>
    evaluate(`(()=>{
    const root=document.querySelector('[role=dialog]')||document.querySelector('main');
    const label=Array.from(root.querySelectorAll('label')).find(l=>Array.from(l.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim()===${JSON.stringify(label)});
    if(!label)throw Error('Missing field '+${JSON.stringify(label)});
    const input=label.querySelector('input,select,textarea');
    const prototype=input instanceof HTMLSelectElement?HTMLSelectElement.prototype:input instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,${JSON.stringify(value)});
    input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  })()`);
  const aria = async (label, value) =>
    evaluate(`(()=>{
    const input=document.querySelector('[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');
    const prototype=input instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,${JSON.stringify(value)});
    input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  })()`);
  const upload = async (selector, filename) => {
    const doc = await c.call('DOM.getDocument');
    const node = await c.call('DOM.querySelector', {
      nodeId: doc.root.nodeId,
      selector,
    });
    assert(node.nodeId, 'File input ' + selector);
    await c.call('DOM.setFileInputFiles', {
      nodeId: node.nodeId,
      files: [path.join(folder, filename)],
    });
  };
  const noModal = () => wait('!document.querySelector("[role=dialog]")');
  const bodyHas = (text) =>
    wait(
      `document.querySelector('main').textContent.includes(${JSON.stringify(text)})`,
    );
  await evaluate('location.hash="/productos"');
  await wait('document.querySelector("main h1")?.textContent==="Productos"');
  for (let index = 0; index < 2; index++) {
    await click('Crear producto');
    await wait('!!document.querySelector("[role=dialog] form")');
    for (const [label, value] of [
      ['Nombre del producto', names[index]],
      ['SKU', 'UI-' + suffix + '-' + index],
      ['Código de barras', '000' + suffix + index],
      ['Submarca', index ? 'Alfa QA' : 'Zeta QA'],
      ['Categoría', index ? 'Alfa categoría' : 'Zeta categoría'],
      ['Subcategoría', 'QA'],
      ['Cantidad', '150'],
      ['Alto (cm)', '15'],
      ['Ancho (cm)', '4'],
      ['Espesor (cm)', '3'],
      ['Precio CLP (opcional)', '4990'],
    ])
      await field(label, value);
    if (index === 0) {
      await upload('[role=dialog] input[type=file]', 'reference.png');
      await wait(
        'document.querySelector("[role=dialog] img")?.complete===true',
      );
    }
    await click('Guardar');
    await noModal();
    await bodyHas(names[index]);
  }
  for (const label of ['Submarca', 'Categoría']) {
    const options = await evaluate(
      `(()=>{const label=Array.from(document.querySelectorAll('main label')).find(l=>l.childNodes[0].textContent===${JSON.stringify(label)});return Array.from(label.querySelector('select').options).slice(1).map(o=>o.text)})()`,
    );
    assert.deepEqual(
      options,
      [...options].sort((a, b) =>
        a.localeCompare(b, 'es', { sensitivity: 'base' }),
      ),
      label + ' alphabetical',
    );
  }
  await c.call('Browser.setDownloadBehavior', {
    behavior: 'allow',
    downloadPath: folder,
  });
  await click('Descargar plantilla');
  for (
    let i = 0;
    i < 100 && !fs.existsSync(path.join(folder, 'Plantilla_Productos.xlsx'));
    i++
  )
    await new Promise((r) => setTimeout(r, 100));
  assert(
    fs.existsSync(path.join(folder, 'Plantilla_Productos.xlsx')),
    'Template download',
  );
  await upload('main .ct-upload input', 'Productos-input.xlsx');
  await wait(
    'Array.from(document.querySelectorAll("main button")).some(b=>b.textContent==="Confirmar importación"&&!b.disabled)',
  );
  await click('Confirmar importación');
  await bodyHas('productos creados');
  await click('Exportar Excel');
  for (
    let i = 0;
    i < 100 && !fs.existsSync(path.join(folder, 'Productos.xlsx'));
    i++
  )
    await new Promise((r) => setTimeout(r, 100));
  assert(
    fs.existsSync(path.join(folder, 'Productos.xlsx')),
    'Product export download',
  );

  await evaluate('location.hash="/planogramas"');
  await wait(
    'Array.from(document.querySelectorAll("main button")).some(b=>b.textContent==="Crear planograma"&&!b.disabled)',
  );
  assert.equal(
    await evaluate(
      'Array.from(document.querySelectorAll("main .sb-toolbar label")).every(l=>{const c=l.querySelector("input,select");return !c||c.getBoundingClientRect().right<=l.getBoundingClientRect().right+1})',
    ),
    true,
    'Filters fit their columns',
  );
  assert.equal(
    await evaluate(
      'document.querySelector("main").textContent.includes("Carga masiva")',
    ),
    false,
  );
  await click('Crear planograma');
  await wait('!!document.querySelector("[role=dialog] form")');
  const local = await evaluate(
    "fetch('/api/admin/stores').then(r=>r.json()).then(s=>s.find(s=>s.code==='L128'))",
  );
  await field('Nombre del planograma', planName);
  await field('Región', local.region);
  await field('Comuna', local.commune);
  await field('Punto de venta', 'L128');
  await upload('[role=dialog] input[type=file]', 'reference.png');
  await wait('document.querySelector("[role=dialog] img")?.complete===true');
  await upload('[role=dialog] input[type=file]', 'reference.pdf');
  await wait(
    'document.querySelector("[role=dialog] canvas")?.dataset.renderedPage==="1"',
  );
  await click('Siguiente');
  await wait(
    'document.querySelector("[role=dialog] canvas")?.dataset.renderedPage==="2"',
  );
  assert.equal(
    await evaluate(
      'document.querySelector("[role=dialog]").textContent.includes("Carga masiva")',
    ),
    false,
  );
  assert.equal(
    await evaluate(
      'document.querySelector("[role=dialog]").textContent.includes("Descargar plantilla")',
    ),
    false,
  );
  const products = await evaluate(
    "fetch('/api/admin/catalog').then(r=>r.json()).then(c=>c.products)",
  );
  await click('Añadir producto');
  const optionNames = await evaluate(
    'Array.from(document.querySelector("select[aria-label]").options).slice(1).map(o=>o.text)',
  );
  assert.deepEqual(
    optionNames,
    [...optionNames].sort((a, b) =>
      a.localeCompare(b, 'es', { sensitivity: 'base' }),
    ),
    'Plan product alphabetical',
  );
  await aria('Producto fila 1', products.find((p) => p.name === names[0]).id);
  await aria('Caras fila 1', '2');
  await click('Añadir producto');
  await aria('Producto fila 2', products.find((p) => p.name === names[1]).id);
  await click('Guardar');
  await wait(
    'document.querySelector("[role=dialog] [role=alert]")?.textContent.includes("superponen")',
  );
  await aria('Posición fila 2', '3');
  await c.call('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  assert.equal(
    await evaluate('document.documentElement.scrollWidth<=innerWidth'),
    true,
    'Plan form mobile overflow',
  );
  assert.equal(
    await evaluate(
      '(()=>{const b=Array.from(document.querySelectorAll("[role=dialog] form>.sb-actions button")).map(b=>b.getBoundingClientRect());return b.length===2&&Math.abs(b[0].top-b[1].top)<2})()',
    ),
    true,
    'Plan actions aligned',
  );
  await click('Guardar');
  await noModal();
  await bodyHas(planName);
  await c.call('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });
  const saved = await evaluate(
    `fetch('/api/admin/catalog').then(r=>r.json()).then(c=>c.planograms.find(p=>p.name===${JSON.stringify(planName)})).then(p=>fetch('/api/admin/catalog/planograms/'+p.id)).then(r=>r.json())`,
  );
  assert.equal(saved.document_page, 2);
  assert.equal(saved.positionRows.length, 2);
  assert.equal(
    saved.items.reduce((n, i) => n + i.expected_facings, 0),
    3,
  );
  const shot = await c.call('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  fs.writeFileSync(
    path.join(folder, 'planograms-desktop.png'),
    Buffer.from(shot.data, 'base64'),
  );
  await evaluate(
    `Array.from(document.querySelectorAll('main table tbody tr')).find(r=>r.textContent.includes(${JSON.stringify(planName)})).querySelector('button').click()`,
  );
  await wait('!!document.querySelector("[role=dialog] form")');
  await c.call('Emulation.setDeviceMetricsOverride', {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await evaluate(
    'document.querySelector("[role=dialog]").scrollTop=document.querySelector("[role=dialog]").scrollHeight',
  );
  const mobile = await c.call('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  fs.writeFileSync(
    path.join(folder, 'planogram-mobile.png'),
    Buffer.from(mobile.data, 'base64'),
  );
  await click('Cancelar');
  await noModal();
  await c.call('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });

  await evaluate('location.hash="/productos"');
  await wait('document.querySelector("main h1")?.textContent==="Productos"');
  await bodyHas(names[0]);
  await evaluate(
    `Array.from(document.querySelectorAll('main table tbody tr')).find(r=>r.textContent.includes(${JSON.stringify(names[0])})).querySelector('button').click()`,
  );
  await wait('!!document.querySelector("[role=dialog] form")');
  await click('Eliminar producto');
  await click('Confirmar eliminación');
  await wait(
    `document.querySelector('[role=dialog] [role=alert]')?.textContent.includes(${JSON.stringify(planName)})`,
  );
  await click('Cancelar');
  await noModal();
  await evaluate('location.hash="/planogramas"');
  await bodyHas(planName);
  await evaluate(
    `Array.from(document.querySelectorAll('main table tbody tr')).find(r=>r.textContent.includes(${JSON.stringify(planName)})).querySelector('button.remove').click()`,
  );
  await wait('!!document.querySelector("[role=dialog]")');
  await click('Confirmar eliminación');
  await noModal();
  await evaluate('location.hash="/productos"');
  await bodyHas(names[0]);
  await field('Buscar', suffix);
  await click('Seleccionar todo');
  await click('Eliminar producto(s)');
  await click('Confirmar eliminación');
  await noModal();
  await wait(
    'document.querySelector("main").textContent.includes("No hay productos con estos filtros")',
  );
  console.log(
    'PASS UI catalog: product CRUD/selection, alphabetical filters, XLSX preview/export, PDF pages, plan faces/overlap, guarded deletion and mobile alignment',
  );
  console.log('Visual QA', folder);
};
