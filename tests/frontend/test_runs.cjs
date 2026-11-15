// Run with: node --test tests/frontend/
const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./harness.cjs');

const prov = (extra = {}) => Object.assign({ columns: [], method: 'parsed', note: null, quote: null, review_status: 'not_required' }, extra);
const quantity = (min, max = min, unit = 'percent', extra = {}) => prov(Object.assign(
    { min, max, unit, qualifier: null, method: min === null ? 'unknown' : 'parsed' }, extra));
const category = (value, extra = {}) => prov(Object.assign({ value, method: value === null ? 'unknown' : 'parsed' }, extra));

function record(id, o2, extra = {}) {
    return Object.assign({
        id, kind: 'run', row: Number(id.split(':')[2]), review_status: 'not_required', original: { A: 'x' }, flags: [], links: [], outcomes: [],
        conditions: {
            fuel_class: category('solid'), material: category('pmma'), geometry: category('slab'), flow_direction: category('concurrent'),
            diluent: category(null), o2_percent: o2, pressure_kpa: quantity(101.3, 101.3, 'kPa'), flow_cm_s: quantity(null, null, 'cm/s'),
        },
    }, extra);
}
const ids = records => records.map(r => r.id);
const { FF, document } = load(['runs.js']);

test('sorting: numeric not lexical, ascending and descending', () => {
    const rs = [record('PSI-1:t:1', quantity(9)), record('PSI-1:t:2', quantity(10)), record('PSI-1:t:3', quantity(2))];
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:asc')), ['PSI-1:t:3', 'PSI-1:t:1', 'PSI-1:t:2']);
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:desc')), ['PSI-1:t:2', 'PSI-1:t:1', 'PSI-1:t:3']);
});

test('sorting: unknown values last in both directions; zero is a value', () => {
    const rs = [record('PSI-1:t:1', quantity(null)), record('PSI-1:t:2', quantity(21)), record('PSI-1:t:3', quantity(0)), record('PSI-1:t:4', quantity(null))];
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:asc')), ['PSI-1:t:3', 'PSI-1:t:2', 'PSI-1:t:1', 'PSI-1:t:4']);
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:desc')), ['PSI-1:t:2', 'PSI-1:t:3', 'PSI-1:t:1', 'PSI-1:t:4']);
});

test('sorting: intervals by min then max; ties by accession number, table, row', () => {
    const rs = [record('PSI-10:a:1', quantity(18, 25)), record('PSI-9:a:2', quantity(18, 22)), record('PSI-9:a:1', quantity(18, 22)),
        record('PSI-9:b:1', quantity(18, 22)), record('PSI-2:z:5', quantity(17, 30))];
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:asc')), ['PSI-2:z:5', 'PSI-9:a:1', 'PSI-9:a:2', 'PSI-9:b:1', 'PSI-10:a:1']);
    // ties stay in identifier order even when the direction is descending
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'o2:desc')), ['PSI-10:a:1', 'PSI-9:a:1', 'PSI-9:a:2', 'PSI-9:b:1', 'PSI-2:z:5']);
});

test('sorting: default and id column follow numeric accession order; input is not mutated', () => {
    const rs = [record('PSI-10:a:1', quantity(1)), record('PSI-9:a:10', quantity(1)), record('PSI-9:a:2', quantity(1))];
    const copy = ids(rs);
    assert.deepEqual(ids(FF.runs.sortRecords(rs, '')), ['PSI-9:a:2', 'PSI-9:a:10', 'PSI-10:a:1']);
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'id:desc')), ['PSI-10:a:1', 'PSI-9:a:10', 'PSI-9:a:2']);
    assert.deepEqual(ids(rs), copy);
});

test('sorting: unknown categorical values last (geometry)', () => {
    const rs = [record('PSI-1:t:1', quantity(1)), record('PSI-1:t:2', quantity(1)), record('PSI-1:t:3', quantity(1))];
    rs[0].conditions.geometry = category(null);
    rs[1].conditions.geometry = category('wire');
    rs[2].conditions.geometry = category('slab');
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'geometry:asc')), ['PSI-1:t:3', 'PSI-1:t:2', 'PSI-1:t:1']);
    assert.deepEqual(ids(FF.runs.sortRecords(rs, 'geometry:desc')), ['PSI-1:t:2', 'PSI-1:t:3', 'PSI-1:t:1']);
});

