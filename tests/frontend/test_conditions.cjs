const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./harness.cjs');

const q = (min, max, unit, extra = {}) => Object.assign({ min, max, unit, method: 'parsed' }, extra);
function record(id, o2, pressure, over = {}) {
    return Object.assign({
        id, kind: 'run', review_status: 'approved', flags: [], outcomes: [],
        conditions: {
            o2_percent: o2 === null ? { method: 'unknown', min: null, max: null, unit: 'percent' } : q(o2[0], o2[1], 'percent'),
            pressure_kpa: pressure === null ? { method: 'unknown', min: null, max: null, unit: 'kPa' } : q(pressure[0], pressure[1], 'kPa'),
        },
    }, over);
}
const counts = (n, extra = {}) => Object.assign({ source_records: n, distinct_run_records: n, run_records: n, range_records: 0,
    session_records: 0, note_records: 0, duplicate_rows: 0, excluded_quality_records: 0, pending_review_records: 0,
    unknown_condition_records: 0, verified_run_count: n }, extra);
const coverage = (status, n, extra = {}) => ({ data: { state: 'available', coverage_status: status, counts: counts(n, extra),
    groups: [], comparisons: [], region: {} }, meta: { provisional: false, scope: 'saved_PSI_snapshot', sources: [] } });

function api(status, records, groups = []) {
    return url => {
        const u = new URL(url, 'http://x');
        if (u.pathname === '/api/coverage') {
            const body = coverage(status, records.length);
            body.data.groups = u.search ? [] : groups;
            return body;
        }
        const offset = Number(u.searchParams.get('offset') || 0), limit = Number(u.searchParams.get('limit') || 20);
        return { data: records.slice(offset, offset + limit), meta: { total: records.length, offset, limit, count_basis: 'source_records', provisional: false, sources: [] } };
    };
}
const plain = value => JSON.parse(JSON.stringify(value));
const wait = () => new Promise(resolve => setTimeout(resolve, 30));
const text = node => node.textContent;

test('URL params map to API names, convert pressure units and omit empty fields', () => {
    const { FF } = load(['conditions.js']);
    const c = FF.conditions;
    const atm = c.buildQuery({ fuel_class: 'solid', material: ' pmma ', o2_min: '21', o2_max: '', pressure_min: '1', p_unit: 'atm', flow_max: '0', outcome: 'burn_time', sort: 'x', run: 'y' });
    assert.deepEqual(plain(Object.keys(atm.query)), ['fuel_class', 'material', 'o2_min', 'pressure_min', 'flow_max', 'outcome']);
    assert.equal(atm.query.material, 'pmma');
    assert.equal(atm.query.pressure_min, 101.325);
    assert.equal(atm.query.flow_max, 0);
    const psia = c.buildQuery({ pressure_min: '14.7', pressure_max: '20', p_unit: 'psia' });
    assert.ok(Math.abs(psia.query.pressure_min - 101.3529) < 1e-3);
    assert.ok(Math.abs(psia.query.pressure_max - 137.8951) < 1e-3);
    const kpa = c.buildQuery({ pressure_max: '98.5', p_unit: 'bogus' });
    assert.equal(kpa.query.pressure_max, 98.5);
    assert.equal(c.queryString(c.buildQuery({ o2_max: '30', fuel_class: 'gas' }).query), 'fuel_class=gas&o2_max=30');
    assert.equal(c.cleanParams({ p_unit: 'kPa', q: 'x', fuel_class: ' ' }).p_unit, undefined);
});

test('invalid values and ranges are reported and not sent', () => {
    const { FF } = load(['conditions.js']);
    const c = FF.conditions;
    let r = c.buildQuery({ o2_min: '40', o2_max: '30' });
    assert.deepEqual(plain(r.query), {});
    assert.match(r.errors.o2, /larger/);
    r = c.buildQuery({ o2_max: '101', pressure_min: '-1', flow_min: 'abc', fuel_class: 'plasma' });
    assert.deepEqual(plain(r.query), {});
    assert.ok(r.errors.o2 && r.errors.pressure && r.errors.flow && r.errors.fuel_class);
    r = c.buildQuery({ o2_min: '10', o2_max: '10', pressure_min: '5', pressure_max: '1' });
    assert.deepEqual(plain(r.query), { o2_min: 10, o2_max: 10 });
    assert.ok(r.errors.pressure);
});

