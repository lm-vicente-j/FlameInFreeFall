// Run with: node --test tests/frontend/
const assert = require('node:assert/strict');
const test = require('node:test');
const { load } = require('./harness.cjs');

const tick = (ms = 15) => new Promise(resolve => setTimeout(resolve, ms));
const ok = (data, meta = {}) => ({ data, meta });
const evidenceItem = (id, extra = {}) => ({ id, excerpt: 'Excerpt for ' + id, investigation: id.split(':')[0],
    locator: { kind: 'metadata', field: 'objective' }, source_url: 'https://psi.nasa.gov/physci/repo/data/investigations/PSI-69', ...extra });
const card = (accession = 'PSI-69', extra = {}) => Object.assign({
    accession, acronym: 'FLEX', title: 'Flame Extinguishment Experiment', coverage: 'metadata_and_documents', source_version: 5,
    review: { status: 'approved', reviewer: 'A. Reviewer', reviewed_at: '2026-11-15T21:00:52Z' },
    generation: { method: 'skill', skill: 'research-card', model: 'm-1', generated_at: '2026-11-15T18:16:43+00:00' },
    summary: { text: 'Summary text.', evidence_ids: [accession + ':meta:objective#aaa'] },
    safety_categories: [{ category: 'suppression', evidence_ids: [accession + ':meta:objective#aaa'] }],
    comparison: { fuels: { text: 'Methanol', evidence_ids: [accession + ':meta:objective#aaa'] }, gravity: null },
    claims: [
        { id: 'C1', type: 'objective', text: 'An objective.', evidence_ids: [accession + ':meta:objective#aaa'] },
        { id: 'C2', type: 'reported_observation', text: 'An observation.', evidence_ids: [accession + ':meta:objective#bbb'] },
    ],
    findings: [{ observation: 'C2', conditions: { text: 'At 1 atm.', evidence_ids: [accession + ':meta:objective#bbb'] }, implication: 'C1', category: 'suppression' }],
    limitations: [{ basis: 'source', text: 'A limit.', evidence_ids: [] }],
    modeling_resources: [{ description: 'Table.', evidence_ids: [], file_keys: ['psi-data/PSI-69/Experimental table/PSI-69_x.csv'] }],
    evidence: [evidenceItem(accession + ':meta:objective#aaa'), evidenceItem(accession + ':meta:objective#bbb')],
}, extra);

test('search request carries q, safety_category and limit; URL state is kept', async () => {
    const { FF, requests, document } = load(['studies.js'], () => ok([], { total: 0, matches: [], query: 'ext', limit: 50, offset: 0 }));
    const container = document.createElement('main');
    FF.views.studies.mount(container, { args: [], params: { q: 'ext', category: 'suppression' } });
    await tick();
    assert.match(requests[0], /\/api\/studies\?/);
    const params = new URL('http://x' + requests[0]).searchParams;
    assert.equal(params.get('q'), 'ext');
    assert.equal(params.get('safety_category'), 'suppression');
    assert.equal(params.get('limit'), '50');
    assert.match(container.textContent, /No investigations match “ext”/);
});

test('HTTP failures stay visible errors, never mock data', async () => {
    const { FF, document } = load(['studies.js'], () => ({ status: 503, body: { error: { code: 'data_unavailable', details: { state: 'missing' } } } }));
    const container = document.createElement('main');
    FF.views.studies.mount(container, { args: [], params: {} });
    await tick();
    assert.match(container.textContent, /Prepared data unavailable \(missing\)/);
    assert.equal(container.qsa('.study-item').length, 0);
});

test('pagination reaches the last items', async () => {
    const all = Array.from({ length: 120 }, (_, i) => card('PSI-' + (i + 1)));
    const { FF, requests, document } = load(['studies.js'], url => {
        const p = new URL('http://x' + url).searchParams;
        const limit = +p.get('limit'), offset = +p.get('offset');
        return ok(all.slice(offset, offset + limit), { total: all.length, matches: [], query: '', limit, offset });
    });
    const container = document.createElement('main');
    FF.views.studies.mount(container, { args: [], params: { page: '3' } });
    await tick();
    assert.match(requests[0], /offset=100/);
    assert.equal(container.qsa('.study-item').length, 20);
    assert.match(container.textContent, /Showing 101–120 of 120/);
    assert.match(container.textContent, /120 investigations/);
});

