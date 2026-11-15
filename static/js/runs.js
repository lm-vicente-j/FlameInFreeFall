// Runs: sortable source-row table, traceable record dialog and CSV export.
// Public API (used by the condition explorer): FF.runs.renderTable, openDetail, csv, sortRecords.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, button, status, label, formatQuantity, isKnownQuantity } = FF;

    const AI_TITLE = "AI-extracted; see record for source text";
    const DAGGER_TITLE = "Uncalibrated display reading, not a measured velocity";
    const GROUND = "1 g ground test";

    // ---------- Record helpers ----------
    function parseId(id) {
        const m = /^PSI-(\d+):([^:]+):(\d+)$/.exec(String(id || ""));
        return m ? { accession: "PSI-" + m[1], number: Number(m[1]), table: m[2], row: Number(m[3]) }
            : { accession: String(id || ""), number: Infinity, table: "", row: Infinity };
    }
    const isQuantity = item => Boolean(item) && typeof item === "object" && "min" in item;
    function categoryValue(item) {
        return item && item.value !== null && item.value !== undefined && item.value !== "" ? String(item.value) : null;
    }
    function gravityLabel(gravity) {
        if (gravity === "normal") return GROUND;
        if (gravity === "microgravity") return label("gravity", "microgravity");
        return "Gravity not recorded";
    }
    // A flow reading is a raw instrument display unless the record says a calibration was applied.
    // Rule from the data: the flow comes from a "... display" column and the note does not state a
    // velocity conversion ("velocity = ...").
    function isUncalibratedFlow(quantity) {
        if (!quantity || quantity.method === "unknown") return false;
        const fromDisplay = (quantity.columns || []).some(column => /display/i.test(column));
        return fromDisplay && !/^\s*velocity\s*=/i.test(quantity.note || "");
    }
    function resultText(result) {
        if (isQuantity(result)) {
            const text = formatQuantity(result, result.unit);
            return text === "Unknown" ? text : text + (result.unit ? " " + result.unit : "");
        }
        const value = categoryValue(result);
        return value === null ? "Unknown" : value;
    }
    const resultIsUnknown = result => isQuantity(result) ? !isKnownQuantity(result, result.unit) : categoryValue(result) === null;
    const isAi = item => Boolean(item) && item.method === "llm";
    const anyAi = record => Object.values(record.conditions || {}).some(isAi) ||
        (record.outcomes || []).some(outcome => isAi(outcome.result));

    // ---------- Sorting ----------
    const quantityKey = q => isKnownQuantity(q) ? [q.min, q.max] : null;
    const textKey = value => value === null || value === undefined || value === "" ? null : String(value).toLowerCase();
    const padAccession = number => Number.isFinite(number) ? String(number).padStart(8, "0") : "zzzzzzzz";
    const COLUMNS = [
        { key: "id", title: "Record", key_of: null },
        { key: "study", title: "Investigation / table", key_of: r => { const p = parseId(r.id); return padAccession(p.number) + ":" + p.table; } },
        { key: "kind", title: "Kind", key_of: r => textKey(label("kind", r.kind)) },
        { key: "fuel", title: "Fuel / material", key_of: r => {
            const fuel = categoryValue(r.conditions.fuel_class), material = categoryValue(r.conditions.material);
            return fuel === null && material === null ? null : (fuel || "~") + "|" + (material || "~"); } },
        { key: "geometry", title: "Geometry", key_of: r => textKey(categoryValue(r.conditions.geometry)) },
        { key: "direction", title: "Flow direction", key_of: r => textKey(categoryValue(r.conditions.flow_direction)) },
        { key: "o2", title: "O2 (%)", numeric: true, key_of: r => quantityKey(r.conditions.o2_percent) },
        { key: "pressure", title: "Pressure (kPa)", numeric: true, key_of: r => quantityKey(r.conditions.pressure_kpa) },
        { key: "flow", title: "Flow (cm/s)", numeric: true, key_of: r => quantityKey(r.conditions.flow_cm_s) },
        { key: "outcomes", title: "Outcomes", key_of: r => (r.outcomes || []).length ? textKey(label("outcome", r.outcomes[0].type)) : null },
        { key: "review", title: "Review", key_of: r => textKey(r.review_status) },
        { key: "flags", title: "Flags", numeric: true, key_of: r => [(r.flags || []).length, (r.flags || []).length] },
    ];
    const COLUMN_BY_KEY = Object.fromEntries(COLUMNS.map(column => [column.key, column]));

    function parseSort(sort) {
        const [key, direction] = String(sort || "").split(":");
        return COLUMN_BY_KEY[key] ? { key, direction: direction === "desc" ? "desc" : "asc" } : { key: "id", direction: "asc" };
    }
    function compareId(a, b) {
        const pa = parseId(a.id), pb = parseId(b.id);
        return (pa.number - pb.number) || (pa.table < pb.table ? -1 : pa.table > pb.table ? 1 : 0) || (pa.row - pb.row) || 0;
    }
    // Both keys known: numbers/intervals by min then max, text by locale order.
    function compareKeys(a, b) {
        if (Array.isArray(a)) return (a[0] - b[0]) || (a[1] - b[1]) || 0;
        return a < b ? -1 : a > b ? 1 : 0;
    }
    // Returns a new array. Unknown values sort last in both directions; ties fall back to
    // accession number, table, row (ascending) so the order is stable and reproducible.
    function sortRecords(records, sort) {
        const { key, direction } = parseSort(sort);
        const column = COLUMN_BY_KEY[key];
        const sign = direction === "desc" ? -1 : 1;
        const keyed = records.map(record => ({ record, value: column.key_of ? column.key_of(record) : null }));
        keyed.sort((x, y) => {
            if (column.key_of) {
                const xu = x.value === null, yu = y.value === null;
                if (xu !== yu) return xu ? 1 : -1;
                if (!xu) {
                    const c = compareKeys(x.value, y.value);
                    if (c) return c * sign;
                }
                return compareId(x.record, y.record);
            }
            return compareId(x.record, y.record) * sign;
        });
        return keyed.map(item => item.record);
    }

    function pageInfo(total, page, pageSize) {
        const pages = Math.max(1, Math.ceil(total / pageSize));
        const current = Math.min(Math.max(1, Math.floor(page) || 1), pages);
        const start = total === 0 ? 0 : (current - 1) * pageSize;
        return { pages, page: current, start, end: Math.min(total, start + pageSize) };
    }

    // ---------- Cell building blocks ----------
    const aiMark = () => h("sup", { class: "ai-mark" }, h("abbr", { title: AI_TITLE }, "AI"));
    const daggerMark = () => h("sup", { class: "dagger" }, h("abbr", { title: DAGGER_TITLE }, "†"));
    function unknownNode(text = "Unknown") { return h("span", { class: "unknown" }, text); }

    function quantityCell(quantity, options = {}) {
        if (!isKnownQuantity(quantity, options.unit)) return unknownNode();
        const text = formatQuantity(quantity, options.unit);
        return h("span", { class: "num" }, text, isAi(quantity) ? aiMark() : null,
            options.uncalibrated && isUncalibratedFlow(quantity) ? daggerMark() : null);
    }
    function categoryCell(item, text) {
        const value = categoryValue(item);
        if (value === null) return unknownNode();
        const attrs = {};
        if (item.quote && item.quote !== value) attrs.title = "Source text: " + item.quote;
        return h("span", attrs, text || value, isAi(item) ? aiMark() : null);
    }
    function outcomeItem(outcome) {
        const unknown = resultIsUnknown(outcome.result);
        return h("li", { class: "run-outcome" },
            h("span", { class: "run-outcome-type" }, label("outcome", outcome.type)), ": ",
            unknown ? unknownNode() : h("span", {}, resultText(outcome.result)),
            isAi(outcome.result) ? aiMark() : null,
            " ", h("span", { class: "muted" }, "(" + gravityLabel(outcome.gravity) + ")"));
    }
    function outcomesCell(record) {
        if (!(record.outcomes || []).length) return unknownNode("None recorded");
        return h("ul", { class: "run-outcomes" }, record.outcomes.map(outcomeItem));
    }
    function flagsCell(record) {
        const flags = record.flags || [];
        if (!flags.length) return h("span", { class: "muted" }, "0");
        const title = flags.map(flag => label("flag", flag.code) + ": " + flag.detail).join("\n");
        return h("span", { title }, String(flags.length), " ", h("span", { class: "muted small" }, flags.length === 1 ? "flag" : "flags"));
    }

    function sourceMap(sources) {
        const map = new Map();
        const list = Array.isArray(sources) ? sources : Object.values(sources || {});
        for (const item of list) if (item && item.investigation) map.set(item.investigation + ":" + item.table, item.source || item);
        return map;
    }
    const sourceFor = (map, record) => { const p = parseId(record.id); return map.get(p.accession + ":" + p.table) || null; };

    // ---------- Table ----------
    function renderTable(container, records, options = {}) {
        const pageSize = options.pageSize || 50;
        const sources = sourceMap(options.sources);
        const onSelect = options.onSelect || (() => {});
        let sort = parseSort(options.sort);
        let sorted = sortRecords(records, sort.key + ":" + sort.direction);
        let page = 1;
        let focusKey = null;

        function setSort(key) {
            const direction = sort.key === key && sort.direction === "asc" ? "desc" : "asc";
            sort = { key, direction };
            sorted = sortRecords(records, key + ":" + direction);
            page = 1;
            focusKey = key;
            draw();
            if (options.onSort) options.onSort(key + ":" + direction);
        }
        function setPage(next) { page = next; draw(); }

        function headerCell(column) {
            const active = sort.key === column.key;
            return h("th", { scope: "col", class: column.numeric ? "n" : null,
                "aria-sort": active ? (sort.direction === "asc" ? "ascending" : "descending") : "none" },
                h("button", { type: "button", dataset: { sortKey: column.key },
                    onclick: () => setSort(column.key) }, column.title));
        }
        function row(record) {
            const parsed = parseId(record.id);
            const source = sourceFor(sources, record);
            const c = record.conditions;
            const fuel = categoryValue(c.fuel_class), material = categoryValue(c.material);
            const select = () => onSelect(record.id);
            return h("tr", { tabindex: "0", class: "run-row", dataset: { runId: record.id },
                onclick: select,
                onkeydown: event => {
                    if (event.target && event.target.tagName === "BUTTON") return;
                    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
                } },
                h("th", { scope: "row", class: "run-id-cell" }, h("span", { class: "id" }, record.id), h("div", { class: "muted small" }, "row " + parsed.row)),
                h("td", { title: source ? source.filename : null }, h("span", { class: "id" }, parsed.accession), h("div", { class: "muted small" }, parsed.table)),
                h("td", {}, h("span", { class: "tag" }, label("kind", record.kind))),
                h("td", {}, fuel === null && material === null ? unknownNode() : h("div", {},
                    fuel !== null ? h("span", { class: "muted small" }, label("fuelClass", fuel)) : null,
                    fuel !== null ? h("br") : null,
                    material !== null ? categoryCell(c.material) : unknownNode("Material unknown"))),
                h("td", {}, categoryCell(c.geometry)),
                h("td", {}, categoryCell(c.flow_direction, label("flowDirection", categoryValue(c.flow_direction)))),
                h("td", { class: "n" }, quantityCell(c.o2_percent, { unit: "percent" })),
                h("td", { class: "n" }, quantityCell(c.pressure_kpa, { unit: "kPa" })),
                h("td", { class: "n" }, quantityCell(c.flow_cm_s, { unit: "cm/s", uncalibrated: true })),
                h("td", { class: "run-outcomes-cell" }, outcomesCell(record)),
                h("td", {}, FF.reviewBadge(record.review_status)),
                h("td", {}, flagsCell(record)),
                h("td", {}, button("Details", event => { event.stopPropagation(); select(); },
                    { class: "btn-link", "aria-label": "Details for " + record.id })));
        }
        function draw() {
            if (!records.length) {
                clear(container, h("p", { class: "empty" }, "No source rows match these filters."));
                return;
            }
            const info = pageInfo(sorted.length, page, pageSize);
            page = info.page;
            const visible = sorted.slice(info.start, info.end);
            const sortedColumn = COLUMN_BY_KEY[sort.key];
            const hasDagger = visible.some(r => isUncalibratedFlow(r.conditions.flow_cm_s));
            const hasAi = visible.some(anyAi);
            const pager = () => info.pages > 1 ? h("nav", { class: "pagination", "aria-label": "Table pages" },
                button("Previous", () => setPage(page - 1), { disabled: page <= 1 }),
                h("span", { class: "range" }, "Page " + FF.formatNumber(page) + " of " + FF.formatNumber(info.pages)),
                button("Next", () => setPage(page + 1), { disabled: page >= info.pages })) : null;
            clear(container,
                h("p", { class: "status run-count", role: "status" },
                    "Rows " + FF.formatNumber(info.start + 1) + "–" + FF.formatNumber(info.end) + " of " +
                    FF.formatNumber(sorted.length) + " source rows, sorted by " + sortedColumn.title + " (" +
                    (sort.direction === "asc" ? "ascending" : "descending") + "; unknown values last)."),
                pager(),
                h("div", { class: "table-wrap" },
                    h("table", { class: "table runs-table" },
                        h("caption", { class: "visually-hidden" }, "Source rows with conditions, outcomes and review state"),
                        h("thead", {}, h("tr", {}, COLUMNS.map(headerCell), h("th", { scope: "col" }, "Record details"))),
                        h("tbody", {}, visible.map(row)))),
                pager(),
                h("div", { class: "run-legend small muted" },
                    h("p", {}, "A row is one row of a source table, not necessarily one experiment; the Kind column says what it records."),
                    hasAi ? h("p", {}, h("sup", { class: "ai-mark" }, "AI"), " Value proposed by a language model from source text; see the record for the quote and review state.") : null,
                    hasDagger ? h("p", {}, h("sup", { class: "dagger" }, "†"), " Flow is a raw instrument display reading, not a calibrated velocity.") : null));
            if (focusKey) {
                const target = Array.from(container.querySelectorAll("button")).find(node => node.dataset && node.dataset.sortKey === focusKey);
                if (target) target.focus();
                focusKey = null;
            }
        }
        draw();
    }

    // ---------- Detail dialog ----------
    let dialog = null, body = null, titleNode = null, opener = null, controller = null, current = null;

    function ensureDialog() {
        if (dialog) return;
        titleNode = h("h2", { id: "run-detail-title" }, "Source record");
        body = h("div", { class: "dialog-body" });
        dialog = h("dialog", { class: "dialog runs-dialog", "aria-labelledby": "run-detail-title" },
            h("div", { class: "dialog-head" }, titleNode,
                button("Close", () => dialog.close(), { class: "btn-quiet" })),
            body);
        dialog.addEventListener("close", () => {
            if (dialog.open) return; // Reopened before this asynchronous event fired: keep the new request.
            if (controller) controller.abort();
            if (opener && typeof opener.focus === "function") opener.focus();
            opener = null;
        });
        dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
        document.body.append(dialog);
    }

    const orEmpty = text => text === null || text === undefined || text === "" ? null : text;
    const methodTag = item => h("span", { class: "tag" + (isAi(item) ? " ai-tag" : "") }, label("method", item.method));
    const columnsText = item => (item.columns || []).length ? item.columns.join(", ") : h("span", { class: "muted" }, "—");
    function quoteCell(item) {
        const quote = orEmpty(item.quote);
        return quote === null ? h("span", { class: "muted" }, "—") : h("span", { class: "run-quote" }, quote);
    }
    function noteCell(item) {
        const parts = [];
        if (orEmpty(item.note)) parts.push(item.note);
        if (isQuantity(item)) {
            if (item.qualifier === "approximate") parts.push("Approximate value.");
            if (item.initial !== undefined && item.initial !== null) parts.push("Initial: " + FF.formatNumber(item.initial));
            if (item.final !== undefined && item.final !== null) parts.push("Final: " + FF.formatNumber(item.final));
        }
        return parts.length ? parts.join(" ") : h("span", { class: "muted" }, "—");
    }
    const CONDITION_ORDER = ["fuel_class", "material", "geometry", "flow_direction", "diluent", "o2_percent", "pressure_kpa", "flow_cm_s"];
    const CONDITION_LABEL = { fuel_class: "Fuel class", material: "Material", geometry: "Geometry", flow_direction: "Flow direction",
        diluent: "Diluent", o2_percent: "Oxygen", pressure_kpa: "Pressure", flow_cm_s: "Flow velocity" };
    function conditionValue(key, item) {
        if (isQuantity(item)) {
            return quantityCell(item, { unit: item.unit, uncalibrated: key === "flow_cm_s" });
        }
        const text = key === "fuel_class" ? label("fuelClass", categoryValue(item)) :
            key === "flow_direction" ? label("flowDirection", categoryValue(item)) : null;
        return categoryCell(item, text);
    }
    function conditionsTable(conditions) {
        const keys = [...CONDITION_ORDER.filter(key => key in conditions), ...Object.keys(conditions).filter(key => !CONDITION_ORDER.includes(key))];
        return h("div", { class: "table-wrap" }, h("table", { class: "table" },
            h("caption", { class: "visually-hidden" }, "Conditions"),
            h("thead", {}, h("tr", {}, ["Condition", "Value", "Unit", "Method", "Review", "Source columns", "Source text", "Note"].map(t => h("th", { scope: "col" }, t)))),
            h("tbody", {}, keys.map(key => {
                const item = conditions[key];
                return h("tr", {},
                    h("th", { scope: "row" }, CONDITION_LABEL[key] || key.replace(/_/g, " ")),
                    h("td", {}, conditionValue(key, item)),
                    h("td", {}, isQuantity(item) && item.unit ? item.unit : h("span", { class: "muted" }, "—")),
                    h("td", {}, methodTag(item)),
                    h("td", {}, FF.reviewBadge(item.review_status)),
                    h("td", {}, columnsText(item)),
                    h("td", {}, quoteCell(item)),
                    h("td", {}, noteCell(item)));
            }))));
    }
    function outcomesTable(outcomes) {
        return h("div", { class: "table-wrap" }, h("table", { class: "table" },
            h("caption", { class: "visually-hidden" }, "Outcomes"),
            h("thead", {}, h("tr", {}, ["Outcome", "Gravity", "Result", "Method", "Review", "Source columns", "Source text", "Note"].map(t => h("th", { scope: "col" }, t)))),
            h("tbody", {}, outcomes.map(outcome => {
                const result = outcome.result || {};
                return h("tr", {},
                    h("th", { scope: "row" }, label("outcome", outcome.type)),
                    h("td", {}, gravityLabel(outcome.gravity)),
                    h("td", {}, resultIsUnknown(result) ? unknownNode() : h("span", { class: "num" }, resultText(result), isAi(result) ? aiMark() : null)),
                    h("td", {}, methodTag(result)),
                    h("td", {}, FF.reviewBadge(result.review_status)),
                    h("td", {}, columnsText(result)),
                    h("td", {}, quoteCell(result)),
                    h("td", {}, noteCell(result)));
            }))));
    }
    function originalList(original, columns) {
        const keys = [...(columns || []).filter(key => key in original), ...Object.keys(original).filter(key => !(columns || []).includes(key))];
        return h("dl", { class: "meta-list run-original" }, keys.map(key => [
            h("dt", {}, key),
            h("dd", {}, original[key] === "" ? h("span", { class: "unknown" }, "(empty)") : h("span", { class: "run-cell" }, original[key])),
        ]));
    }
    function linkItem(link, closeDialog) {
        const target = link.target || {};
        const accession = target.accession;
        return h("li", { class: "run-link" },
            h("div", {}, target.kind === "file"
                ? h("a", { href: FF.buildHash("files", [accession], { filename: target.filename }), onclick: closeDialog }, target.filename)
                : h("span", { class: "id" }, target.passage_id || "passage")),
            target.key ? h("div", { class: "small muted" }, "Key: ", h("span", { class: "id" }, target.key),
                target.version !== undefined ? " · version " + target.version : "") : null,
            h("div", { class: "small" }, "Basis: " + link.basis),
            accession ? h("div", { class: "small" },
                h("a", { href: FF.buildHash("study", [accession]), onclick: closeDialog }, "Investigation " + accession), " · ",
                FF.externalLink("PSI page", FF.PSI_INVESTIGATION_URL + accession)) : null);
    }
    function linksSection(links, closeDialog) {
        if (!links.length) return h("p", { class: "muted" }, "No linked files are recorded for this row.");
        const confirmed = links.filter(link => link.status === "confirmed");
        const ambiguous = links.filter(link => link.status !== "confirmed");
        return h("div", {},
            confirmed.length ? h("div", {}, h("h4", {}, "Confirmed (" + confirmed.length + ")"),
                h("ul", { class: "run-links" }, confirmed.map(link => linkItem(link, closeDialog)))) : h("p", { class: "muted" }, "No confirmed links."),
            ambiguous.length ? h("div", { class: "notice notice-warn" },
                h("h4", {}, "Ambiguous candidates (not confirmed) (" + ambiguous.length + ")"),
                h("p", {}, "These files share some identifiers with the row but do not establish that they belong to this test."),
                h("ul", { class: "run-links" }, ambiguous.map(link => linkItem(link, closeDialog)))) : null);
    }

    // Builds the full record view. Exposed for tests.
    function buildDetail(data, meta, closeDialog = () => {}) {
        const parsed = parseId(data.id);
        const info = (meta && meta.source) || {};
        const source = info.source || {};
        const section = (title, ...children) => h("section", { class: "section run-section" }, h("h3", {}, title), children);
        const copy = button("Copy record ID", () => {
            const done = () => status(copyStatus, "Copied " + data.id + ".");
            try {
                const result = navigator.clipboard.writeText(data.id);
                if (result && result.then) result.then(done, () => status(copyStatus, "Copy failed; select the ID manually.", "error")); else done();
            } catch { status(copyStatus, "Copy failed; select the ID manually.", "error"); }
        });
        const copyStatus = h("span", { class: "status", role: "status" });
        const raw = button("Download record JSON", () => FF.download(data.id.replace(/[:]/g, "_") + ".json",
            JSON.stringify({ data, meta }, null, 2), "application/json"));
        const flags = data.flags || [];
        return h("div", { class: "run-detail" },
            h("div", { class: "cluster" },
                h("span", { class: "id run-detail-id" }, data.id),
                h("span", { class: "tag" }, label("kind", data.kind)),
                FF.reviewBadge(data.review_status)),
            meta && meta.provisional ? h("div", { class: "notice notice-warn" }, h("p", {},
                "Provisional: this table is not yet fully reviewed. Counts and classification may change.")) : null,
            h("p", { class: "small muted" }, "A record is one row of a source table, not necessarily one experiment. The kind (run, range, session summary, note) says what the row records."),
            section("Source",
                h("dl", { class: "meta-list" },
                    h("dt", {}, "Investigation"), h("dd", {}, h("a", { href: FF.buildHash("study", [parsed.accession]), onclick: closeDialog }, parsed.accession)),
                    h("dt", {}, "Table"), h("dd", {}, h("span", { class: "id" }, info.table || parsed.table)),
                    h("dt", {}, "Source file"), h("dd", {}, source.filename || h("span", { class: "unknown" }, "Not recorded")),
                    h("dt", {}, "Row"), h("dd", {}, String(data.row)),
                    h("dt", {}, "File SHA-256"), h("dd", {}, source.sha256
                        ? h("span", { class: "id", title: source.sha256 }, source.sha256.slice(0, 12) + "…") : h("span", { class: "unknown" }, "Not recorded")),
                    h("dt", {}, "Encoding"), h("dd", {}, source.encoding || h("span", { class: "unknown" }, "Not recorded")))),
            section("Conditions", conditionsTable(data.conditions || {})),
            section("Outcomes", (data.outcomes || []).length ? outcomesTable(data.outcomes)
                : h("p", { class: "unknown" }, "No outcomes recorded for this row.")),
            section("Original row", h("p", { class: "small muted" }, "Cells exactly as in the source file; whitespace preserved."),
                originalList(data.original || {}, source.columns)),
            section("Flags", flags.length
                ? h("ul", { class: "run-flags" }, flags.map(flag => h("li", {}, h("strong", {}, label("flag", flag.code)), ": " + flag.detail,
                    (flag.columns || []).length ? h("span", { class: "muted small" }, " (columns: " + flag.columns.join(", ") + ")") : null)))
                : h("p", { class: "muted" }, "No data-quality flags.")),
            section("Links to files", linksSection(data.links || [], closeDialog)),
            h("div", { class: "cluster run-actions" }, copy, raw, copyStatus));
    }

    async function openDetail(runId) {
        ensureDialog();
        if (controller) controller.abort();
        controller = new AbortController();
        const mine = controller;
        current = runId;
        if (!dialog.open) {
            opener = document.activeElement || null;
            dialog.showModal();
        }
        titleNode.textContent = "Source record";
        clear(body, status(h("p"), "Loading " + runId + "…", "loading"));
        try {
            const result = await FF.api("/api/runs/" + FF.encodeId(runId), { signal: mine.signal });
            if (mine.signal.aborted || current !== runId) return;
            titleNode.textContent = "Source record " + result.data.id;
            clear(body, buildDetail(result.data, result.meta, () => dialog.close()));
        } catch (error) {
            if (error.name === "AbortError" || mine.signal.aborted) return;
            const text = error.status === 404 ? "Record " + runId + " was not found in the prepared data."
                : error.status === 503 ? error.message + " The run tables have not been prepared."
                : error.message || "The record could not be loaded.";
            clear(body, status(h("p"), text, "error"), button("Close", () => dialog.close()));
        }
    }

    // ---------- CSV ----------
    const CSV_HEADER = ["id", "investigation", "table", "source_file", "row", "kind", "review_status", "fuel_class", "material",
        "material_source_text", "geometry", "flow_direction", "diluent", "o2_percent_min", "o2_percent_max", "o2_method",
        "pressure_kpa_min", "pressure_kpa_max", "pressure_method", "flow_cm_s_min", "flow_cm_s_max", "flow_method", "flow_note",
        "outcomes", "any_ai_extracted", "flags"];
    const bound = (q, side) => isKnownQuantity(q) ? q[side] : "";
    const cat = item => categoryValue(item) === null ? "" : categoryValue(item);
    function csv(records, sources) {
        const map = sourceMap(sources);
        const rows = records.map(record => {
            const c = record.conditions || {};
            const parsed = parseId(record.id);
            const source = sourceFor(map, record);
            const outcomes = (record.outcomes || []).map(outcome =>
                outcome.type + " [" + (outcome.gravity || "unknown") + "]: " +
                (resultIsUnknown(outcome.result) ? "unknown" : resultText(outcome.result))).join("; ");
            return [record.id, parsed.accession, parsed.table, source ? source.filename : "", parsed.row, record.kind, record.review_status,
                cat(c.fuel_class), cat(c.material), c.material && c.material.quote ? c.material.quote : "",
                cat(c.geometry), cat(c.flow_direction), cat(c.diluent),
                bound(c.o2_percent, "min"), bound(c.o2_percent, "max"), c.o2_percent ? c.o2_percent.method : "unknown",
                bound(c.pressure_kpa, "min"), bound(c.pressure_kpa, "max"), c.pressure_kpa ? c.pressure_kpa.method : "unknown",
                bound(c.flow_cm_s, "min"), bound(c.flow_cm_s, "max"), c.flow_cm_s ? c.flow_cm_s.method : "unknown",
                c.flow_cm_s && c.flow_cm_s.note ? c.flow_cm_s.note : "",
                outcomes, anyAi(record) ? "true" : "false", (record.flags || []).map(flag => flag.code).join(";")];
        });
        return FF.toCsv(CSV_HEADER, rows);
    }

    FF.runs = { renderTable, openDetail, csv, sortRecords, pageInfo, buildDetail, isUncalibratedFlow, parseId, resultText, gravityLabel, COLUMNS };
})(window);
