// Two-investigation comparison (#/compare, #/compare/A, #/compare/A/B).
// A side-by-side reading of each card's own cited statements. Nothing is merged, paraphrased,
// normalised or differenced (decision D3): statements are shown exactly as stored.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, status } = FF;

    const NOT_STATED = "Not stated in this card";
    const COMPARISON_KEYS = ["fuels", "geometry", "oxygen", "pressure", "flow", "gravity"];

    // ---------- Pure row model ----------
    // An item is one statement: { parts: [{ label?, text, ids }], tag?, links? }.
    function part(text, ids, label) {
        return { text: String(text), ids: Array.isArray(ids) ? ids : [], label };
    }
    function statementItems(list) {
        return (list || []).filter(entry => entry && entry.text).map(entry => ({ parts: [part(entry.text, entry.evidence_ids)] }));
    }
    function claimsOf(card, ...types) {
        return statementItems((card.claims || []).filter(claim => types.includes(claim.type)));
    }
    function basename(key) {
        const text = String(key || "");
        return text.slice(text.lastIndexOf("/") + 1);
    }
    function comparisonItems(card, key) {
        const entry = card.comparison && card.comparison[key];
        return entry && entry.text ? [{ parts: [part(entry.text, entry.evidence_ids)] }] : [];
    }
    function findingItems(card) {
        const byId = new Map((card.claims || []).map(claim => [claim.id, claim]));
        return (card.findings || []).map(finding => {
            const parts = [];
            const observation = byId.get(finding.observation);
            const implication = byId.get(finding.implication);
            if (observation) parts.push(part(observation.text, observation.evidence_ids, "Observation"));
            if (finding.conditions && finding.conditions.text) {
                parts.push(part(finding.conditions.text, finding.conditions.evidence_ids, "Conditions"));
            }
            if (implication) parts.push(part(implication.text, implication.evidence_ids, "Implication"));
            return parts.length ? { parts, tag: finding.category ? FF.label("category", finding.category) : null } : null;
        }).filter(Boolean);
    }

    // Row definitions in display order. `get(card)` returns an array of items (empty = not stated).
    const ROWS = [
        { group: "Overview", label: "Summary", get: card => card.summary && card.summary.text
            ? [{ parts: [part(card.summary.text, card.summary.evidence_ids)] }] : [] },
        { group: "Overview", label: "Safety categories", get: card => (card.safety_categories || []).map(entry =>
            ({ parts: [part(FF.label("category", entry.category), entry.evidence_ids)] })) },
        { group: "Aims", groupNote: "Stated aims, not results.", label: "Objectives", get: card => claimsOf(card, "objective") },
        { group: "Aims", label: "Approach", get: card => claimsOf(card, "approach") },
        { group: "Aims", label: "Hypotheses", get: card => claimsOf(card, "hypothesis") },
        { group: "Results", groupNote: "Reported observations are quoted from the cited sources; expected impact is a stated expectation.",
            label: "Reported observations", get: card => claimsOf(card, "reported_observation") },
        { group: "Results", label: "Findings", note: "Observation, then conditions, then implication.", get: findingItems },
        { group: "Results", label: "Expected impact / potential application",
            note: "Stated expectation, not a result.", get: card => claimsOf(card, "expected_impact", "potential_application") },
        ...COMPARISON_KEYS.map(key => ({ group: "Experimental conditions", label: FF.label("comparison", key),
            get: card => comparisonItems(card, key) })),
        { group: "Methods", label: FF.label("comparison", "measurements"), get: card => comparisonItems(card, "measurements") },
        { group: "Methods", label: FF.label("comparison", "hardware"), get: card => comparisonItems(card, "hardware") },
        { group: "Limitations", label: "Limitations", get: card => (card.limitations || []).filter(entry => entry && entry.text).map(entry => ({
            parts: [part(entry.text, entry.evidence_ids)],
            tag: entry.basis ? FF.label("limitationBasis", entry.basis) : null })) },
        { group: "Modeling resources", label: "Modeling resources", get: card => (card.modeling_resources || []).map(entry => ({
            parts: [part(entry.description || "", entry.evidence_ids)], files: entry.file_keys || [] })) },
    ];

    function itemText(item) {
        const text = item.parts.map(entry => entry.label ? entry.label + ": " + entry.text : entry.text).join(" → ");
        return item.files && item.files.length ? text + " [files: " + item.files.join("; ") + "]" : text;
    }
    function itemIds(items) {
        const seen = new Set();
        for (const item of items) for (const entry of item.parts) for (const id of entry.ids) seen.add(id);
        return [...seen];
    }
    // columns: [{accession, card|null, error|null}] → [{group, groupNote, label, note, cells: [items[]|null]}]
    function buildRows(columns) {
        return ROWS.map(row => ({ group: row.group, groupNote: row.groupNote, label: row.label, note: row.note,
            cells: columns.map(column => column.card ? row.get(column.card) : null) }));
    }
    function csv(columns) {
        const header = ["Group", "Attribute"];
        for (const column of columns) header.push(column.accession + " statement", column.accession + " evidence IDs");
        const rows = buildRows(columns).map(row => {
            const out = [row.group, row.label];
            row.cells.forEach((items, index) => {
                if (items === null) out.push("Not available: " + (columns[index].error || "card not loaded"), "");
                else out.push(items.length ? items.map(itemText).join("\n") : NOT_STATED, itemIds(items).join("; "));
            });
            return out;
        });
        return FF.toCsv(header, rows);
    }

    // ---------- Rendering ----------
    function cites(accession, ids, context) {
        if (!ids.length) return null;
        if (FF.evidence && typeof FF.evidence.citeMarkers === "function") {
            try { return FF.evidence.citeMarkers(accession, ids, context); } catch { /* fall through */ }
        }
        return h("span", { class: "muted small" }, " " + ids.length + (ids.length === 1 ? " source" : " sources"));
    }
    function renderItems(accession, items, context) {
        if (!items.length) return h("span", { class: "unknown" }, NOT_STATED);
        return h("div", { class: "cmp-items" }, items.map(item => h("div", { class: "cmp-item" },
            item.tag ? h("span", { class: "tag" }, item.tag) : null,
            item.parts.map(entry => h("p", { class: "cmp-part" },
                entry.label ? h("span", { class: "cmp-part-label" }, entry.label + ": ") : null,
                entry.text, cites(accession, entry.ids, context))),
            item.files && item.files.length ? h("ul", { class: "cmp-files" }, item.files.map(key => h("li", {},
                h("a", { href: FF.buildHash("files", [accession], { filename: basename(key) }), title: key }, basename(key))))) : null)));
    }

    function columnLabel(column) {
        return column.accession + (column.card ? " · " + column.card.title : "");
    }
    function headerCell(column) {
        const card = column.card;
        const th = h("th", { scope: "col", class: "cmp-col", "data-label": column.accession });
        if (!card) {
            th.append(h("span", { class: "id" }, column.accession), h("p", { class: "error small" }, column.error));
            return th;
        }
        th.append(
            h("div", { class: "cmp-title" }, card.acronym ? card.acronym + " — " + card.title : card.title),
            h("div", { class: "cmp-meta small" }, h("span", { class: "id" }, card.accession),
                " · v" + card.source_version, " · ", FF.reviewBadge(card.review && card.review.status)),
            h("div", { class: "cmp-meta small muted" }, FF.label("coverage", card.coverage)),
            h("a", { class: "small", href: FF.buildHash("study", [card.accession]) }, "Open investigation"));
        return th;
    }

    function renderTable(columns) {
        const rows = buildRows(columns);
        const body = h("tbody");
        let group = null;
        for (const row of rows) {
            if (row.group !== group) {
                group = row.group;
                const th = h("th", { colspan: String(columns.length + 1), scope: "colgroup" }, group);
                if (row.groupNote) th.append(h("span", { class: "cmp-group-note" }, " " + row.groupNote));
                body.append(h("tr", { class: "cmp-group" }, th));
            }
            const tr = h("tr", {}, h("th", { scope: "row", class: "cmp-attr" }, row.label,
                row.note ? h("div", { class: "small muted cmp-note" }, row.note) : null));
            row.cells.forEach((items, index) => {
                const column = columns[index];
                tr.append(h("td", { "data-label": columnLabel(column) },
                    items === null ? h("span", { class: "error small" }, "Not available: " + (column.error || "card not loaded"))
                        : renderItems(column.accession, items, row.label)));
            });
            body.append(tr);
        }
        const head = h("tr", {}, h("th", { scope: "col", class: "cmp-corner" }, "Attribute"), columns.map(headerCell));
        return h("div", { class: "table-wrap cmp-wrap" }, h("table", { class: "table cmp-table" },
            h("caption", { class: "visually-hidden" }, "Side-by-side statements from two research cards"),
            h("thead", {}, head), body));
    }

    function notice() {
        return h("div", { class: "notice cmp-notice" },
            h("p", {}, "This is a side-by-side reading of each card's cited statements. Statements are shown as written; units and wording are not normalised and no differences are computed."),
            h("p", {}, "A quantitative comparison of runs requires known and equal fuel class, material, geometry, flow direction and hardware. If the statements here differ, no conclusion should be drawn from them. See ",
                h("a", { href: "#/conditions" }, "run-level condition groups"), "."));
    }

    // ---------- View ----------
    let controller = null;

    function optionLabel(study) { return study.accession + " · " + FF.studyLabel(study); }

    function mount(container, route) {
        if (controller) controller.abort();
        controller = new AbortController();
        const signal = controller.signal;
        const [a, b] = [route.args[0] || "", route.args[1] || ""];
        const go = (first, second) => FF.navigate("compare", [first, second].filter(Boolean));

        const selects = ["A", "B"].map((name, index) => {
            const select = h("select", { id: "cmp-select-" + name.toLowerCase() },
                h("option", { value: "" }, "Select an investigation"));
            select.addEventListener("change", () => {
                const values = [selectA.value, selectB.value];
                values[index] = select.value;
                go(values[0], values[1]);
            });
            return select;
        });
        const [selectA, selectB] = selects;
        const swap = FF.button("Swap", () => go(selectB.value, selectA.value), { disabled: !(a && b) });
        const fields = h("form", { class: "filters cmp-controls", onsubmit: event => event.preventDefault() },
            h("div", { class: "field-row" },
                h("div", { class: "field" }, h("label", { for: "cmp-select-a" }, "Investigation A"), selectA),
                h("div", { class: "field cmp-swap" }, swap),
                h("div", { class: "field" }, h("label", { for: "cmp-select-b" }, "Investigation B"), selectB)));
        const output = h("div", { class: "cmp-output" });
        const exportBar = h("div", { class: "cluster no-print" });

        clear(container,
            h("header", { class: "page-head" }, h("h1", {}, "Compare investigations"),
                h("p", { class: "lede" }, "Read the cited statements of two research cards side by side.")),
            fields, output);

        // Fill the selects once the index is known; selection comes from the URL.
        FF.studyIndex().then(index => {
            if (signal.aborted) return;
            for (const [select, chosen] of [[selectA, a], [selectB, b]]) {
                const known = new Set(index.map(study => study.accession));
                for (const study of index) select.append(h("option", { value: study.accession }, optionLabel(study)));
                if (chosen && !known.has(chosen)) select.append(h("option", { value: chosen }, chosen));
                select.value = chosen;
            }
        }).catch(error => {
            if (signal.aborted) return;
            for (const [select, chosen] of [[selectA, a], [selectB, b]]) {
                if (chosen) select.append(h("option", { value: chosen }, chosen));
                select.value = chosen;
            }
            clear(output, h("p", { class: "error small", role: "alert" }, "The investigation list could not be loaded: " + error.message));
        });

        if (!a || !b) {
            output.append(h("p", { class: "empty" }, a
                ? "Choose a second investigation to compare with " + a + "."
                : "Choose two investigations to compare."));
            return;
        }
        if (a === b) {
            output.append(h("p", { class: "empty", role: "status" },
                "The same investigation (" + a + ") is selected twice. Choose two different investigations."));
            return;
        }

        const state = h("p", { class: "status" });
        status(state, "Loading both research cards…", "loading");
        output.append(state);
        const load = accession => FF.api("/api/studies/" + FF.encodeId(accession), { signal })
            .then(result => ({ accession, card: result.data, error: null }),
                error => {
                    if (error.name === "AbortError") throw error;
                    return { accession, card: null,
                        error: error.status === 404 ? "No investigation " + accession + " in this dataset." : error.message };
                });
        Promise.all([load(a), load(b)]).then(columns => {
            if (signal.aborted) return;
            const failed = columns.filter(column => !column.card);
            const download = FF.button("Download comparison (CSV)", () => {
                FF.download("compare_" + a + "_" + b + ".csv", csv(columns), "text/csv");
            }, { disabled: failed.length === columns.length });
            exportBar.append(download);
            clear(output, notice(),
                failed.map(column => h("p", { class: "error", role: "alert" }, column.accession + ": " + column.error)),
                failed.length === columns.length ? null : [exportBar, renderTable(columns)]);
        }).catch(error => {
            if (error.name === "AbortError") return;
            status(state, error.message, "error");
        });
    }

    function unmount() {
        if (controller) controller.abort();
        controller = null;
    }

    FF.compare = { ROWS, buildRows, csv, itemText, NOT_STATED, basename };
    FF.views.compare = { mount, unmount };
})(typeof window !== "undefined" ? window : globalThis);
