// Browser integration test for the research interface (issue #31).
// Start the prepared Flask application first (real data). Uses Node's built-in CDP client only.
// Run: node tests/frontend/smoke_browser.cjs
// Env: FRONTEND_URL, BROWSER_PATH, SMOKE_COPY_DIR (optional: also copy screenshots there).
// Screenshots go to res/smoke/ (ignored by git). Failed checks are listed at the end; exit code 1 if any failed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const root = path.resolve(__dirname, '../..');
const base = (process.env.FRONTEND_URL || 'http://127.0.0.1:5000').replace(/\/$/, '');
const origin = new URL(base).origin;
const browserPath = process.env.BROWSER_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const shotDir = path.join(root, 'res', 'smoke');
const copyDir = process.env.SMOKE_COPY_DIR || '';
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'flame-frontend-'));
const browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-first-run',
    '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
    { stdio: 'ignore', windowsHide: true });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let command;

async function until(check, description, timeout = 20000) {
    const deadline = Date.now() + timeout;
    let last;
    while (Date.now() < deadline) {
        try { if (await check()) return; } catch (error) { last = error; }
        await delay(100);
    }
    throw new Error('Timed out: ' + description + (last ? ' (' + last.message + ')' : ''));
}

// RFC 4180 parser: quoted cells may contain commas and line breaks.
function parseCsv(text) {
    const rows = [];
    let row = [], cell = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (quoted) {
            if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
            else if (ch === '"') quoted = false;
            else cell += ch;
        } else if (ch === '"') quoted = true;
        else if (ch === ',') { row.push(cell); cell = ''; }
        else if (ch === '\n' || ch === '\r') {
            if (ch === '\r' && text[i + 1] === '\n') i++;
            row.push(cell); rows.push(row); row = []; cell = '';
        } else cell += ch;
    }
    if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
    return rows;
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
    const requests = [];
    let intercept = false;
    socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.id && pending.has(message.id)) {
            const { resolve, reject, timer } = pending.get(message.id);
            pending.delete(message.id);
            clearTimeout(timer);
            if (message.error) reject(new Error(message.error.message));
            else resolve(message.result);
        }
        if (message.method === 'Runtime.exceptionThrown') {
            const details = message.params.exceptionDetails;
            runtimeErrors.push((details.exception && details.exception.description) || details.text);
        }
        if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
            runtimeErrors.push('console.error: ' + message.params.args.map(a => a.value || a.description).join(' '));
        }
        if (message.method === 'Network.requestWillBeSent') {
            const url = message.params.request.url;
            requests.push(url);
            if (/^(https?|wss?|ftp):/i.test(url) && new URL(url).origin !== origin) externalRequests.push(url);
        }
        if (message.method === 'Fetch.requestPaused') {
            const requestId = message.params.requestId;
            if (intercept) {
                command('Fetch.fulfillRequest', { requestId, responseCode: 503,
                    responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
                    body: Buffer.from(JSON.stringify({ error: { code: 'data_unavailable',
                        message: 'Prepared research cards are unavailable.', details: { state: 'unavailable' } } })).toString('base64') }).catch(() => {});
            } else command('Fetch.continueRequest', { requestId }).catch(() => {});
        }
    };
    command = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++counter;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 30000);
        pending.set(id, { resolve, reject, timer });
        socket.send(JSON.stringify({ id, method, params }));
    });
    const ev = async expression => {
        const result = await command('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails.exception || result.exceptionDetails));
        return result.result.value;
    };
    const apiGet = async p => (await fetch(base + p)).json();

    // ---------- Harness ----------
    const results = [];
    async function check(name, fn) {
        try { await fn(); results.push({ name, ok: true }); console.log('PASS  ' + name); }
        catch (error) {
            try {
                error.message += ' | state: ' + await ev(`JSON.stringify({ hash: location.hash, status: document.querySelector('#view .status')?.textContent, items: document.querySelectorAll('.study-item').length, dialogs: [...document.querySelectorAll('dialog')].map(d => d.className + ':' + d.open + ':' + d.textContent.slice(0, 80)) })`);
            } catch { /* page state unavailable */ }
            results.push({ name, ok: false, error: error.message.split('\n').slice(0, 6).join(' | ') });
            console.log('FAIL  ' + name + '\n      ' + error.message.split('\n').slice(0, 6).join('\n      '));
        }
    }
    const savedShots = [];
    async function shot(name, { full = true } = {}) {
        fs.mkdirSync(shotDir, { recursive: true });
        await delay(250);
        const metrics = await command('Page.getLayoutMetrics');
        const width = metrics.cssVisualViewport.clientWidth;
        const height = full ? Math.min(Math.ceil(metrics.cssContentSize.height), 7000) : metrics.cssVisualViewport.clientHeight;
        const image = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: full,
            clip: { x: 0, y: 0, width, height, scale: 1 } });
        const file = path.join(shotDir, name + '.png');
        fs.writeFileSync(file, Buffer.from(image.data, 'base64'));
        if (copyDir) { fs.mkdirSync(copyDir, { recursive: true }); fs.copyFileSync(file, path.join(copyDir, name + '.png')); }
        savedShots.push(path.relative(root, file));
    }
    // Fresh page at a hash route (resets all in-page state).
    async function fresh(hash) {
        await command('Page.navigate', { url: 'about:blank' });
        await command('Page.navigate', { url: base + '/' + hash });
        await until(() => ev(`document.readyState === 'complete' && Boolean(window.FF) && document.getElementById('view').children.length > 0`), 'page load ' + hash);
    }
    const go = hash => ev(`location.hash = ${JSON.stringify(hash)}`);
    const text = sel => ev(`document.querySelector(${JSON.stringify(sel)})?.textContent ?? null`);
    const count = sel => ev(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
    const click = sel => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); if (!n) throw new Error('missing ' + ${JSON.stringify(sel)}); n.click(); return true; })()`);
    const clickByText = (sel, label) => ev(`(() => { const n = [...document.querySelectorAll(${JSON.stringify(sel)})].find(x => x.textContent.trim() === ${JSON.stringify(label)}); if (!n) throw new Error('no ${sel} with text ${label}'); n.click(); return true; })()`);
    const setInput = (sel, value) => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); n.value = ${JSON.stringify(value)}; n.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
    const hash = () => ev('location.hash');
    const key = async name => {
        await command('Input.dispatchKeyEvent', { type: 'keyDown', key: name, code: name, windowsVirtualKeyCode: 27 });
        await command('Input.dispatchKeyEvent', { type: 'keyUp', key: name, code: name, windowsVirtualKeyCode: 27 });
    };
    // Capture what FF.download hands to the browser, without letting the download happen.
    const captureDownloads = () => ev(`(() => {
        window.__dl = [];
        const create = URL.createObjectURL.bind(URL);
        URL.createObjectURL = blob => { const item = { type: blob.type, text: null }; window.__dl.push(item); blob.text().then(t => { item.text = t; }); return create(blob); };
        HTMLAnchorElement.prototype.click = function () { const last = window.__dl[window.__dl.length - 1]; if (last) last.filename = this.download; };
        return true; })()`);
    const nextDownload = async () => {
        await until(() => ev('window.__dl.length > 0 && window.__dl[0].text !== null'), 'download captured');
        return ev('(() => { const d = window.__dl.shift(); return d; })()');
    };
    const visibleError = sel => ev(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); return Boolean(n) && n.textContent.trim().length > 0 && n.getBoundingClientRect().height > 0; })()`);

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    const ROUTES = {
        studies: '#/studies',
        study: '#/study/PSI-69',
        compare: '#/compare/PSI-69/PSI-99',
        files: '#/files/PSI-69?category=Experimental%20table',
        conditions: '#/conditions?fuel_class=solid',
        about: '#/about',
    };
    const loaded = {
        studies: () => count('.study-item').then(n => n === 24),
        study: () => count('#references .reference').then(n => n > 0),
        compare: () => count('.cmp-table tbody tr').then(n => n > 0),
        files: () => count('.files-table tbody tr').then(n => n > 0),
        conditions: () => ev(`Boolean(document.querySelector('.cond-svg')) && document.querySelectorAll('.runs-table tbody tr').length > 0`),
        about: () => count('#view h1').then(n => n > 0),
    };

    // ---------- 1. Investigations list ----------
    await check('1a studies: 24 investigations on one page, header snapshot shows counts', async () => {
        await fresh(ROUTES.studies);
        await until(loaded.studies, '24 study items');
        assert.equal(await count('.study-item'), 24);
        assert.equal(await count('.study-list + .pagination button, .pagination button'), 0, 'no pager expected');
        await until(() => ev(`/24 investigations/.test(document.getElementById('snapshot-status').textContent)`), 'header counts');
        const header = await text('#snapshot-status');
        assert.match(header, /24 investigations/);
        assert.match(header, /2,009 source rows/);
        assert.match(await text('#view .status'), /24 investigations/);
        await shot('desktop-studies');
    });
    await check('1b studies: search "extinction" updates URL q=, shows <mark> and Relevance rank', async () => {
        await setInput('#study-search', 'extinction');
        await until(() => ev(`document.querySelectorAll('.study-item mark').length > 0`), 'highlighted matches');
        assert.match(await hash(), /[?&]q=extinction/);
        assert.match(await text('.study-list'), /Relevance rank \d+/);
        assert.match(await text('#view .status'), /matches? for “extinction”/);
        assert.match(await text('#view .small.muted'), /not a measure of fire risk/i);
        const total = (await apiGet('/api/studies?q=extinction&limit=50')).meta.total;
        assert.equal(await count('.study-item'), total);
    });
    await check('1c studies: category radio "Suppression" filters', async () => {
        await setInput('#study-search', '');
        await until(() => count('.study-item').then(n => n === 24), 'cleared search');
        await ev(`[...document.querySelectorAll('input[name=safety-category]')].find(r => r.value === 'suppression').click()`);
        const expected = (await apiGet('/api/studies?safety_category=suppression&limit=50')).meta.total;
        await until(() => count('.study-item').then(n => n === expected), 'suppression filter');
        assert.ok(expected > 0 && expected < 24);
        assert.match(await hash(), /category=suppression/);
        assert.match(await text('#view .status'), /in suppression/);
        assert.equal(await ev(`document.querySelector('input[name=safety-category]:checked').value`), 'suppression');
        await ev(`document.querySelector('input[name=safety-category][value=""]').click()`);
        await until(() => count('.study-item').then(n => n === 24), 'category cleared');
    });
    await check('1d studies: nonsense query shows the empty state', async () => {
        await setInput('#study-search', 'zzqxqzzq');
        await until(() => ev(`Boolean(document.querySelector('.study-list .empty'))`), 'empty state');
        assert.match(await text('.study-list .empty'), /No investigations match “zzqxqzzq”/);
        assert.equal(await count('.study-item'), 0);
        assert.match(await text('#view .status'), /0 matches/);
        await shot('desktop-studies-empty', { full: false });
    });
    await check('1e studies: two Compare checkboxes show the compare bar and navigate to #/compare/A/B', async () => {
        await setInput('#study-search', '');
        await until(() => count('.study-item').then(n => n === 24), 'list restored');
        await click('input[data-accession="PSI-69"]');
        assert.match(await text('.compare-bar'), /Selected PSI-69/);
        await click('input[data-accession="PSI-99"]');
        assert.equal(await ev(`document.querySelectorAll('.study-item input:disabled').length`), 22, 'other boxes disabled at two');
        await clickByText('.compare-bar button', 'Compare PSI-69 and PSI-99');
        await until(async () => (await hash()) === '#/compare/PSI-69/PSI-99', 'compare route');
    });

    // ---------- 2. Study detail ----------
    await check('2a study PSI-69: title, review line, sections', async () => {
        await fresh(ROUTES.study);
        await until(loaded.study, 'study loaded');
        const card = (await apiGet('/api/studies/PSI-69')).data;
        assert.ok((await text('#view h1')).includes(card.title));
        const review = await text('.review-line');
        assert.ok(review.length > 5, 'review line present: ' + review);
        for (const id of ['summary', 'attributes', 'references']) assert.equal(await count('#' + id), 1, 'section #' + id);
        assert.equal(await text('#summary h2'), 'Summary');
        assert.equal(await text('#attributes h2'), 'Comparison attributes');
        assert.equal(await text('#references h2'), 'References');
        await shot('desktop-study');
    });
    await check('2b study: citation marker opens evidence dialog with excerpt and locator; Next/Previous; Esc closes', async () => {
        await click('#summary .cite button');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog')?.open === true && document.querySelector('dialog.evidence-dialog blockquote.excerpt')?.textContent.length > 20`), 'evidence dialog');
        assert.match(await text('dialog.evidence-dialog .meta-list'), /Location/);
        assert.ok((await text('dialog.evidence-dialog .meta-list dd')).length > 3, 'locator text');
        assert.match(await text('dialog.evidence-dialog .meta-list'), /Evidence ID/);
        await shot('desktop-evidence-dialog', { full: false });
        await key('Escape');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog').open === false`), 'Esc closes');
        // Multi-citation marker: previous/next.
        const multi = await ev(`(() => { const sups = [...document.querySelectorAll('#view .cite')]; const i = sups.findIndex(s => s.querySelectorAll('button').length >= 2); if (i < 0) return -1; sups[i].querySelector('button').click(); return i; })()`);
        assert.ok(multi >= 0, 'a marker with two or more citations exists');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog')?.open && /Citation 1 of \\d+/.test(document.querySelector('.evidence-nav').textContent) && document.querySelector('dialog.evidence-dialog blockquote.excerpt').textContent.length > 20`), 'first of many');
        const first = await text('dialog.evidence-dialog blockquote.excerpt');
        assert.equal(await ev(`[...document.querySelectorAll('.evidence-nav button')].find(b => b.textContent === 'Previous').disabled`), true);
        await clickByText('.evidence-nav button', 'Next');
        await until(() => ev(`/Citation 2 of/.test(document.querySelector('.evidence-nav').textContent)`), 'second citation');
        await until(async () => (await text('dialog.evidence-dialog blockquote.excerpt')) !== first && (await text('dialog.evidence-dialog blockquote.excerpt')).length > 20, 'different excerpt');
        await clickByText('.evidence-nav button', 'Previous');
        await until(async () => (await text('dialog.evidence-dialog blockquote.excerpt')) === first, 'back to first');
        await key('Escape');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog').open === false`), 'Esc closes again');
    });
    await check('2c study: Cite shows DOI and PSI investigators', async () => {
        const source = (await apiGet('/api/studies/PSI-69')).meta.source;
        await clickByText('.actions button', 'Cite');
        await until(() => ev(`document.querySelector('dialog.cite-dialog')?.open === true`), 'cite dialog');
        const body = await text('dialog.cite-dialog');
        assert.ok(body.includes('10.60555/mbq8-0451'), 'DOI in citation');
        const isInv = p => (p.roles || []).some(r => /investigator|\(PI\)|\(Co-I\)/i.test(r));
        const authors = source.investigators.filter(isInv);
        assert.ok(authors.length > 0);
        for (const person of authors) assert.ok(body.includes(person.name), 'author ' + person.name);
        assert.match(body, /BibTeX/);
        await shot('desktop-cite-dialog', { full: false });
        await key('Escape');
        await until(() => ev(`document.querySelector('dialog.cite-dialog').open === false`), 'cite closes');
    });
    await check('2d study: Export card (JSON) equals /api/studies/PSI-69 data', async () => {
        await captureDownloads();
        await clickByText('.actions button', 'Export card (JSON)');
        const download = await nextDownload();
        assert.match(download.filename, /^PSI-69_v\d+_research-card\.json$/);
        assert.deepEqual(JSON.parse(download.text), (await apiGet('/api/studies/PSI-69')).data);
    });

    // ---------- 3. Compare ----------
    await check('3 compare PSI-69/PSI-99: titles, "Not stated in this card", citation markers, D3 notice', async () => {
        await fresh(ROUTES.compare);
        await until(loaded.compare, 'compare table');
        const a = (await apiGet('/api/studies/PSI-69')).data, b = (await apiGet('/api/studies/PSI-99')).data;
        const heads = await ev(`[...document.querySelectorAll('.cmp-table thead th')].map(t => t.textContent)`);
        assert.ok(heads.some(t => t.includes(a.title)), 'title A in header');
        assert.ok(heads.some(t => t.includes(b.title)), 'title B in header');
        assert.ok(heads.some(t => t.includes('PSI-69')) && heads.some(t => t.includes('PSI-99')));
        assert.ok((await text('.cmp-table')).includes('Not stated in this card'));
        assert.ok(await count('.cmp-table .cite button') > 0, 'citation markers');
        assert.match(await text('.cmp-notice'), /requires known and equal fuel class, material, geometry, flow direction and hardware/);
        assert.match(await text('.cmp-notice'), /no differences are computed/);
        await click('.cmp-table .cite button');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog')?.open === true && document.querySelector('dialog.evidence-dialog blockquote.excerpt')?.textContent.length > 20`), 'evidence from compare');
        await key('Escape');
        await shot('desktop-compare');
    });

    // ---------- 4. Files ----------
    await check('4a files PSI-69 category=Experimental table: rows and total line', async () => {
        await fresh(ROUTES.files);
        await until(loaded.files, 'file rows');
        const total = (await apiGet('/api/studies/PSI-69/files?category=Experimental%20table&limit=1')).meta.total;
        assert.equal(await count('.files-table tbody tr'), total);
        assert.match(await text('.files-heading'), new RegExp('PSI-69 · ' + total + ' catalogued files? match'));
        assert.equal(await ev(`document.getElementById('files-category').value`), 'Experimental table');
        assert.match(await text('.files-note'), /does not mean the contents were downloaded or processed/);
        await shot('desktop-files');
    });
    await check('4b files: pagination on an unfiltered investigation', async () => {
        await go('#/files/PSI-69');
        const total = (await apiGet('/api/studies/PSI-69/files?limit=1')).meta.total;
        await until(() => count('.files-table tbody tr').then(n => n === 50), 'page 1 of 50 rows');
        const pages = Math.ceil(total / 50);
        assert.match(await text('.files-body .pagination .range'), new RegExp('1–50 of ' + total.toLocaleString('en-US') + ' \\(page 1 of ' + pages.toLocaleString('en-US') + '\\)'));
        const firstName = await text('.files-table tbody tr td');
        await clickByText('.files-body .pagination button', 'Next');
        await until(async () => (await hash()).includes('page=2'), 'page=2 in URL');
        await until(() => ev(`/51–100 of/.test(document.querySelector('.files-body .pagination .range')?.textContent || '')`), 'page two range');
        assert.notEqual(await text('.files-table tbody tr td'), firstName);
        await clickByText('.files-body .pagination button', 'Previous');
        await until(() => ev(`/1–50 of/.test(document.querySelector('.files-body .pagination .range')?.textContent || '')`), 'back to page one');
    });
    await check('4c files: extension "csv" (no dot) shows validation message and sends no request', async () => {
        await go('#/files/PSI-99');
        await until(() => count('.files-table tbody tr').then(n => n > 0), 'PSI-99 files');
        await until(() => ev(`document.getElementById('files-acc').value === 'PSI-99'`), 'investigation list populated');
        const before = requests.filter(u => u.includes('/files')).length;
        await ev(`(() => { const e = document.getElementById('files-extension'); e.value = 'csv'; document.querySelector('.files-filters').requestSubmit(); })()`);
        await until(() => ev(`document.getElementById('files-extension-hint').getAttribute('role') === 'alert'`), 'validation shown');
        assert.match(await text('#files-extension-hint'), /must start with a period/);
        assert.equal(await ev(`document.getElementById('files-extension').getAttribute('aria-invalid')`), 'true');
        await delay(600);
        assert.equal(requests.filter(u => u.includes('/files')).length, before, 'no /files request sent');
        assert.ok(!(await hash()).includes('extension=csv'), 'invalid extension not put in the URL');
        // A valid extension still works.
        await ev(`(() => { const e = document.getElementById('files-extension'); e.value = '.csv'; document.querySelector('.files-filters').requestSubmit(); })()`);
        await until(async () => (await hash()).includes('extension=.csv') || (await hash()).includes('extension=%2Ecsv'), 'valid extension applied');
        await until(() => ev(`document.querySelectorAll('.files-table tbody tr').length > 0 && [...document.querySelectorAll('.files-table tbody tr td:nth-child(3)')].every(c => c.textContent.trim() === '.csv')`), 'only .csv rows');
    });
    await check('4d files: shared URL with an invalid extension sends no request and explains why', async () => {
        const before = requests.filter(u => u.includes('/files')).length;
        await go('#/files/PSI-99?extension=csv');
        await until(() => ev(`/No request was sent/.test(document.querySelector('.files-heading')?.textContent || '')`), 'no-request message');
        assert.equal(requests.filter(u => u.includes('/files')).length, before);
    });

    // ---------- 5. Conditions ----------
    let solidTotal;
    await check('5a conditions fuel_class=solid: map marks, 3 reference atmospheres, counts agree', async () => {
        await fresh(ROUTES.conditions);
        await until(loaded.conditions, 'conditions loaded', 60000);
        assert.ok(await count('.cond-svg .cond-mark') > 0, 'plotted marks');
        assert.equal(await count('.cond-svg .cond-ref'), 3, 'reference atmospheres');
        const coverage = (await apiGet('/api/coverage?fuel_class=solid')).data;
        const runs = (await apiGet('/api/runs?fuel_class=solid&limit=1')).meta.total;
        solidTotal = runs;
        const tableTotal = Number((await text('.cond-count strong')).replace(/,/g, ''));
        assert.equal(tableTotal, runs, 'table total == runs meta.total');
        assert.equal(coverage.counts.source_records, runs, 'coverage source_records == runs total');
        assert.match(await text('.cond-summary'), new RegExp('Source rows[^]*' + runs.toLocaleString('en-US')));
        assert.equal(await count('.cond-count + .notice-warn'), 0, 'no count-mismatch notice');
        assert.ok(await ev(`document.querySelector('.cond-ref title')?.textContent.includes('not experimental data')`), 'reference marks labelled as non-data');
        await shot('desktop-conditions');
    });
    await check('5b conditions: sorting a column changes order and URL sort=', async () => {
        const firstIds = () => ev(`[...document.querySelectorAll('.runs-table tbody tr')].slice(0, 5).map(r => r.dataset.runId).join(',')`);
        const before = await firstIds();
        await click('.runs-table button[data-sort-key="o2"]');
        await until(async () => (await hash()).includes('sort=o2'), 'sort in URL');
        assert.equal(await ev(`document.querySelector('.runs-table th[aria-sort="ascending"]')?.textContent.trim()`), 'O2 (%)');
        const asc = await firstIds();
        assert.notEqual(asc, before, 'order changed');
        await click('.runs-table button[data-sort-key="o2"]');
        await until(async () => (await hash()).includes('sort=o2:desc') || (await hash()).includes('sort=o2%3Adesc'), 'descending sort in URL');
        assert.notEqual(await firstIds(), asc, 'descending differs from ascending');
        // The sorted view is shareable: reload keeps it.
        // Mark the old document so the wait cannot be satisfied before the reload replaces it.
        await ev('window.__beforeReload = true; location.reload()');
        await until(async () => (await ev('window.__beforeReload !== true')) && (await loaded.conditions()), 'reload conditions', 60000);
        assert.equal(await ev(`document.querySelector('.runs-table th[aria-sort="descending"]')?.textContent.trim()`), 'O2 (%)');
    });
    await check('5c conditions: clicking a row opens the run dialog with "Original row"', async () => {
        const id = await ev(`document.querySelector('.runs-table tbody tr').dataset.runId`);
        await click('.runs-table tbody tr');
        await until(() => ev(`document.querySelector('dialog.runs-dialog')?.open === true && /Original row/.test(document.querySelector('dialog.runs-dialog').textContent)`), 'run dialog');
        const body = await text('dialog.runs-dialog');
        assert.ok(body.includes(id), 'dialog shows the record id');
        assert.match(body, /Conditions/);
        assert.ok(await count('dialog.runs-dialog [class*="original"] dd, dialog.runs-dialog dl dd') > 0, 'original row cells');
        await shot('desktop-run-dialog', { full: false });
        await key('Escape');
        await until(() => ev(`document.querySelector('dialog.runs-dialog').open === false`), 'run dialog closes');
    });
    await check('5d conditions solid + o2_min=30: coverage status text matches the API', async () => {
        const coverage = (await apiGet('/api/coverage?fuel_class=solid&o2_min=30')).data;
        const labels = { covered: 'Covered', pending_review: 'Pending review', unknown_conditions: 'Unknown conditions', not_in_PSI: 'Not in PSI' };
        await fresh('#/conditions?fuel_class=solid&o2_min=30');
        await until(() => ev(`/Coverage status:/.test(document.querySelector('.cond-status-line')?.textContent || '')`), 'status line', 60000);
        assert.match(await text('.cond-status-line'), new RegExp('Coverage status: ' + labels[coverage.coverage_status]));
        const empty = coverage.counts.source_records === 0;
        const summary = await text('.cond-summary');
        if (coverage.coverage_status === 'not_in_PSI') {
            assert.match(summary, /Not in PSI: no record in the saved PSI snapshot/);
            assert.match(summary, /does not establish whether the scenario was studied elsewhere/);
        } else {
            assert.ok(!/Not in PSI: no record/.test(summary), 'a gap must not be claimed unless the API says not_in_PSI');
            if (empty) assert.match(summary, /a gap cannot be claimed/);
        }
        if (coverage.counts.source_records === 0) await until(() => ev(`/No source rows match these filters/.test(document.querySelector('.cond-table-section')?.textContent || '')`), 'empty table message');
        await shot('desktop-conditions-pending', { full: false });
    });
    await check('5e conditions: Download CSV row count == total + 1 header', async () => {
        await fresh(ROUTES.conditions);
        await until(loaded.conditions, 'conditions loaded', 60000);
        await captureDownloads();
        await clickByText('.cond-export button', 'Download CSV');
        const download = await nextDownload();
        assert.match(download.filename, /\.csv$/);
        const rows = parseCsv(download.text);
        assert.equal(rows.length, solidTotal + 1, 'CSV rows (header + records)');
        assert.ok(new Set(rows.map(r => r.length)).size === 1, 'rectangular CSV');
    });

    // ---------- 6. Backend error and recovery ----------
    await check('6 backend 503 on /api/studies: visible error, no mock data; recovery after reload', async () => {
        await fresh('#/about');
        intercept = true;
        await command('Fetch.enable', { patterns: [{ urlPattern: base + '/api/studies*' }] });
        await command('Page.navigate', { url: base + '/#/studies' });
        await command('Page.reload');
        await until(() => ev(`Boolean(document.querySelector('#view .status-error'))`), 'error status');
        assert.equal(await visibleError('#view .status-error'), true);
        assert.ok((await text('#view .status-error')).length > 5);
        assert.equal(await count('.study-item'), 0, 'no mock investigations');
        await shot('desktop-error-503', { full: false });
        intercept = false;
        await command('Fetch.disable');
        await command('Page.reload');
        await until(loaded.studies, 'recovered list');
        assert.equal(await count('#view .status-error'), 0);
    });

    // ---------- 7. Mobile ----------
    await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    for (const [name, hashRoute] of Object.entries(ROUTES)) {
        await check('7 mobile 390px: ' + name + ' has no horizontal page scroll', async () => {
            await fresh(hashRoute);
            await until(loaded[name], name + ' loaded', 60000);
            await delay(300);
            const widths = await ev(`({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, body: document.body.scrollWidth })`);
            await shot('mobile-' + name);
            assert.ok(widths.scroll <= 390, 'scrollWidth ' + widths.scroll + ' > 390 (body ' + widths.body + ')');
        });
    }
    await check('7 mobile 390px: evidence dialog fits the viewport', async () => {
        await fresh(ROUTES.study);
        await until(loaded.study, 'study loaded');
        await click('#summary .cite button');
        await until(() => ev(`document.querySelector('dialog.evidence-dialog')?.open === true && document.querySelector('dialog.evidence-dialog blockquote.excerpt')?.textContent.length > 20`), 'dialog');
        const rect = await ev(`(() => { const r = document.querySelector('dialog.evidence-dialog').getBoundingClientRect(); return { left: r.left, right: r.right }; })()`);
        assert.ok(rect.left >= -1 && rect.right <= 391, 'dialog within viewport: ' + JSON.stringify(rect));
        await shot('mobile-evidence-dialog', { full: false });
        await key('Escape');
    });

    // ---------- Dark mode ----------
    await check('7 dark mode: desktop and mobile screenshots, no overflow', async () => {
        await command('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
        await fresh(ROUTES.study);
        await until(loaded.study, 'study dark mobile');
        assert.ok(await ev(`document.documentElement.scrollWidth <= 390`));
        assert.equal(await ev(`matchMedia('(prefers-color-scheme: dark)').matches`), true);
        await shot('mobile-study-dark');
        await command('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
        await fresh(ROUTES.conditions);
        await until(loaded.conditions, 'conditions dark desktop', 60000);
        await shot('desktop-conditions-dark');
        const bg = await ev(`getComputedStyle(document.body).backgroundColor`);
        const [r, g, b] = bg.match(/\d+/g).map(Number);
        assert.ok(r + g + b < 300, 'dark background, got ' + bg);
        await command('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });
    });

    // ---------- 8. Offline / console ----------
    await check('8 only local requests were made; no JavaScript exceptions or console errors', async () => {
        assert.deepEqual(externalRequests, [], 'non-local requests');
        assert.deepEqual(runtimeErrors, [], 'JS exceptions / console errors');
        assert.ok(requests.length > 50, 'requests were observed');
    });

    const failed = results.filter(r => !r.ok);
    console.log('\n' + (results.length - failed.length) + '/' + results.length + ' checks passed');
    console.log('Screenshots:\n  ' + savedShots.join('\n  '));
    if (failed.length) {
        console.log('\nFailed:\n' + failed.map(f => '  - ' + f.name + '\n      ' + f.error).join('\n'));
        process.exitCode = 1;
    }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
    if (socket?.readyState === WebSocket.OPEN && command) {
        await command('Browser.close').catch(() => {});
        socket.close();
    }
    browser.kill();
    // The unique temporary browser profile is separate from the user's browser.
});
