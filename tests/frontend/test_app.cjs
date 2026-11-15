// Run with Node's built-in test runner; no npm packages are required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');

class Element {
    constructor(tag = 'div') {
        this.tag = tag;
        this.children = [];
        this.listeners = {};
        this.attributes = {};
        this.value = '';
        this.open = false;
        this.classList = { toggle() {} };
    }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return (this.text || '') + this.children.map(child => child.textContent).join(' '); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.text = ''; this.children = [...children]; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    removeAttribute(key) { delete this.attributes[key]; delete this[key]; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    scrollIntoView() {}
    getContext() { return {}; }
}

function setup(respond = () => ({ data: [], meta: {} })) {
    const nodes = new Map();
    const requests = [];
    const document = {
        createElement: tag => new Element(tag),
        getElementById: id => {
            if (!nodes.has(id)) nodes.set(id, new Element());
            return nodes.get(id);
        },
        addEventListener() {},
        querySelectorAll: () => [],
    };
    const context = vm.createContext({ document, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
        fetch: async (url, options) => {
            requests.push(url);
            const result = await respond(url, options);
            return { ok: result.status === undefined || result.status < 400,
                status: result.status || 200, json: async () => result.body || result };
        },
    });
    vm.runInContext(source, context);
    return { context, requests, get: document.getElementById };
}

const quantity = (min, max = min, unit = 'percent', method = 'parsed') => ({ min, max, unit, method });
const run = (o2, pressure) => ({ id: 'PSI-69:flex:1', kind: 'run', review_status: 'pending',
    conditions: { o2_percent: o2, pressure_kpa: pressure }, outcomes: [] });

test('unknowns, intervals and unsupported units never become graph points; valid zero survives', () => {
    const { context } = setup();
    const pressure = quantity(100, 100, 'kPa');
    const records = [run(quantity(0), pressure), run(quantity(null), pressure), run(quantity(18, 22), pressure),
        run(quantity(21, 21, 'fraction'), pressure), run(quantity(21, 21, 'percent', 'unknown'), pressure)];
    const points = context.puntosConocidos(records);
    assert.equal(points.length, 1);
    assert.equal(points[0].x, 0);
    assert.equal(context.formatearCantidad(quantity(18, 22), 'percent'), '18–22');
    assert.equal(context.formatearCantidad(quantity(null), 'percent'), 'Desconocido');
});

test('the table preserves both outcome gravities and does not invent missing gravity', () => {
    const { context, get } = setup();
    const record = run(quantity(21), quantity(100, 100, 'kPa'));
    record.outcomes = [{ type: 'burn_time', gravity: 'normal' }, { type: 'spread_rate', gravity: 'microgravity' }];
    context.llenarTablaRuns([record, { ...record, outcomes: [] }]);
    const rows = get('tabla-runs-body').children;
    assert.match(rows[0].textContent, /burn_time: 1 g ground test/);
    assert.match(rows[0].textContent, /spread_rate: Microgravedad/);
    assert.match(rows[1].textContent, /Sin resultados/);
    assert.match(rows[0].textContent, /Pendiente/);
});

test('graph references retain psia-to-kPa conversion and do not clip valid pressures', () => {
    const { context } = setup();
    let chart;
    context.Chart = function (_, config) { chart = config; this.destroy = () => {}; };
    context.dibujarGrafico([run(quantity(45), quantity(150, 150, 'kPa'))]);
    assert.equal(chart.data.datasets[0].data[0].y, 150);
    assert.equal(chart.options.scales.y.max, undefined);
    assert.equal(chart.data.datasets[1].data.length, 3);
    assert.ok(Math.abs(chart.data.datasets[1].data[1].y - 70.3265) < 0.001);
});

test('search goes to the server with the full query and safety filter', async () => {
    const { context, requests } = setup(() => ({ data: [], meta: { total: 0, offset: 0, limit: 20, matches: [] } }));
    await context.aplicarFiltros('smoke & aerosol', 'detection');
    const url = new URL(requests[0], 'http://localhost');
    assert.equal(url.searchParams.get('q'), 'smoke & aerosol');
    assert.equal(url.searchParams.get('safety_category'), 'detection');
    assert.equal(url.searchParams.get('limit'), '20');
});

test('HTTP failures remain errors instead of silently using mock or empty results', async () => {
    const { context, get, requests } = setup(() => ({ status: 503,
        body: { error: { code: 'data_unavailable' } } }));
    await context.cargarEstudios();
    assert.match(get('estado-estudios').textContent, /Datos no disponibles/);
    assert.equal(get('contenedor-tarjetas').children.length, 0);
    assert.equal(requests.length, 1);
    assert.ok(requests.every(url => !url.includes('mock')));
});

test('study pagination reaches the final four investigations without claiming the first page is complete', async () => {
    const { context, get } = setup();
    let offset;
    context.mostrarPaginacion('pager', { offset: 0, limit: 20, total: 24 }, value => { offset = value; });
    const [previous, status, next] = get('pager').children;
    assert.equal(previous.disabled, true);
    assert.equal(next.disabled, false);
    assert.equal(status.textContent, '1–20 de 24');
    next.listeners.click();
    assert.equal(offset, 20);
    context.mostrarPaginacion('pager', { offset: 20, limit: 20, total: 24 }, () => {});
    assert.equal(get('pager').children[2].disabled, true);
});

test('evidence IDs including # are encoded, with exact excerpts and original locators', async () => {
    const card = JSON.parse(fs.readFileSync(path.join(root, 'data/cards/PSI-69.json'), 'utf8'));
    const evidence = card.evidence.find(item => item.locator.kind === 'pdf');
    const { context, requests, get } = setup(() => ({ data: evidence, meta: { state: 'available' } }));
    get('selector-evidence').value = evidence.id;
    await context.cargarEvidencia();
    assert.equal(requests[0], '/api/evidence/' + encodeURIComponent(evidence.id));
    assert.ok(requests[0].includes('%23'));
    assert.equal(get('evidence-text').textContent, evidence.excerpt);
    assert.match(get('evidence-locator').textContent, /Página: 9/);
    assert.ok(get('evidence-locator').textContent.includes(evidence.locator.filename));
    assert.equal(get('evidence-source').href, evidence.source_url);
});

test('unavailable evidence never leaves a stale source link or invented quote', async () => {
    const { context, get } = setup(() => ({ status: 503, body: { error: { code: 'data_unavailable' } } }));
    get('selector-evidence').value = 'PSI-69:meta:objective#0123456789ab';
    get('evidence-source').hidden = false;
    await context.cargarEvidencia();
    assert.match(get('evidence-text').textContent, /Datos no disponibles/);
    assert.equal(get('evidence-source').hidden, true);
});

test('file filters and pagination reach the selected investigation, not a hardcoded accession', async () => {
    const { context, requests, get } = setup(() => ({ data: [], meta: { total: 0, offset: 40, limit: 20 } }));
    get('investigacion-archivos').value = 'PSI-99';
    get('nombre-archivo').value = 'sample & flame';
    get('categoria-archivo').value = 'Experimental table';
    get('extension-archivo').value = '.CSV';
    await context.cargarArchivos(40);
    const url = new URL(requests[0], 'http://localhost');
    assert.equal(url.pathname, '/api/studies/PSI-99/files');
    assert.equal(url.searchParams.get('filename'), 'sample & flame');
    assert.equal(url.searchParams.get('category'), 'Experimental table');
    assert.equal(url.searchParams.get('extension'), '.CSV');
    assert.equal(url.searchParams.get('offset'), '40');
});

test('file metadata preserves zero bytes, hidden access and the difference between hash and processing', () => {
    const { context, get } = setup();
    context.llenarTablaArchivos([{ accession: 'PSI-99', filename: '<img onerror=attack>', version: 2,
        bytes: 0, access: 'hidden', category: 'Data', extension: '.csv', key: 'source/key', download_sha256: 'abc' }]);
    const row = get('tabla-archivos-body').children[0];
    assert.match(row.textContent, /0.00 MB/);
    assert.match(row.textContent, /Oculto/);
    assert.match(row.textContent, /procesamiento no indicado/);
    assert.equal(row.children[0].children.length, 0);
    assert.equal(row.children[6].children[0].href,
        'https://psi.nasa.gov/physci/repo/data/investigations/PSI-99');
});

test('source links refuse executable URL schemes', () => {
    const { context } = setup();
    const link = new Element('a');
    context.enlaceSeguro(link, 'javascript:alert(1)');
    assert.equal(link.hidden, true);
    assert.equal(link.href, undefined);
});

test('HTML serves local chart assets and contains every literal JavaScript element ID', () => {
    const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
    assert.ok(!/<script[^>]+src=["']https?:/i.test(html));
    for (const [, id] of source.matchAll(/getElementById\("([^"]+)"\)/g)) assert.ok(html.includes('id="' + id + '"'), id);
    assert.ok(fs.existsSync(path.join(root, 'static/vendor/chart.umd.min.js')));
});