test('search results mark query terms by splitting text, and title-only matches say so', async () => {
    const { FF, document } = load(['studies.js'], () => ok([card('PSI-69'), card('PSI-70')], {
        total: 2, query: 'extinction', limit: 50, offset: 0,
        matches: [{ accession: 'PSI-69', rank: 1, evidence: [evidenceItem('PSI-69:meta:objective#aaa', { excerpt: 'flame <img onerror=x> Extinction limit' })] },
                  { accession: 'PSI-70', rank: 2, evidence: [] }],
    }));
    const container = document.createElement('main');
    FF.views.studies.mount(container, { args: [], params: { q: 'extinction' } });
    await tick();
    const marks = container.qsa('mark');
    assert.equal(marks.length, 1);
    assert.equal(marks[0].textContent, 'Extinction');
    assert.match(container.textContent, /<img onerror=x>/);              // kept as text
    assert.equal(container.qsa('img').length, 0);
    assert.match(container.textContent, /Relevance rank 1/);
    assert.match(container.textContent, /Matched on title or acronym; no evidence passage/);
    assert.match(container.textContent, /2 matches for “extinction”/);
});

test('highlight handles regex metacharacters and empty queries', () => {
    const { FF } = load(['studies.js']);
    assert.equal(JSON.stringify(FF.studies.highlight('plain', '')), '["plain"]');
    const nodes = FF.studies.highlight('a (b) cxd c.d', 'c.d');
    assert.equal(nodes.filter(n => typeof n === 'object').length, 1); // '.' is literal, not a wildcard
});

test('compare selection allows two and navigates', async () => {
    const { FF, context, document } = load(['studies.js'], () => ok([card('PSI-1'), card('PSI-2'), card('PSI-3')], { total: 3, query: '', limit: 50, offset: 0, matches: [] }));
    const container = document.createElement('main');
    FF.views.studies.mount(container, { args: [], params: {} });
    await tick();
    const boxes = container.qsa('input').filter(b => b.dataset.accession);
    boxes[0].checked = true; boxes[0].dispatch('change');
    boxes[1].checked = true; boxes[1].dispatch('change');
    assert.equal(boxes[2].disabled, true);
    const bar = container.querySelector('.compare-bar');
    const button = bar.find(n => n.tagName === 'BUTTON' && /Compare PSI-1 and PSI-2/.test(n.textContent));
    assert.ok(button);
    button.click();
    assert.equal(context.window.location.hash, '#/compare/PSI-1/PSI-2');
    FF.views.studies.unmount();
});

test('evidence ids with # are encoded and stale content never survives a failure', async () => {
    const id1 = 'PSI-69:meta:objective#aaa', id2 = 'PSI-69:meta:objective#bad';
    const { FF, requests, document } = load(['studies.js'], url => {
        if (url.includes(encodeURIComponent(id2))) return { status: 503, body: { error: { code: 'data_unavailable', details: {} } } };
        if (url.includes('/api/evidence/')) return ok(evidenceItem(id1));
        return ok(card(), {});
    });
    FF.evidence.open('PSI-69', [id1, id2], 'Summary');
    await tick();
    assert.ok(requests.some(r => r.includes('/api/evidence/PSI-69%3Ameta%3Aobjective%23aaa')));
    const dialog = document.body.querySelector('dialog');
    assert.match(dialog.querySelector('blockquote').textContent, /Excerpt for/);
    assert.ok(dialog.qsa('a').some(a => a.getAttribute('href')));
    dialog.qsa('button').find(b => b.textContent === 'Next').click();
    await tick();
    assert.match(dialog.textContent, /The evidence text is unavailable/);
    assert.equal(dialog.querySelector('blockquote').textContent, '');
    assert.equal(dialog.qsa('a').filter(a => a.getAttribute('target') === '_blank').length, 0);
    assert.match(dialog.textContent, /Citation 2 of 2/);
});

