const test = require('node:test');
const assert = require('node:assert/strict');
const { load, Element } = require('./harness.cjs');

const row = (n, extra = {}) => Object.assign({ access: 'public', accession: 'PSI-99', bytes: 10, category: 'Data', download_sha256: null,
    extension: '.csv', file_id: 'f' + n, filename: 'file' + n + '.csv', key: 'psi-data/PSI-99/Data/file' + n + '.csv', version: 1 }, extra);
const makeRespond = (rows, total = rows.length) => url => {
    if (url.includes('/files')) {
        return { data: rows, meta: { total, offset: Number(new URL(url, 'http://x').searchParams.get('offset')) || 0, limit: 50 } };
    }
    return { data: [{ accession: 'PSI-99', acronym: 'S2', title: 'Saffire' }], meta: { total: 1, offset: 0, limit: 100 } };
};
const tick = () => new Promise(r => setTimeout(r, 5));
const setup = (respond, extra) => { const env = load(['files.js'], respond, extra); return Object.assign(env, { container: new Element('main') }); };
const filesRequests = requests => requests.filter(u => u.includes('/files'));

test('query is built from URL params against the selected investigation', async () => {
    const { FF, requests, container } = setup(makeRespond([row(1)], 120));
    FF.views.files.mount(container, { args: ['PSI-99'], params: { filename: 'sample & flame', category: 'Experimental table', extension: '.CSV', page: '3' } });
    await tick();
    const url = new URL(filesRequests(requests)[0], 'http://x');
    assert.equal(url.pathname, '/api/studies/PSI-99/files');
    assert.equal(url.searchParams.get('filename'), 'sample & flame');
    assert.equal(url.searchParams.get('category'), 'Experimental table');
    assert.equal(url.searchParams.get('extension'), '.CSV');
    assert.equal(url.searchParams.get('limit'), '50');
    assert.equal(url.searchParams.get('offset'), '100');
    assert.match(container.textContent, /PSI-99 · 120 catalogued files match/);
    assert.match(container.textContent, /Catalogued means listed in the PSI file inventory/);
});

test('an invalid extension is explained and no request is sent', async () => {
    const { FF, requests, container } = setup(makeRespond([row(1)]));
    FF.views.files.mount(container, { args: ['PSI-99'], params: { extension: 'csv' } });
    await tick();
    assert.equal(filesRequests(requests).length, 0);
    assert.match(container.textContent, /must start with a period/);
});

test('zero bytes, hidden access, hash wording and download state', async () => {
    const hash = 'abcdef0123456789abcdef';
    const { FF, container } = setup(makeRespond([
        row(1, { bytes: 0, access: 'hidden', download_sha256: hash, filename: '<img onerror=attack>' }),
        row(2, { bytes: null, access: 'public' })]));
    FF.views.files.mount(container, { args: ['PSI-99'], params: {} });
    await tick();
    const rows = container.qsa('tbody')[0].children;
    assert.match(rows[0].textContent, /0 B/);
    assert.match(rows[0].textContent, /Hidden/);
    assert.match(rows[0].textContent, /Bytes verified/);
    assert.match(rows[0].textContent, /abcdef012345\b/);
    assert.ok(!rows[0].textContent.includes(hash));
    assert.ok(rows[0].children[0].children.every(c => c.tagName === 'SPAN')); // text only, no injected elements
    assert.match(rows[1].textContent, /Unknown/);
    assert.match(rows[1].textContent, /Not downloaded/);
    assert.equal(rows[0].children[0].attributes.title, 'psi-data/PSI-99/Data/file1.csv');
});

test('unknown accession shows a 404 message; empty result is explicit', async () => {
    let env = setup(url => url.includes('/files') ? { status: 404, body: { error: { code: 'not_found' } } } : { data: [], meta: { total: 0 } });
    env.FF.views.files.mount(env.container, { args: ['PSI-00'], params: {} });
    await tick();
    assert.match(env.container.textContent, /No investigation PSI-00/);
    env = setup(makeRespond([], 0));
    env.FF.views.files.mount(env.container, { args: ['PSI-99'], params: { filename: 'zzz' } });
    await tick();
    assert.match(env.container.textContent, /No catalogued files match/);
});

test('submitting the form updates the URL; invalid extension blocks it', async () => {
    const { FF, context, container } = setup(makeRespond([row(1)]));
    FF.views.files.mount(container, { args: ['PSI-99'], params: {} });
    await tick();
    const get = id => container.find(n => n.attributes.id === id);
    const form = container.find(n => n.tagName === 'FORM');
    get('files-acc').value = 'PSI-99';
    get('files-filename').value = 'flame';
    get('files-category').value = 'Experimental table';
    get('files-extension').value = 'csv';
    form.dispatch('submit');
    assert.equal(context.location.hash, '');
    get('files-extension').value = '.csv';
    form.dispatch('submit');
    assert.equal(context.location.hash, '#/files/PSI-99?filename=flame&category=Experimental+table&extension=.csv');
});

test('category suggestions come from results seen so far', async () => {
    const { FF, container } = setup(makeRespond([row(1, { category: 'Experimental table' }), row(2, { category: 'Calibration' })]));
    FF.views.files.mount(container, { args: ['PSI-99'], params: {} });
    await tick();
    const options = container.find(n => n.tagName === 'DATALIST').children.map(o => o.attributes.value);
    assert.deepEqual(options, ['Calibration', 'Experimental table']);
});

test('CSV export columns, formula safety and zero bytes', () => {
    const { FF } = setup(makeRespond([]));
    const text = FF.files.csv([row(1, { bytes: 0, filename: '=SUM(A1)', download_sha256: 'abc' })]);
    const [header, line] = text.split('\r\n');
    assert.equal(header, 'accession,file_id,version,key,filename,category,extension,bytes,access,download_sha256');
    assert.equal(line, "PSI-99,f1,1,psi-data/PSI-99/Data/file1.csv,'=SUM(A1),Data,.csv,0,public,abc");
});

test('export fetches every page for the selected filters and downloads the CSV', async () => {
    const downloads = [];
    const rows = Array.from({ length: 100 }, (_, i) => row(i));
    const respond = url => {
        if (!url.includes('/files')) return { data: [], meta: { total: 0 } };
        const offset = Number(new URL(url, 'http://x').searchParams.get('offset'));
        return { data: rows.slice(offset, offset + 100), meta: { total: 100, offset, limit: 100 } };
    };
    const { FF, requests, container } = setup(respond);
    FF.views.files.mount(container, { args: ['PSI-99'], params: { extension: '.csv' } });
    await tick();
    FF.download = (name, text) => downloads.push([name, text]);
    container.find(n => n.tagName === 'BUTTON' && /Export file list/.test(n.textContent)).click();
    await tick();
    const exportUrl = new URL(filesRequests(requests).pop(), 'http://x');
    assert.equal(exportUrl.searchParams.get('extension'), '.csv');
    assert.equal(downloads[0][0], 'files_PSI-99.csv');
    assert.equal(downloads[0][1].split('\r\n').length, 102);
});