test('pagination math', () => {
    assert.deepEqual({ ...FF.runs.pageInfo(2009, 1, 50) }, { pages: 41, page: 1, start: 0, end: 50 });
    assert.deepEqual({ ...FF.runs.pageInfo(2009, 41, 50) }, { pages: 41, page: 41, start: 2000, end: 2009 });
    assert.deepEqual({ ...FF.runs.pageInfo(2009, 99, 50) }, { pages: 41, page: 41, start: 2000, end: 2009 });
    assert.deepEqual({ ...FF.runs.pageInfo(0, 1, 50) }, { pages: 1, page: 1, start: 0, end: 0 });
});

function render(records, options = {}) {
    const container = document_div();
    FF.runs.renderTable(container, records, options);
    return container;
}
function document_div() { return document.createElement('div'); }
const textOf = node => node.textContent;
const bodyRows = container => container.qsa('tr').filter(tr => tr.classList.contains('run-row'));

test('table paginates, buttons move pages, empty state message', () => {
    const many = Array.from({ length: 120 }, (_, i) => record('PSI-1:t:' + (i + 1), quantity(i)));
    const container = render(many, { pageSize: 50 });
    assert.equal(bodyRows(container).length, 50);
    assert.match(textOf(container), /Rows 1–50 of 120/);
    container.qsa('button').find(b => textOf(b) === 'Next').click();
    assert.match(textOf(container), /Rows 51–100 of 120/);
    container.qsa('button').find(b => textOf(b) === 'Next').click();
    assert.equal(bodyRows(container).length, 20);
    assert.ok(container.qsa('button').filter(b => textOf(b) === 'Next').every(b => b.hasAttribute('disabled')));
    assert.match(textOf(render([])), /No source rows match these filters\./);
});

test('sort headers carry aria-sort, call onSort, and re-sort locally with unknown last', () => {
    const rs = [record('PSI-1:t:1', quantity(null)), record('PSI-1:t:2', quantity(30)), record('PSI-1:t:3', quantity(5))];
    const calls = [];
    const container = render(rs, { sort: 'o2:asc', onSort: s => calls.push(s) });
    const th = () => container.qsa('th').find(t => t.getAttribute('aria-sort') && textOf(t) === 'O2 (%)');
    assert.equal(th().getAttribute('aria-sort'), 'ascending');
    assert.equal(container.qsa('th').filter(t => t.getAttribute('aria-sort') === 'none').length, 11);
    th().querySelector('button').click();
    assert.deepEqual(calls, ['o2:desc']);
    assert.equal(th().getAttribute('aria-sort'), 'descending');
    assert.deepEqual(bodyRows(container).map(r => r.dataset.runId), ['PSI-1:t:2', 'PSI-1:t:3', 'PSI-1:t:1']);
    const other = container.qsa('th').find(t => textOf(t) === 'Pressure (kPa)').querySelector('button');
    other.click();
    assert.equal(calls[1], 'pressure:asc');
});

test('rows select by click, Enter and Space; Details button selects once', () => {
    const selected = [];
    const container = render([record('PSI-1:t:1', quantity(21))], { onSelect: id => selected.push(id) });
    const row = bodyRows(container)[0];
    row.click();
    row.dispatch('keydown', { key: 'Enter' });
    row.dispatch('keydown', { key: ' ' });
    row.dispatch('keydown', { key: 'a' });
    assert.deepEqual(selected, ['PSI-1:t:1', 'PSI-1:t:1', 'PSI-1:t:1']);
    selected.length = 0;
    // Real browsers bubble the button click to the row; the handler stops it, so check via the button only.
    row.qsa('button').find(b => textOf(b) === 'Details').click();
    assert.deepEqual(selected, ['PSI-1:t:1']);
});

