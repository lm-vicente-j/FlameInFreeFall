// Shared loader for frontend unit tests. Node built-ins only; no npm packages.
// Usage: const { load } = require('./harness.cjs'); const { FF, requests } = load(['studies.js'], respond);
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');

class Element {
    constructor(tag = 'div') {
        this.tagName = String(tag).toUpperCase();
        this.children = [];
        this.attributes = {};
        this.listeners = {};
        this.dataset = {};
        this.style = {};
        this.className = '';
        this.value = '';
        this.open = false;
        this.hidden = false;
        this.parentNode = null;
        this._text = '';
        const element = this;
        this.classList = {
            add(...names) { const set = new Set(element.className.split(/\s+/).filter(Boolean)); names.forEach(n => set.add(n)); element.className = [...set].join(' '); },
            remove(...names) { element.className = element.className.split(/\s+/).filter(n => n && !names.includes(n)).join(' '); },
            toggle(name, force) { const has = this.contains(name); const want = force === undefined ? !has : force; want ? this.add(name) : this.remove(name); return want; },
            contains(name) { return element.className.split(/\s+/).includes(name); },
        };
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
    append(...nodes) { for (const node of nodes) { if (node && typeof node === 'object') node.parentNode = this; this.children.push(node); } }
    prepend(...nodes) { this.children.unshift(...nodes); }
    replaceChildren(...nodes) { this._text = ''; this.children = []; this.append(...nodes); }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(c => c !== this); }
    setAttribute(key, value) { this.attributes[key] = String(value); if (key === 'id') this.id = String(value); }
    getAttribute(key) { return key in this.attributes ? this.attributes[key] : null; }
    hasAttribute(key) { return key in this.attributes; }
    removeAttribute(key) { delete this.attributes[key]; }
    addEventListener(event, callback) { (this.listeners[event] ||= []).push(callback); }
    removeEventListener(event, callback) { this.listeners[event] = (this.listeners[event] || []).filter(c => c !== callback); }
    dispatch(event, detail = {}) { for (const cb of this.listeners[event] || []) cb(Object.assign({ target: this, preventDefault() {}, stopPropagation() {} }, detail)); }
    click() { this.dispatch('click'); }
    focus() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
    scrollIntoView() {}
    getContext() { return {}; }
    getBoundingClientRect() { return { width: 800, height: 400, left: 0, top: 0 }; }
    // Depth-first helpers for assertions.
    all(predicate) { const out = []; const walk = n => { for (const c of n.children) { if (typeof c === 'object') { if (predicate(c)) out.push(c); walk(c); } } }; walk(this); return out; }
    find(predicate) { return this.all(predicate)[0] || null; }
    querySelector(selector) { return this.find(matcher(selector)); }
    // Like the DOM, product code gets a NodeList (no find/map); tests use qsa() for a plain array.
    querySelectorAll(selector) { return nodeList(this.all(matcher(selector))); }
    qsa(selector) { return this.all(matcher(selector)); }
}
function nodeList(items) {
    const list = Object.create({
        item(index) { return items[index] || null; },
        forEach(callback, thisArg) { items.forEach(callback, thisArg); },
        entries() { return items.entries(); }, keys() { return items.keys(); }, values() { return items.values(); },
        [Symbol.iterator]() { return items[Symbol.iterator](); },
    });
    items.forEach((item, index) => { list[index] = item; });
    Object.defineProperty(list, 'length', { value: items.length });
    return list;
}
function matcher(selector) {
    if (selector.startsWith('#')) return n => n.id === selector.slice(1) || n.attributes.id === selector.slice(1);
    if (selector.startsWith('.')) return n => n.classList.contains(selector.slice(1));
    return n => n.tagName === selector.toUpperCase();
}

function load(files, respond = () => ({ data: [], meta: {} }), extra = {}) {
    const nodes = new Map();
    const requests = [];
    const body = new Element('body');
    const document = {
        body,
        createElement: tag => new Element(tag),
        createElementNS: (_ns, tag) => new Element(tag),
        createTextNode: text => String(text),
        getElementById: id => {
            if (!nodes.has(id)) { const el = new Element(); el.id = id; nodes.set(id, el); }
            return nodes.get(id);
        },
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener() {},
    };
    const location = { hash: extra.hash || '' };
    const window = {
        location,
        history: { replaceState(_s, _t, hash) { location.hash = hash; } },
        addEventListener() {},
        scrollTo() {},
        matchMedia: () => ({ matches: false, addEventListener() {} }),
    };
    const context = vm.createContext(Object.assign({
        document, window, location, URL, URLSearchParams, AbortController, Intl, Blob: class { constructor(parts) { this.parts = parts; } },
        setTimeout, clearTimeout, console, navigator: { clipboard: { writeText: async () => {} } },
        fetch: async (url, options) => {
            requests.push(String(url));
            const result = await respond(String(url), options);
            const statusCode = result && result.status !== undefined && result.body !== undefined ? result.status : 200;
            return { ok: statusCode < 400, status: statusCode, json: async () => (result && result.body !== undefined ? result.body : result) };
        },
    }, extra.globals || {}));
    context.window = Object.assign(context, window);
    context.globalThis = context;
    for (const file of ['core.js', ...files]) {
        vm.runInContext(fs.readFileSync(path.join(root, 'static/js', file), 'utf8'), context, { filename: file });
    }
    return { FF: context.FF, context, requests, document, Element };
}

module.exports = { load, Element, root };
