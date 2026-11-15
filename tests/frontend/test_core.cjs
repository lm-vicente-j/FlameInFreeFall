// Core API client and helpers. Node built-ins only.
const assert = require('node:assert/strict');
const test = require('node:test');
const { load } = require('./harness.cjs');

// A fetch stub whose responses are scripted per call: 'cut' = body cut short, 'reset' = connection failure.
function scripted(steps) {
    const calls = [];
    const fetch = async (url) => {
        calls.push(String(url));
        const step = steps[Math.min(calls.length - 1, steps.length - 1)];
        if (step === 'reset') throw new TypeError('fetch failed');
        if (step === 'abort') { const error = new Error('aborted'); error.name = 'AbortError'; throw error; }
        const status = step === 503 ? 503 : 200;
        return { ok: status < 400, status, json: async () => {
            if (step === 'cut') throw new SyntaxError('Unexpected end of JSON input');
            if (status === 503) return { error: { code: 'data_unavailable', details: { state: 'catalog_unavailable' } } };
            return { data: [1], meta: { total: 1 } };
        } };
    };
    return { calls, fetch };
}

test('a truncated body or reset connection is retried, then succeeds', async () => {
    for (const failure of ['cut', 'reset']) {
        const stub = scripted([failure, failure, 'ok']);
        const { FF } = load([], undefined, { globals: { fetch: stub.fetch } });
        const body = await FF.api('/api/studies');
        assert.deepEqual([...body.data], [1]);
        assert.equal(stub.calls.length, 3, failure);
    }
});

test('persistent truncation surfaces a clear error after two retries', async () => {
    const stub = scripted(['cut']);
    const { FF } = load([], undefined, { globals: { fetch: stub.fetch } });
    await assert.rejects(FF.api('/api/studies'), error => error.code === 'truncated' && /incomplete/.test(error.message));
    assert.equal(stub.calls.length, 3);
});

test('HTTP errors and aborts are never retried', async () => {
    const unavailable = scripted([503]);
    let loaded = load([], undefined, { globals: { fetch: unavailable.fetch } });
    await assert.rejects(loaded.FF.api('/api/studies'), error => error.status === 503 && /catalog_unavailable/.test(error.message));
    assert.equal(unavailable.calls.length, 1);
    const aborted = scripted(['abort']);
    loaded = load([], undefined, { globals: { fetch: aborted.fetch } });
    await assert.rejects(loaded.FF.api('/api/studies'), error => error.name === 'AbortError');
    assert.equal(aborted.calls.length, 1);
});

test('quantities keep zero, intervals and unknowns; CSV neutralises formulas', () => {
    const { FF } = load([]);
    assert.equal(FF.formatQuantity({ min: 0, max: 0, unit: 'percent', method: 'parsed' }, 'percent'), '0');
    assert.equal(FF.formatQuantity({ min: 1, max: 2, unit: 'kPa', method: 'parsed', qualifier: 'approximate' }, 'kPa'), '≈ 1–2');
    assert.equal(FF.formatQuantity({ min: 1, max: 1, unit: 'psi', method: 'parsed' }, 'kPa'), 'Unknown');
    assert.equal(FF.formatQuantity({ method: 'unknown', min: null, max: null }), 'Unknown');
    assert.equal(FF.toCsv(['a'], [['=SUM(A1)'], [-3], ['x,"y"']]), "a\r\n'=SUM(A1)\r\n-3\r\n\"x,\"\"y\"\"\"\r\n");
});

test('routes round-trip through the hash and drop empty parameters', () => {
    const { FF } = load([]);
    const hash = FF.buildHash('compare', ['PSI-69', 'PSI-99'], { q: 'a b', empty: '' });
    assert.equal(hash, '#/compare/PSI-69/PSI-99?q=a+b');
    assert.deepEqual(JSON.parse(JSON.stringify(FF.parseHash(hash))), { view: 'compare', args: ['PSI-69', 'PSI-99'], params: { q: 'a b' } });
    assert.equal(FF.safeUrl('javascript:alert(1)'), null);
});