test('cells: unknown, interval, approximate and valid zero; flags and kind', () => {
    const r = record('PSI-1:t:1', quantity(0));
    r.conditions.pressure_kpa = quantity(30, 60, 'kPa', { qualifier: 'approximate' });
    r.flags = [{ code: 'suspected_typo', columns: ['A'], detail: 'looks mistyped' }];
    const container = render([r, record('PSI-1:t:2', quantity(null))]);
    const rows = bodyRows(container);
    const cells = row => row.qsa('td');
    // td order: study, kind, fuel, geometry, direction, o2, pressure, flow, outcomes, review, flags, details
    assert.equal(textOf(cells(rows[0])[5]), '0');
    assert.equal(textOf(cells(rows[0])[6]), '≈ 30–60');
    assert.equal(textOf(cells(rows[1])[5]), 'Unknown');
    assert.ok(cells(rows[1])[5].find(n => n.classList.contains('unknown')));
    assert.equal(textOf(cells(rows[0])[7]), 'Unknown');
    assert.match(textOf(cells(rows[0])[10]), /^1 flag/);
    assert.match(cells(rows[0])[10].find(n => n.getAttribute('title')).getAttribute('title'), /Suspected typo: looks mistyped/);
    assert.equal(textOf(cells(rows[0])[1]), 'Run');
});

test('outcomes keep per-outcome gravity; normal is 1 g ground test; missing gravity is not invented', () => {
    const r = record('PSI-99:saffire-2:1', quantity(21));
    r.outcomes = [
        { type: 'burn_length', gravity: 'normal', result: quantity(12, 12, 'cm') },
        { type: 'burn_length', gravity: 'microgravity', result: quantity(0, 0, 'cm') },
        { type: 'burn_time', gravity: 'microgravity', result: category('Insignificant') },
        { type: 'spread_rate', result: quantity(null, null, 'mm/s') },
    ];
    const text = textOf(render([r]).qsa('td').find(td => td.classList.contains('run-outcomes-cell')));
    assert.match(text, /Burn length: 12 cm \(1 g ground test\)/);
    assert.match(text, /Burn length: 0 cm \(Microgravity\)/);
    assert.match(text, /Burn time: Insignificant \(Microgravity\)/);
    assert.match(text, /Spread rate: Unknown \(Gravity not recorded\)/);
    assert.equal(FF.runs.gravityLabel('normal'), '1 g ground test');
    assert.match(textOf(render([record('PSI-1:t:1', quantity(1))])), /None recorded/);
});

test('AI marker only for method=llm; uncalibrated display flow gets a dagger and legend', () => {
    const plain = record('PSI-1:t:1', quantity(21));
    const ai = record('PSI-25:bass-ii:2', quantity(17.4));
    ai.conditions.flow_cm_s = quantity(2, 5, 'cm/s', { method: 'llm', columns: ['Air display'], quote: '5 2.5 2', review_status: 'approved' });
    ai.outcomes = [{ type: 'extinction', gravity: 'microgravity', result: category('extinction at end of flow sweep', { method: 'llm', quote: 'slow decr to ext' }) }];
    const marks = c => c.qsa('abbr').filter(a => a.getAttribute('title') === 'AI-extracted; see record for source text');
    assert.equal(marks(render([plain])).length, 0);
    const container = render([ai]);
    assert.equal(marks(container).length, 2); // flow quantity and outcome
    assert.match(textOf(container), /†/);
    assert.match(textOf(container), /raw instrument display reading/);
    assert.equal(marks(render([plain, { ...plain, id: 'PSI-1:t:2' }])).length, 0);

    const raw = record('PSI-26:bass:1', quantity(21));
    raw.conditions.flow_cm_s = quantity(5, 5, 'cm/s', { columns: ['as run matrix!Air display'], note: 'raw display retained' });
    const calibrated = record('PSI-25:bass-ii:3', quantity(21));
    calibrated.conditions.flow_cm_s = quantity(5, 5, 'cm/s', { columns: ['Air display'], note: "velocity = 1.0066 x air display, from the footnote" });
    const measured = record('PSI-99:saffire-2:1', quantity(21));
    measured.conditions.flow_cm_s = quantity(20, 20, 'cm/s', { columns: ['Air Flow (cm/s)'] });
    assert.equal(FF.runs.isUncalibratedFlow(raw.conditions.flow_cm_s), true);
    assert.equal(FF.runs.isUncalibratedFlow(calibrated.conditions.flow_cm_s), false);
    assert.equal(FF.runs.isUncalibratedFlow(measured.conditions.flow_cm_s), false);
    assert.equal(FF.runs.isUncalibratedFlow(quantity(null, null, 'cm/s')), false);
    assert.doesNotMatch(textOf(render([calibrated, measured])), /†/);
});