test('evidence dialog: 404 message, javascript: source URLs refused, attribution from meta.source', async () => {
    const id = 'PSI-69:meta:objective#aaa';
    const { FF, document } = load(['studies.js'], url => {
        if (url.includes('/api/evidence/')) return ok(evidenceItem(id, { source_url: 'javascript:alert(1)' }));
        return ok(card(), { source: { investigators: [{ name: 'Ada Lovelace' }, 'Grace Hopper'] } });
    });
    FF.evidence.open('PSI-69', [id], 'Summary');
    await tick();
    const dialog = document.body.querySelector('dialog');
    assert.equal(dialog.qsa('a').filter(a => /^javascript:/.test(a.getAttribute('href') || '')).length, 0);
    assert.match(dialog.textContent, /link unavailable/);
    assert.match(dialog.textContent, /PSI investigators: Ada Lovelace, Grace Hopper/);
    assert.match(dialog.textContent, /authorship may differ/);
});

test('evidence dialog reports unknown ids', async () => {
    const { FF, document } = load(['studies.js'], () => ({ status: 404, body: { error: { code: 'not_found', details: {} } } }));
    FF.evidence.open('PSI-69', ['PSI-69:meta:x#zz'], '');
    await tick();
    assert.match(document.body.querySelector('dialog').textContent, /Unknown evidence id/);
});

test('citeMarkers: empty ids flagged, numbering follows the registered bibliography', () => {
    const { FF } = load(['studies.js']);
    assert.equal(FF.evidence.citeMarkers('PSI-69', [], 'x').className, 'cite-missing');
    FF.evidence.setNumbering({ 'PSI-69:a#1': 7 });
    const node = FF.evidence.citeMarkers('PSI-69', ['PSI-69:a#1', 'PSI-69:b#2'], 'x');
    assert.deepEqual(node.qsa('button').map(b => b.textContent), ['[7]', '[2]']);
});

test('citation is built only from supplied metadata', () => {
    const { FF } = load(['studies.js']);
    const none = FF.studies.buildCitation(card(), null);
    assert.equal(none.available, false);
    assert.equal(none.bibtex, null);
    assert.doesNotMatch(none.text, /20\d\d/);
    const partial = FF.studies.buildCitation(card(), { investigators: [{ name: 'Ada Lovelace' }, { name: 'Grace Hopper' }] });
    assert.match(partial.text, /^Ada Lovelace, Grace Hopper\. Flame Extinguishment Experiment \[Data set\]\./);
    assert.doesNotMatch(partial.text, /\(\d{4}\)|accessed/);
    assert.doesNotMatch(partial.bibtex, /year|urldate/);
    assert.doesNotMatch(partial.bibtex, /doi =/);
    // Real backend shape: roles arrays, MM-DD-YYYY investigation dates, snapshot retrieval timestamp.
    const full = FF.studies.buildCitation(card(), {
        investigators: [
            { name: 'Forman A. Williams', roles: ['Principal Investigator (PI)'], affiliation: 'UCSD' },
            { name: 'Daniel Dietrich', roles: ['Project Scientist'], affiliation: 'NASA GRC' },
            { name: 'Benjamin D. Shaw', roles: ['Co-Investigator (Co-I)'], affiliation: null },
        ],
        start_date: '08-01-2007', end_date: '07-31-2016', doi: '10.60555/mbq8-0451',
        retrieved_at: '2026-11-15T01:06:33.262144+00:00',
    });
    assert.match(full.text, /^Forman A\. Williams, Benjamin D\. Shaw\. /, 'only investigator roles are authors');
    assert.doesNotMatch(full.text, /Dietrich|\(20\d\d\)|08-0/, 'no project scientist, no invented year');
    assert.match(full.text, /https:\/\/doi\.org\/10\.60555\/mbq8-0451 \(accessed 2026-11-15\)\.$/);
    assert.match(full.bibtex, /doi = \{10\.60555\/mbq8-0451\}/);
    assert.match(full.bibtex, /urldate = \{2026-11-15\}/);
    assert.doesNotMatch(full.bibtex, /year/);
    assert.match(FF.studies.buildRecordCitation(card(), '2026-11-14'), /PSI-69, source version 5, review state: Reviewed .*snapshot 2026-11-14/);
});