test('reference atmospheres convert psia to kPa', () => {
    const { FF } = load(['conditions.js']);
    const refs = FF.conditions.REFERENCE_ATMOSPHERES;
    assert.deepEqual(plain(refs.map(r => [r.psia, r.o2])), [[14.7, 21], [10.2, 26.5], [8.2, 34]]);
    assert.equal(refs[0].kpa.toFixed(2), '101.35');
    assert.equal(refs[1].kpa.toFixed(2), '70.33');
    assert.equal(refs[2].kpa.toFixed(2), '56.54');
});

test('plot model keeps zeros, never plots unknown, and aggregates identical points', () => {
    const { FF } = load(['conditions.js']);
    const records = [
        record('a', [21, 21], [101.3, 101.3]),
        record('b', [21, 21], [101.3, 101.3]),
        record('zero', [0, 0], [0, 0]),
        record('unk-p', [21, 21], null),
        record('unk-o', null, [50, 50]),
        record('sweep', [20, 25], [90, 90]),
        record('pend', [21, 21], [101.3, 101.3], { review_status: 'pending' }),
        record('dup', [30, 30], [100, 100], { flags: [{ code: 'duplicate_row' }] }),
        record('bad', [30, 30], [100, 100], { flags: [{ code: 'invalid_reading' }] }),
        record('note', null, null, { kind: 'note' }),
        record('huge', [3400, 3400], [100, 100]),
    ];
    const m = FF.conditions.plotModel(records);
    assert.equal(m.total, 11);
    assert.equal(m.unknown, 2);
    assert.equal(m.intervals, 1);
    assert.equal(m.plotted, 5);
    assert.equal(m.excluded, 4);
    const zero = m.marks.find(mark => mark.ids.includes('zero'));
    assert.ok(zero && zero.o2[0] === 0 && zero.pressure[0] === 0);
    assert.ok(!m.marks.some(mark => mark.ids.includes('unk-p') || mark.ids.includes('unk-o')));
    const merged = m.marks.find(mark => mark.ids.includes('a'));
    assert.deepEqual(plain(merged.ids), ['a', 'b']);
    assert.equal(merged.filled, true);
    assert.equal(m.marks.find(mark => mark.ids.includes('pend')).filled, false);
});

test('axis model covers data, references and the filter window with nice ticks', () => {
    const { FF } = load(['conditions.js']);
    const m = FF.conditions.plotModel([record('a', [15, 15], [60, 60])]);
    const axes = FF.conditions.axisModel(m, { o2_min: 30, pressure_max: 120 });
    assert.ok(axes.x.lo <= 15 && axes.x.hi >= 34 && axes.x.lo >= 0);
    assert.ok(axes.y.lo <= 56 && axes.y.hi >= 120);
    assert.ok(axes.x.ticks.length >= 3 && axes.y.atmTicks.length >= 2);
});

test('status info marks gaps only for not_in_PSI', () => {
    const { FF } = load(['conditions.js']);
    const info = FF.conditions.statusInfo;
    assert.equal(info(coverage('not_in_PSI', 0), {}).gap, true);
    for (const status of ['covered', 'pending_review', 'unknown_conditions']) assert.equal(info(coverage(status, 3), {}).gap, false);
    assert.equal(info(coverage('pending_review', 0), {}).emptyPending, true);
    assert.equal(info(coverage('covered', 0), {}).emptyPending, true);
    assert.equal(info(coverage('pending_review', 2), {}).emptyPending, false);
});

test('filter options are narrowed by fuel class and material with record counts', () => {
    const { FF } = load(['conditions.js']);
    const g = (fuel, material, geometry, n) => ({ conditions: { fuel_class: fuel, material, geometry, flow_direction: null }, run_record_count: n });
    const groups = [g('solid', 'pmma', 'film', 10), g('solid', 'pmma', 'cylinder', 5), g('droplet', 'heptane', 'droplet', 7)];
    const options = FF.conditions.optionsFromGroups;
    assert.deepEqual(plain(options(groups, 'fuel_class', {}).map(o => [o.value, o.count])), [['droplet', 7], ['solid', 15]]);
    assert.deepEqual(plain(options(groups, 'material', { fuel_class: 'solid' }).map(o => o.value)), ['pmma']);
    assert.deepEqual(plain(options(groups, 'geometry', { fuel_class: 'solid', material: 'pmma' }).map(o => o.value)), ['cylinder', 'film']);
    assert.deepEqual(plain(options(groups, 'flow_direction', {})), []);
});

