// Shared helpers for every view. Classic script: attaches to the global FF namespace.
// Load order (see index.html): core.js, then view modules, then main.js.
(function (global) {
    "use strict";
    const FF = global.FF || (global.FF = {});

    // ---------- DOM ----------
    // h("p", {class: "note"}, "text", childNode, ...). Strings become text nodes, never HTML.
    function h(tag, attributes, ...children) {
        const node = document.createElement(tag);
        if (attributes) {
            for (const [key, value] of Object.entries(attributes)) {
                if (value === null || value === undefined || value === false) continue;
                if (key === "class") node.className = value;
                else if (key === "text") node.textContent = value;
                else if (key.startsWith("on") && typeof value === "function") {
                    node.addEventListener(key.slice(2).toLowerCase(), value);
                } else if (key === "dataset") Object.assign(node.dataset, value);
                else if (value === true) node.setAttribute(key, "");
                else node.setAttribute(key, String(value));
            }
        }
        append(node, children);
        return node;
    }
    function append(node, children) {
        for (const child of children.flat(Infinity)) {
            if (child === null || child === undefined || child === false) continue;
            node.append(typeof child === "string" || typeof child === "number" ? String(child) : child);
        }
        return node;
    }
    function clear(node, ...children) {
        node.replaceChildren();
        return append(node, children);
    }
    function button(label, onClick, attributes = {}) {
        return h("button", Object.assign({ type: "button", onclick: onClick }, attributes), label);
    }
    // Status line: role=status for screen readers; error styling when needed.
    function status(node, text, kind = "") {
        node.textContent = text;
        node.className = "status" + (kind ? " status-" + kind : "");
        if (!node.getAttribute("role")) node.setAttribute("role", "status");
        return node;
    }
    // External links only for http(s). Returns <a> or a plain <span> when the URL is unusable.
    function safeUrl(value) {
        if (!value) return null;
        try {
            const url = new URL(value);
            return ["https:", "http:"].includes(url.protocol) ? url.href : null;
        } catch { return null; }
    }
    function externalLink(label, url, attributes = {}) {
        const href = safeUrl(url);
        if (!href) return h("span", { class: "muted" }, label + " (link unavailable)");
        return h("a", Object.assign({ href, target: "_blank", rel: "noopener noreferrer" }, attributes), label);
    }

    // ---------- API ----------
    class ApiError extends Error {
        constructor(message, statusCode, code, state) {
            super(message);
            this.status = statusCode;
            this.code = code;
            this.state = state;
        }
    }
    // Transport failures (connection reset, body cut short) are retried; HTTP errors and aborts are not.
    // All API calls are idempotent GETs, so a retry cannot change server state.
    const RETRIES = 2;
    async function api(path, options = {}) {
        for (let attempt = 0; ; attempt += 1) {
            try {
                return await apiOnce(path, options);
            } catch (error) {
                const transient = error instanceof ApiError && (error.code === "network_error" || error.code === "truncated");
                if (!transient || attempt >= RETRIES || (options.signal && options.signal.aborted)) throw error;
            }
        }
    }
    async function apiOnce(path, options) {
        let response;
        try {
            response = await fetch(FF.config.apiBase + path, { signal: options.signal });
        } catch (error) {
            if (error.name === "AbortError") throw error;
            throw new ApiError("The local server could not be reached.", 0, "network_error", "network_error");
        }
        let body = null, unreadable = false;
        try {
            body = await response.json();
        } catch (error) {
            // An abort during the body read is still an abort, not a malformed response.
            if (error.name === "AbortError" || (options.signal && options.signal.aborted)) throw error;
            unreadable = true;
        }
        if (!response.ok) {
            const code = body?.error?.code || "error";
            const state = body?.error?.details?.state || null;
            const message = response.status === 503
                ? "Prepared data unavailable (" + (state || code) + ")."
                : response.status === 404 ? "Record not found."
                : response.status === 400 ? "Invalid request parameters: " +
                    ((body?.error?.details?.parameters || []).join(", ") || "unknown") + "."
                : "The request failed (HTTP " + response.status + ").";
            throw new ApiError(message, response.status, code, state);
        }
        if (unreadable) {
            throw new ApiError("The server response was incomplete; please retry.", response.status, "truncated", null);
        }
        if (!body || !("data" in body) || !body.meta) {
            throw new ApiError("Incompatible API response.", response.status, "contract", null);
        }
        return body;
    }
    // Fetch every page of a paginated list endpoint (limit max 100).
    async function apiAll(path, params = {}, options = {}) {
        const items = [];
        let offset = 0, total = 0, meta = null;
        do {
            const query = new URLSearchParams(Object.assign({}, params, { limit: 100, offset }));
            const page = await api(path + "?" + query, options);
            items.push(...page.data);
            meta = meta || page.meta;
            if (page.meta.sources) {
                meta.sources = mergeSources(meta === page.meta ? [] : meta.sources, page.meta.sources);
            }
            total = page.meta.total;
            offset += 100;
            if (options.onProgress) options.onProgress(Math.min(offset, total), total);
        } while (offset < total);
        return { data: items, meta: Object.assign({}, meta, { total, offset: 0, limit: items.length }) };
    }
    function mergeSources(existing, incoming) {
        const seen = new Map((existing || []).map(item => [item.investigation + "/" + item.table, item]));
        for (const item of incoming || []) seen.set(item.investigation + "/" + item.table, item);
        return [...seen.values()];
    }
    function encodeId(id) { return encodeURIComponent(id); } // '#' -> %23 is required for evidence IDs.

    // ---------- Formatting ----------
    const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 });
    function formatNumber(value, digits) {
        if (!Number.isFinite(value)) return "—";
        if (digits !== undefined) {
            return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
        }
        return numberFormat.format(value);
    }
    // A quantity is known when it is not method=unknown, has the expected unit and finite ordered bounds.
    function isKnownQuantity(quantity, unit) {
        return Boolean(quantity) && quantity.method !== "unknown" && (!unit || quantity.unit === unit) &&
            Number.isFinite(quantity.min) && Number.isFinite(quantity.max) && quantity.min <= quantity.max;
    }
    function isPointQuantity(quantity, unit) {
        return isKnownQuantity(quantity, unit) && quantity.min === quantity.max;
    }
    // "21", "≈ 0", "0.5–2.0", or "Unknown". Never invents values. Valid zero survives.
    function formatQuantity(quantity, unit, digits) {
        if (!isKnownQuantity(quantity, unit)) return "Unknown";
        const text = quantity.min === quantity.max ? formatNumber(quantity.min, digits)
            : formatNumber(quantity.min, digits) + "–" + formatNumber(quantity.max, digits);
        return (quantity.qualifier === "approximate" ? "≈ " : "") + text;
    }
    function formatBytes(bytes) {
        if (!Number.isFinite(bytes)) return "Unknown";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let value = bytes, index = 0;
        while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
        return (index === 0 ? String(value) : value.toFixed(value < 10 ? 1 : 0)) + " " + units[index];
    }
    const KPA_PER_ATM = 101.325;
    const KPA_PER_PSI = 6.894757293168361;

    // ---------- Vocabulary ----------
    const LABELS = {
        review: { approved: "Reviewed", pending: "Pending review", rejected: "Rejected",
            not_required: "No review required", reviewed: "Reviewed" },
        method: { parsed: "Parsed from table", mapped: "Mapped via reviewed alias", manual: "Set by curator",
            llm: "AI-extracted", extracted: "AI-extracted", unknown: "Not recorded" },
        claim: { objective: "Objective", approach: "Approach", hypothesis: "Hypothesis",
            expected_impact: "Expected impact", potential_application: "Potential application",
            reported_observation: "Reported observation" },
        category: { prevention: "Prevention", detection: "Detection", suppression: "Suppression" },
        comparison: { fuels: "Fuels", geometry: "Geometry", oxygen: "Oxygen", pressure: "Pressure",
            flow: "Flow", gravity: "Gravity", measurements: "Measurements", hardware: "Hardware" },
        kind: { run: "Run", range: "Range", session: "Session summary", note: "Note", duplicate: "Duplicate" },
        gravity: { microgravity: "Microgravity", normal: "1 g ground test" },
        coverage: { metadata_only: "Metadata only", metadata_and_documents: "Metadata and documents",
            metadata_documents_and_tables: "Metadata, documents and tables" },
        outcome: { burn_time: "Burn time", burning_rate: "Burning rate", extinction_diameter: "Extinction diameter",
            test_end: "Test end", burn_length: "Burn length", spread_length: "Spread length",
            spread_rate: "Spread rate", ignition: "Ignition", extinction: "Extinction", blowoff: "Blowoff",
            weight_loss_rate: "Weight-loss rate", flames_ignited: "Flames ignited", observation: "Observation" },
        access: { public: "Public", restricted: "Restricted", hidden: "Hidden" },
        flag: { invalid_reading: "Invalid reading", duplicate_row: "Duplicate row",
            references_other_rows: "Refers to other rows", inconsistent_values: "Inconsistent values",
            suspected_typo: "Suspected typo" },
        link: { confirmed: "Confirmed link", ambiguous: "Ambiguous candidate" },
        flowDirection: { concurrent: "Concurrent", opposed: "Opposed", quiescent: "Quiescent" },
        fuelClass: { solid: "Solid", droplet: "Droplet", gas: "Gas" },
        limitationBasis: { source: "Stated by source", coverage: "Coverage of this record" },
    };
    function label(group, value, fallback) {
        if (value === null || value === undefined || value === "") return fallback || "Not recorded";
        return (LABELS[group] && LABELS[group][value]) || String(value).replace(/_/g, " ");
    }
    // Review status marker: <span class="review review-approved">Reviewed</span>
    function reviewBadge(statusValue) {
        const value = statusValue || "unknown";
        return h("span", { class: "review review-" + value }, label("review", value, "Review state not given"));
    }

    // ---------- Routing (hash-based, shareable) ----------
    // #/studies?q=flex  #/study/PSI-69  #/compare/PSI-69/PSI-99  #/conditions?fuel_class=solid  #/files/PSI-69
    function parseHash(hash) {
        const raw = (hash || "").replace(/^#\/?/, "");
        const [pathPart, queryPart = ""] = raw.split("?");
        const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
        return { view: segments[0] || "studies", args: segments.slice(1),
            params: Object.fromEntries(new URLSearchParams(queryPart)) };
    }
    function buildHash(view, args = [], params = {}) {
        const query = new URLSearchParams(Object.entries(params).filter(([, v]) =>
            v !== null && v !== undefined && v !== "")).toString();
        return "#/" + [view, ...args.map(encodeURIComponent)].join("/") + (query ? "?" + query : "");
    }
    function navigate(view, args = [], params = {}) { global.location.hash = buildHash(view, args, params); }
    // Update the query part without triggering a re-render (filters, search box).
    function replaceParams(view, args = [], params = {}) {
        const hash = buildHash(view, args, params);
        if (global.location.hash !== hash) global.history.replaceState(null, "", hash);
    }

    // ---------- Downloads ----------
    function download(filename, text, type = "application/json") {
        const blob = new Blob([text], { type: type + ";charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = h("a", { href: url, download: filename });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    function csvCell(value) {
        const text = value === null || value === undefined ? "" : String(value);
        // Neutralise spreadsheet formula injection, then quote.
        const safe = /^[=+\-@\t\r]/.test(text) && !/^-?\d/.test(text) ? "'" + text : text;
        return /[",\n\r]/.test(safe) ? '"' + safe.replace(/"/g, '""') + '"' : safe;
    }
    function toCsv(header, rows) {
        return [header, ...rows].map(row => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
    }

    // ---------- Shared state ----------
    // Cached health and study index (accession → {accession, title, acronym}) used by several views.
    const cache = { health: null, studyIndex: null };
    async function studyIndex() {
        if (!cache.studyIndex) {
            cache.studyIndex = apiAll("/api/studies").then(result => result.data).catch(error => {
                cache.studyIndex = null;
                throw error;
            });
        }
        return cache.studyIndex;
    }
    function studyLabel(study) {
        return study.acronym ? study.acronym + " — " + study.title : study.title;
    }

    // Views register here: FF.views.studies = { mount(container, route) }. main.js calls mount on route change.
    FF.views = FF.views || {};
    FF.config = Object.assign({ apiBase: "" }, FF.config || {});
    Object.assign(FF, {
        h, append, clear, button, status, safeUrl, externalLink,
        ApiError, api, apiAll, encodeId,
        formatNumber, formatQuantity, isKnownQuantity, isPointQuantity, formatBytes, KPA_PER_ATM, KPA_PER_PSI,
        LABELS, label, reviewBadge,
        parseHash, buildHash, navigate, replaceParams,
        download, toCsv, csvCell,
        cache, studyIndex, studyLabel,
        PSI_INVESTIGATION_URL: "https://psi.nasa.gov/physci/repo/data/investigations/",
    });
})(typeof window !== "undefined" ? window : globalThis);
