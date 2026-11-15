const test = require('node:test');
const assert = require('node:assert/strict');
const { load, Element } = require('./harness.cjs');

const card = (acc, extra = {}) => Object.assign({
    accession: acc, acronym: 'AC', title: 'Title ' + acc, source_version: 3, coverage: 'metadata_and_documents',
    review: { status: 'approved' },
    summary: { text: 'Summary of ' + acc + ' at 0.5 atm', evidence_ids: [acc + ':meta:s#1'] },
    claims: [
        { id: 'C1', type: 'objective', text: 'Aim of ' + acc, evidence_ids: [acc + ':meta:o#1'] },
        { id: 'C2', type: 'reported_observation', text: 'Observed 21 %O2', evidence_ids: [acc + ':pdf:x#2'] },
        { id: 'C3', type: 'potential_application', text: 'Could help', evidence_ids: [acc + ':pdf:x#3'] },
    ],
    findings: [{ category: 'suppression', observation: 'C2', implication: 'C3', conditions: { text: 'At 1 atm', evidence_ids: [acc + ':pdf:x#4'] } }],
    comparison: { fuels: { text: '=cmd|fuel', evidence_ids: [acc + ':a#1'] }, hardware: { text: 'Rig, "quoted"', evidence_ids: [] } },
    limitations: [{ basis: 'source', text: 'Only one run', evidence_ids: [acc + ':l#1'] }],
    modeling_resources: [{ description: 'Table', evidence_ids: [], file_keys: ['psi-data/' + acc + '/Experimental table/a b.csv'] }],
    safety_categories: [{ category: 'suppression', evidence_ids: [acc + ':c#1'] }],
}, extra);
const respond = url => {
    const m = /\/api\/studies\/([^/?]+)$/.exec(url);
    if (m && m[1] === 'PSI-99') return { status: 404, body: { error: { code: 'not_found' } } };
    if (m) return { data: card(decodeURIComponent(m[1])), meta: {} };
    return { data: [{ accession: 'PSI-69', acronym: 'FLEX', title: 'Flame' }], meta: { total: 1, offset: 0, limit: 100 } };
};
const tick = () => new Promise(r => setTimeout(r, 5));
const setup = (r = respond) => { const env = load(['compare.js'], r); return Object.assign(env, { container: new Element('main') }); };

test('fetches both accessions and renders the table with the D3 notice', async () => {
    const { FF, requests, container } = setup();
    FF.views.compare.mount(container, { args: ['PSI-69', 'PSI-12'], params: {} });
    await tick();
    assert.ok(requests.includes('/api/studies/PSI-69'));
    assert.ok(requests.includes('/api/studies/PSI-12'));
    const text = container.textContent;
    assert.match(text, /Summary of PSI-69 at 0.5 atm/);
    assert.match(text, /Summary of PSI-12 at 0.5 atm/);
    assert.match(text, /stated aims, not results/i);
    assert.match(text, /Stated expectation, not a result/);
    assert.match(text, /fuel class, material, geometry, flow direction and hardware/);
    // Without FF.evidence the view falls back to a source count instead of crashing.
    assert.match(text, /1 source/);
});

test('missing attributes show Not stated; statements are never altered', async () => {
    const { FF, container } = setup();
    FF.views.compare.mount(container, { args: ['PSI-69', 'PSI-12'], params: {} });
    await tick();
    assert.match(container.textContent, /Not stated in this card/);
    assert.ok(container.all(n => n.classList.contains('unknown')).length > 0);
    assert.ok(container.textContent.includes('Rig, "quoted"'));
    assert.ok(container.textContent.includes('=cmd|fuel'));
});

test('file keys link to the file browser with the basename filter', async () => {
    const { FF, container } = setup();
    FF.views.compare.mount(container, { args: ['PSI-69', 'PSI-12'], params: {} });
    await tick();
    const link = container.find(n => n.tagName === 'A' && /#\/files\//.test(n.attributes.href || ''));
    assert.equal(link.attributes.href, '#/files/PSI-69?filename=a+b.csv');
});

test('CSV has both statements and evidence ids and neutralises formulas', () => {
    const { FF } = setup();
    const columns = ['PSI-69', 'PSI-12'].map(a => ({ accession: a, card: card(a), error: null }));
    const text = FF.compare.csv(columns);
    const lines = text.split('\r\n');
    assert.equal(lines[0], 'Group,Attribute,PSI-69 statement,PSI-69 evidence IDs,PSI-12 statement,PSI-12 evidence IDs');
    assert.ok(text.includes("'=cmd|fuel"));
    assert.ok(!/(^|,)=cmd/.test(text));
    assert.match(text, /PSI-69:meta:s#1/);
    assert.match(text, /Observation: Observed 21 %O2 → Conditions: At 1 atm → Implication: Could help/);
    assert.match(text, /Not stated in this card/);
});

test('same accession twice shows a message and fetches nothing', async () => {
    const { FF, requests, container } = setup();
    FF.views.compare.mount(container, { args: ['PSI-69', 'PSI-69'], params: {} });
    await tick();
    assert.match(container.textContent, /selected twice/);
    assert.equal(requests.filter(u => u.includes('/api/studies/PSI-69')).length, 0);
});

test('0 or 1 chosen shows an instruction; per-column errors are explicit', async () => {
    let env = setup();
    env.FF.views.compare.mount(env.container, { args: [], params: {} });
    assert.match(env.container.textContent, /Choose two investigations/);
    env = setup();
    env.FF.views.compare.mount(env.container, { args: ['PSI-69', 'PSI-99'], params: {} });
    await tick();
    assert.match(env.container.textContent, /PSI-99: No investigation PSI-99/);
    assert.match(env.container.textContent, /Summary of PSI-69/);
});

test('swap navigates to the reversed pair', async () => {
    const { FF, context, container } = setup();
    FF.views.compare.mount(container, { args: ['PSI-69', 'PSI-12'], params: {} });
    await tick();
    const swap = container.find(n => n.tagName === 'BUTTON' && n.textContent === 'Swap');
    swap.click();
    assert.equal(context.location.hash, '#/compare/PSI-12/PSI-69');
});
