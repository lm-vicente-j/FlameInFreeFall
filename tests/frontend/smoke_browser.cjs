// Start the prepared Flask application first. Uses Node's built-in CDP client.
// Run: node tests/frontend/smoke_browser.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const root = path.resolve(__dirname, '../..');
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5000';
const browserPath = process.env.BROWSER_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'flame-frontend-'));
const browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
    { stdio: 'ignore', windowsHide: true });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let command;

async function until(check, description, timeout = 20000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        if (await check()) return;
        await delay(100);
    }
    throw new Error('Timed out: ' + description);
}

(async () => {
    let port;
    await until(() => {
        const active = path.join(profile, 'DevToolsActivePort');
        if (!fs.existsSync(active)) return false;
        port = fs.readFileSync(active, 'utf8').split('\n')[0];
        return Boolean(port);
    }, 'headless browser startup');
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let counter = 0;
    const pending = new Map();
    const runtimeErrors = [];
    const externalRequests = [];
    socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.id && pending.has(message.id)) {
            const { resolve, reject, timer } = pending.get(message.id);
            pending.delete(message.id);
            clearTimeout(timer);
            if (message.error) reject(new Error(message.error.message));
            else resolve(message.result);
        }
        if (message.method === 'Runtime.exceptionThrown') runtimeErrors.push(message.params.exceptionDetails);
        if (message.method === 'Network.requestWillBeSent') {
            const url = message.params.request.url;
            if (/^https?:/.test(url) && !url.startsWith(base + '/')) externalRequests.push(url);
        }
        if (message.method === 'Fetch.requestPaused') {
            command('Fetch.fulfillRequest', { requestId: message.params.requestId, responseCode: 503,
                responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
                body: Buffer.from(JSON.stringify({ error: { code: 'data_unavailable' } })).toString('base64') });
        }
    };
    command = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++counter;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 20000);
        pending.set(id, { resolve, reject, timer });
        socket.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
        const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
        return result.result.value;
    };
    const checks = [];
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Page.navigate', { url: base + '/' });
    await until(() => evaluate(`document.querySelector('#estado-estudios')?.textContent.includes('24 investigaciones') &&
        document.querySelector('#estado-runs')?.textContent.includes('2009') &&
        document.querySelector('#estado-archivos')?.textContent.includes('archivos catalogados')`), 'real-data load');
    assert.equal(await evaluate(`document.querySelectorAll('.tarjeta').length`), 20);
    assert.equal(await evaluate(`document.querySelectorAll('#investigacion-archivos option').length`), 24);
    assert.ok(await evaluate(`Boolean(Chart.getChart(document.querySelector('#graficoRuns')))`));
    checks.push('Real data: 24 investigations, 2009 source rows, local chart loaded');

    await evaluate(`document.querySelector('#paginacion-estudios button:last-child').click()`);
    await until(() => evaluate(`document.querySelector('#paginacion-estudios')?.textContent.includes('21–24 de 24')`),
        'last study page');
    assert.equal(await evaluate(`document.querySelectorAll('.tarjeta').length`), 4);
    checks.push('Study pagination reaches all 24 investigations');

    await evaluate(`document.querySelector('#buscador').value = 'FLEX';
        document.querySelector('#buscador').dispatchEvent(new Event('input', { bubbles: true }))`);
    await until(() => evaluate(`document.querySelector('.tarjeta h3')?.textContent.includes('Flame Extinguishment')`), 'search');
    await evaluate(`document.querySelector('.tarjeta button').click()`);
    await until(() => evaluate(`document.querySelector('#detalle-estudio')?.textContent.includes('Afirmaciones de la ficha')`),
        'study detail');
    assert.ok(await evaluate(`document.querySelector('#detalle-estudio').textContent.includes('Revisión: Aprobada')`));
    await evaluate(`document.querySelector('#btn-cerrar-estudio').click(); document.querySelectorAll('.tarjeta button')[1].click()`);
    await until(() => evaluate(`document.querySelector('#evidence-source')?.hidden === false`), 'exact evidence');
    const evidenceId = await evaluate(`document.querySelector('#selector-evidence').value`);
    const evidence = await (await fetch(base + '/api/evidence/' + encodeURIComponent(evidenceId))).json();
    assert.equal(await evaluate(`document.querySelector('#evidence-text').textContent`), evidence.data.excerpt);
    checks.push('Server search, approved study detail and exact encoded evidence');
    await evaluate(`document.querySelector('#btn-cerrar-modal').click()`);

    await evaluate(`document.querySelector('#investigacion-archivos').value = 'PSI-99';
        document.querySelector('#investigacion-archivos').dispatchEvent(new Event('change'))`);
    await until(() => evaluate(`document.querySelector('#estado-archivos').textContent.includes('PSI-99 ·') &&
        document.querySelectorAll('#tabla-archivos-body tr').length === 20`), 'file selection');
    await evaluate(`document.querySelector('#paginacion-archivos button:last-child').click()`);
    await until(() => evaluate(`document.querySelector('#paginacion-archivos').textContent.includes('21–40')`), 'file page two');
    await evaluate(`document.querySelector('#extension-archivo').value = '.csv';
        document.querySelector('#categoria-archivo').value = 'Experimental table';
        document.querySelector('#nombre-archivo').value = 'SAFFIRE';
        document.querySelector('#filtros-archivos').requestSubmit()`);
    await until(() => evaluate(`document.querySelector('#tabla-archivos-body')?.textContent.includes('SAFFIRE-2.csv')`),
        'file filters');
    assert.ok(await evaluate(`document.querySelector('#tabla-archivos-body a').href.endsWith('PSI-99')`));
    checks.push('Investigation selection, file pagination and all three file filters');

    await evaluate(`document.querySelector('#nombre-archivo').value = 'no-such-file-fixture';
        document.querySelector('#filtros-archivos').requestSubmit()`);
    await until(() => evaluate(`document.querySelector('#tabla-archivos-body').textContent.includes('No se encontraron archivos')`),
        'empty file state');
    checks.push('Explicit empty file state');

    await command('Fetch.enable', { patterns: [{ urlPattern: base + '/api/studies*' }] });
    await evaluate(`document.querySelector('#btn-limpiar').click()`);
    await until(() => evaluate(`document.querySelector('#estado-estudios').textContent.includes('HTTP 503')`), 'backend failure');
    assert.equal(await evaluate(`document.querySelectorAll('.tarjeta').length`), 0);
    await command('Fetch.disable');
    await evaluate(`document.querySelector('#btn-limpiar').click()`);
    await until(() => evaluate(`document.querySelectorAll('.tarjeta').length === 20`), 'recovery after backend failure');
    checks.push('Backend 503 stays visible without mock fallback; recovery succeeds');

    await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    await delay(200);
    assert.ok(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
    checks.push('Mobile viewport has no page overflow');
    await command('Emulation.clearDeviceMetricsOverride');
    await command('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
    await evaluate(`document.querySelector('#buscador').value = 'FLEX';
        document.querySelector('#buscador').dispatchEvent(new Event('input', { bubbles: true }))`);
    await until(() => evaluate(`document.querySelector('.tarjeta h3')?.textContent.includes('Flame Extinguishment')`), 'screenshot');
    await delay(1200);
    const metrics = await command('Page.getLayoutMetrics');
    const screenshot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
        clip: { x: 0, y: 0, width: metrics.cssContentSize.width, height: metrics.cssContentSize.height, scale: 1 } });
    fs.mkdirSync(path.join(root, 'res'), { recursive: true });
    fs.writeFileSync(path.join(root, 'res/frontend-smoke.png'), Buffer.from(screenshot.data, 'base64'));
    assert.deepEqual(runtimeErrors, []);
    assert.deepEqual(externalRequests, []);
    checks.push('No JavaScript exceptions or external page requests');
    console.log(JSON.stringify({ checks, screenshot: 'res/frontend-smoke.png' }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
    if (socket?.readyState === WebSocket.OPEN && command) {
        await command('Browser.close').catch(() => {});
        socket.close();
    }
    browser.kill();
    // The unique temporary browser profile is separate from the user's browser.
});