test('detail page: 404 and 503 messages', async () => {
    let status = 404;
    const { FF, document } = load(['studies.js'], () => ({ status, body: { error: { code: 'x', details: { state: 'missing' } } } }));
    const container = document.createElement('main');
    FF.views.study.mount(container, { args: ['PSI-99'], params: {} });
    await tick();
    assert.match(container.textContent, /No investigation with accession PSI-99 in this snapshot/);
    status = 503;
    FF.views.study.mount(container, { args: ['PSI-99'], params: {} });
    await tick();
    assert.match(container.textContent, /unavailable/);
});

test('detail page renders sections, labels claim types, resolves findings and numbers references', async () => {
    const data = card();
    const { FF, document } = load(['studies.js'], () => ok(data, { evidence_state: 'available' }));
    const container = document.createElement('main');
    FF.views.study.mount(container, { args: ['PSI-69'], params: {} });
    await tick();
    const text = container.textContent;
    assert.match(text, /Reviewed by A\. Reviewer on 2026-11-15/);
    assert.match(text, /Drafted with the research-card skill \(m-1\) on 2026-11-15/);
    assert.match(text, /Reported observations/);
    assert.match(text, /Objectives and hypotheses \(not results\)/);
    assert.match(text, /An observation\./);           // finding resolved to claim text
    assert.match(text, /Not stated in this card/);     // gravity null
    assert.match(text, /Investigator and publication metadata are not available from this server\./);
    assert.equal(container.qsa('.reference').length, 2);
    assert.ok(container.qsa('a').some(a => a.getAttribute('href') === '#/files/PSI-69?filename=PSI-69_x.csv'));
    FF.views.study.unmount();
});

test('export payload equals the API data object, with the expected filename and no extra fetch', async () => {
    const data = card();
    let downloaded = null;
    const { FF, requests, document } = load(['studies.js'], () => ok(data, {}));
    const original = FF.download;
    FF.download = (name, body, type) => { downloaded = { name, body, type }; };
    const container = document.createElement('main');
    FF.views.study.mount(container, { args: ['PSI-69'], params: {} });
    await tick();
    const before = requests.length;
    container.qsa('button').find(b => b.textContent === 'Export card (JSON)').click();
    assert.equal(requests.length, before);
    assert.equal(downloaded.name, 'PSI-69_v5_research-card.json');
    assert.deepEqual(JSON.parse(downloaded.body), data);
    assert.equal(downloaded.body, JSON.stringify(data, null, 2));
    FF.download = original;
});

test('a late close event after reopening does not cancel the new evidence request', async () => {
    const id = 'PSI-69:meta:objective#aaa';
    const { FF, document } = load(['studies.js'], url => url.includes('/api/evidence/')
        ? { data: { id, excerpt: 'Exact excerpt text', investigation: 'PSI-69', locator: { kind: 'metadata', field: 'objective' }, source_url: 'https://psi.nasa.gov/x' }, meta: {} }
        : { data: {}, meta: { source: null } });
    FF.evidence.open('PSI-69', [id], 'Summary');
    await tick();
    const dialog = document.body.find(n => n.tagName === 'DIALOG');
    dialog.close();                              // Esc: open becomes false, "close" event still queued
    FF.evidence.open('PSI-69', [id], 'Summary'); // user opens a citation again straight away
    dialog.dispatch('close');                    // the queued event arrives late
    await tick();
    assert.match(dialog.textContent, /Exact excerpt text/);
    assert.doesNotMatch(dialog.textContent, /Loading evidence/);
});