test('fuel / material cell shows the source quote when it differs from the mapped value', () => {
    const r = record('PSI-69:flex:1', quantity(21));
    r.conditions.material = category('methanol', { method: 'mapped', quote: 'Methanol (99%)' });
    const cell = render([r]).qsa('td')[2];
    assert.ok(cell.find(n => n.getAttribute('title') === 'Source text: Methanol (99%)'));
    assert.match(textOf(cell), /Solid/);
});

// ---------- detail ----------
const detailRecord = () => {
    const r = record('PSI-99:saffire-2:1', quantity(21, 21, 'percent', { method: 'llm', quote: '  21 %  (approx.)', columns: ['Percent O2'], review_status: 'pending' }));
    r.original = { 'Percent O2 (Note 1)': '  21 %  (approx.)', 'Camera 2': '', Material: 'Line1\nLine2' };
    r.links = [
        { basis: 'sample 205 and test O3a in file name', status: 'confirmed', target: { kind: 'file', accession: 'PSI-99', filename: 'a b#.zip', key: 'k/a b#.zip', version: 2, file_id: 'x' } },
        { basis: 'only sample 205 in the file name', status: 'ambiguous', target: { kind: 'file', accession: 'PSI-99', filename: 'maybe.zip', key: 'k/maybe.zip', version: 1, file_id: 'y' } },
    ];
    r.flags = [{ code: 'references_other_rows', columns: ['Percent O2 (Note 1)'], detail: 'cites Note 1' }];
    r.outcomes = [{ type: 'burn_length', gravity: 'normal', result: quantity(0, 0, 'cm', { note: 'unit taken from column' }) }];
    return r;
};
const sourceMeta = { provisional: true, source: { investigation: 'PSI-99', table: 'saffire-2', source: {
    filename: 'PSI-99_Experimental table_SAFFIRE-2.csv', sha256: 'ab'.repeat(32), encoding: 'utf-8', columns: ['Percent O2 (Note 1)', 'Material', 'Camera 2'] } } };

test('openDetail encodes the run id, shows quotes and original cells verbatim, groups links', async () => {
    const r = detailRecord();
    const env = load(['runs.js'], url => ({ data: r, meta: sourceMeta }));
    await env.FF.runs.openDetail('PSI-99:saffire-2:1');
    assert.deepEqual(env.requests, ['/api/runs/PSI-99%3Asaffire-2%3A1']);
    const dialog = env.document.body.children.find(c => c.tagName === 'DIALOG');
    assert.ok(dialog.open);
    const text = dialog.textContent;
    assert.match(text, /PSI-99_Experimental table_SAFFIRE-2\.csv/);
    assert.match(text, /utf-8/);
    assert.match(text, /Provisional/);
    assert.match(text, /not necessarily one experiment/);
    assert.ok(dialog.find(n => n.getAttribute && n.getAttribute('title') === 'ab'.repeat(32)));
    // verbatim quote and original cells (leading whitespace preserved)
    assert.ok(dialog.all(n => n.classList.contains('run-quote')).some(n => n.textContent === '  21 %  (approx.)'));
    const cells = dialog.all(n => n.classList.contains('run-cell')).map(n => n.textContent);
    assert.ok(cells.includes('  21 %  (approx.)'));
    assert.ok(cells.includes('Line1\nLine2'));
    assert.match(text, /\(empty\)/);
    // method label, AI-extracted distinct, review pending
    assert.ok(dialog.find(n => n.classList.contains('ai-tag') && n.textContent === 'AI-extracted'));
    assert.match(text, /Pending review/);
    // per-outcome gravity, zero kept
    assert.match(text, /1 g ground test/);
    assert.match(text, /0 cm/);
    // flags and links
    assert.match(text, /References other rows|Refers to other rows/);
    assert.match(text, /Confirmed \(1\)/);
    assert.match(text, /Ambiguous candidates \(not confirmed\) \(1\)/);
    const hrefs = dialog.all(n => n.tagName === 'A').map(n => n.getAttribute('href'));
    assert.ok(hrefs.includes('#/files/PSI-99?filename=a+b%23.zip'));
    assert.ok(hrefs.includes('#/study/PSI-99'));
    // actions
    const labels = dialog.all(n => n.tagName === 'BUTTON').map(n => n.textContent);
    for (const expected of ['Copy record ID', 'Download record JSON', 'Close']) assert.ok(labels.includes(expected), expected);
});