test('filename slug and export object', () => {
    const { FF } = load(['conditions.js']);
    FF.cache.health = { snapshot_date: '2026-11-14' };
    assert.equal(FF.conditions.filterSlug({}), 'all');
    assert.equal(FF.conditions.filterSlug({ fuel_class: 'solid', o2_min: 30 }), 'solid_o2-ge30');
    const out = FF.conditions.buildExport({ query: { fuel_class: 'solid' }, runs: { data: [{ id: 'x' }], meta: { total: 1 } },
        coverage: { data: { counts: {} }, meta: {} } });
    assert.deepEqual(plain(Object.keys(out)), ['exported_at', 'snapshot_date', 'filters', 'api', 'records']);
    assert.equal(out.snapshot_date, '2026-11-14');
    assert.deepEqual(plain(Object.keys(out.api)), ['runs_meta', 'coverage']);
});

test('mount requests coverage and runs with identical filters', async () => {
    const records = [record('PSI-1:t:1', [21, 21], [101.3, 101.3])];
    const { FF, requests, document } = load(['conditions.js'], api('covered', records));
    const container = document.createElement('div');
    FF.views.conditions.mount(container, { view: 'conditions', args: [], params: { fuel_class: 'solid', pressure_min: '1', p_unit: 'atm', o2_min: '30', o2_max: '10' } });
    await wait();
    const cov = requests.filter(u => u.startsWith('/api/coverage') && u.includes('?'));
    const runs = requests.filter(u => u.startsWith('/api/runs'));
    assert.equal(cov.length, 1);
    assert.equal(runs.length, 1);
    const strip = u => { const p = new URL(u, 'http://x').searchParams; p.delete('limit'); p.delete('offset'); return p.toString(); };
    assert.equal(strip(cov[0]), 'fuel_class=solid&pressure_min=101.325');
    assert.equal(strip(runs[0]), strip(cov[0]));
    FF.views.conditions.unmount();
});

test('gap notice only for not_in_PSI; zero results with pending shows the explicit message', async () => {
    const run = async (status, records) => {
        const { FF, document } = load(['conditions.js'], api(status, records));
        const container = document.createElement('div');
        FF.views.conditions.mount(container, { view: 'conditions', args: [], params: { material: 'x' } });
        await wait();
        const result = { gap: container.qsa('.notice-gap'), warn: container.qsa('.notice-warn'), text: text(container) };
        FF.views.conditions.unmount();
        return result;
    };
    const gap = await run('not_in_PSI', []);
    assert.equal(gap.gap.length, 1);
    assert.match(text(gap.gap[0]), /^Not in PSI: no record in the saved PSI snapshot covers these filters and ranges\./);
    assert.match(text(gap.gap[0]), /Saffire-IV–VI and SoFIE results outside PSI are not verified here\.$/);
    const pending = await run('pending_review', []);
    assert.equal(pending.gap.length, 0);
    assert.match(pending.text, /a gap cannot be claimed/);
    for (const status of ['covered', 'unknown_conditions']) {
        const other = await run(status, [record('r', [21, 21], [101, 101])]);
        assert.equal(other.gap.length, 0);
    }
    const some = await run('pending_review', [record('r', [21, 21], [101, 101])]);
    assert.ok(!/a gap cannot be claimed/.test(some.text));
    assert.match(some.text, /1 source rows \(not individual experiments\)/);
});

test('table uses FF.runs when present and falls back to ids otherwise', async () => {
    const records = [record('PSI-1:t:1', [21, 21], [101.3, 101.3]), record('PSI-1:t:2', null, null)];
    let rendered = null;
    const { FF, document } = load(['conditions.js'], api('covered', records));
    FF.runs = { renderTable: (el, rows, opts) => { rendered = { rows, opts }; }, openDetail() {}, csv: () => 'csv' };
    const container = document.createElement('div');
    FF.views.conditions.mount(container, { view: 'conditions', args: [], params: { sort: 'o2' } });
    await wait();
    assert.equal(rendered.rows.length, 2);
    assert.equal(rendered.opts.sort, 'o2');
    assert.equal(typeof rendered.opts.onSelect, 'function');
    assert.match(text(container), /Plotted: 1 of 2 matching records; 1 have unknown O2 or pressure/);
    FF.views.conditions.unmount();

    const fallback = load(['conditions.js'], api('covered', records));
    const second = fallback.document.createElement('div');
    fallback.FF.views.conditions.mount(second, { view: 'conditions', args: [], params: {} });
    await wait();
    assert.match(text(second), /PSI-1:t:2/);
    fallback.FF.views.conditions.unmount();
});