test('openDetail: 404 and 503 produce explicit errors; no fabricated record', async () => {
    for (const [status, pattern] of [[404, /was not found/], [503, /unavailable/]]) {
        const env = load(['runs.js'], () => ({ status, body: { error: { code: 'x', details: { state: 'graph_unavailable' } } } }));
        await env.FF.runs.openDetail('PSI-1:t:1');
        const dialog = env.document.body.children.find(c => c.tagName === 'DIALOG');
        assert.match(dialog.textContent, pattern);
        assert.doesNotMatch(dialog.textContent, /Conditions/);
    }
});

test('Download record JSON passes exact data and meta', async () => {
    const r = detailRecord();
    const downloads = [];
    const env = load(['runs.js'], () => ({ data: r, meta: sourceMeta }));
    env.FF.download = (name, text) => downloads.push({ name, text });
    await env.FF.runs.openDetail(r.id);
    const dialog = env.document.body.children.find(c => c.tagName === 'DIALOG');
    dialog.all(n => n.tagName === 'BUTTON').find(n => n.textContent === 'Download record JSON').click();
    assert.equal(downloads[0].name, 'PSI-99_saffire-2_1.json');
    assert.deepEqual(JSON.parse(downloads[0].text), JSON.parse(JSON.stringify({ data: r, meta: sourceMeta })));
});

// ---------- CSV ----------
test('CSV: columns, valid zero, empty unknown, intervals, outcomes, AI flag, sources', () => {
    const header = ['id', 'investigation', 'table', 'source_file', 'row', 'kind', 'review_status', 'fuel_class', 'material', 'material_source_text',
        'geometry', 'flow_direction', 'diluent', 'o2_percent_min', 'o2_percent_max', 'o2_method', 'pressure_kpa_min', 'pressure_kpa_max',
        'pressure_method', 'flow_cm_s_min', 'flow_cm_s_max', 'flow_method', 'flow_note', 'outcomes', 'any_ai_extracted', 'flags'];
    const a = record('PSI-99:saffire-2:1', quantity(0));
    a.conditions.flow_cm_s = quantity(2, 5, 'cm/s', { method: 'llm', note: 'raw, "display"' });
    a.conditions.material = category('pmma', { quote: 'PMMA cast' });
    a.outcomes = [{ type: 'burn_length', gravity: 'normal', result: quantity(0, 0, 'cm') }, { type: 'ignition', gravity: 'microgravity', result: category(null) }];
    a.flags = [{ code: 'duplicate_row', columns: [], detail: 'd' }, { code: 'suspected_typo', columns: [], detail: 'd' }];
    const b = record('PSI-1:t:2', quantity(null));
    const text = FF.runs.csv([a, b], [{ investigation: 'PSI-99', table: 'saffire-2', source: { filename: 'f.csv' } }]);
    const lines = text.trim().split('\r\n');
    assert.equal(lines[0], header.join(','));
    assert.equal(lines.length, 3);
    assert.ok(lines[1].startsWith('PSI-99:saffire-2:1,PSI-99,saffire-2,f.csv,1,run,not_required,solid,pmma,PMMA cast,slab,concurrent,,0,0,parsed,101.3,101.3,parsed,2,5,llm,"raw, ""display""",'));
    assert.ok(lines[1].endsWith('burn_length [normal]: 0 cm; ignition [microgravity]: unknown,true,duplicate_row;suspected_typo'));
    // unknown: empty cells, method says unknown
    assert.ok(lines[2].includes(',,,unknown,101.3,101.3,parsed,,,unknown,'));
    assert.ok(lines[2].endsWith(',false,'));
});

test('CSV: text beginning with a formula character is neutralised', () => {
    const r = record('PSI-1:t:1', quantity(21));
    r.conditions.material = category('=HYPERLINK("x")', { quote: '+cmd' });
    const text = FF.runs.csv([r], []);
    assert.ok(text.includes(`"'=HYPERLINK(""x"")"`));
    assert.ok(text.includes(",'+cmd,"));
});
