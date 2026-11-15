// Condition explorer: filters, coverage summary, O2-pressure map, condition groups, runs table, export.
// Route: #/conditions?<API filter names>&p_unit=&sort=&run=
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, status } = FF;
    const SVG_NS = "http://www.w3.org/2000/svg";

    // ---------- Constants ----------
    const CATEGORY_KEYS = ["fuel_class", "material", "geometry", "flow_direction"];
    const API_KEYS = ["fuel_class", "material", "geometry", "flow_direction", "o2_min", "o2_max",
        "pressure_min", "pressure_max", "flow_min", "flow_max", "outcome"];
    const URL_KEYS = [...API_KEYS, "p_unit", "sort", "run"];
    const RANGES = [
        { name: "o2", label: "Oxygen (% by volume)", short: "O2", unit: "%", max: 100 },
        { name: "pressure", label: "Pressure", short: "Pressure", unit: null },
        { name: "flow", label: "Flow (cm/s)", short: "Flow", unit: "cm/s" },
    ];
    const FACTORS = { kPa: 1, atm: FF.KPA_PER_ATM, psia: FF.KPA_PER_PSI };
    const ENUMS = {
        fuel_class: FF.LABELS.fuelClass, flow_direction: FF.LABELS.flowDirection, outcome: FF.LABELS.outcome,
    };
    const REFERENCE_ATMOSPHERES = [
        { psia: 14.7, o2: 21 }, { psia: 10.2, o2: 26.5 }, { psia: 8.2, o2: 34 },
    ].map(item => Object.assign(item, { kpa: item.psia * FF.KPA_PER_PSI }));
    const QUALITY_FLAGS = ["invalid_reading", "inconsistent_values", "suspected_typo", "references_other_rows"];
    const FILLED_REVIEW = ["approved", "reviewed", "not_required"];
    const GAP_TEXT = "Not in PSI: no record in the saved PSI snapshot covers these filters and ranges. " +
        "This does not establish whether the scenario was studied elsewhere, whether it is safe, or what would happen. " +
        "Saffire-IV–VI and SoFIE results outside PSI are not verified here.";
    const STATUS = {
        covered: ["Covered", "Reviewed runs in the saved PSI tables match these filters."],
        pending_review: ["Pending review", "Matching records exist but rely on records pending review, or pending or unknown context prevents a definite answer."],
        unknown_conditions: ["Unknown conditions", "Matching records lack the condition values needed to give a definite answer."],
        not_in_PSI: ["Not in PSI", "No record in the saved PSI snapshot covers these filters and ranges."],
    };
    const COUNT_ROWS = [
        ["source_records", "Source rows (not individual experiments)"],
        ["distinct_run_records", "Distinct run records"],
        ["run_records", "Run records"],
        ["range_records", "Range records"],
        ["session_records", "Session records"],
        ["note_records", "Note records"],
        ["duplicate_rows", "Duplicate rows"],
        ["excluded_quality_records", "Excluded for quality"],
        ["pending_review_records", "Pending review"],
        ["unknown_condition_records", "With an unknown condition"],
        ["verified_run_count", "Reviewed (verified) runs"],
    ];

    // ---------- Pure logic: URL parameters <-> API query ----------
    function pressureUnit(params) { return FACTORS[params.p_unit] ? params.p_unit : "kPa"; }

    // Validate URL/form parameters the way the API does. Invalid fields are left out of `query`
    // and reported in `errors` (keyed by field group: o2, pressure, flow, or the categorical name).
    function buildQuery(params) {
        const query = {}, errors = {};
        const unit = pressureUnit(params);
        for (const key of CATEGORY_KEYS.concat("outcome")) {
            const value = (params[key] || "").trim();
            if (!value) continue;
            if (ENUMS[key] && !(value in ENUMS[key])) errors[key] = "Unknown value.";
            else query[key] = value;
        }
        for (const range of RANGES) {
            const bounds = {};
            for (const side of ["min", "max"]) {
                const raw = (params[range.name + "_" + side] || "").trim();
                if (!raw) continue;
                const number = Number(raw);
                if (!Number.isFinite(number)) { errors[range.name] = "Enter numbers only."; continue; }
                if (number < 0) { errors[range.name] = "Values must be 0 or greater."; continue; }
                if (range.max !== undefined && number > range.max) {
                    errors[range.name] = "Oxygen cannot exceed " + range.max + "%."; continue;
                }
                const factor = range.name === "pressure" ? FACTORS[unit] : 1;
                bounds[side] = Number((number * factor).toPrecision(12));
            }
            if (!errors[range.name] && "min" in bounds && "max" in bounds && bounds.min > bounds.max) {
                errors[range.name] = "Minimum is larger than maximum.";
            }
            if (errors[range.name]) continue;
            for (const side of Object.keys(bounds)) query[range.name + "_" + side] = bounds[side];
        }
        // Stable key order so equal filter sets give equal query strings.
        const ordered = {};
        for (const key of API_KEYS) if (key in query) ordered[key] = query[key];
        return { query: ordered, errors, unit };
    }
    function queryString(query) { return new URLSearchParams(query).toString(); }

    // Only keep recognised, non-empty URL parameters.
    function cleanParams(params) {
        const out = {};
        for (const key of URL_KEYS) {
            const value = params[key];
            if (value !== undefined && value !== null && String(value).trim() !== "") out[key] = String(value).trim();
        }
        if (out.p_unit === "kPa") delete out.p_unit;
        return out;
    }

    function filterSlug(query) {
        const parts = [];
        for (const key of ["fuel_class", "material", "geometry", "flow_direction", "outcome"]) {
            if (query[key]) parts.push(query[key]);
        }
        for (const key of ["o2_min", "o2_max", "pressure_min", "pressure_max", "flow_min", "flow_max"]) {
            if (key in query) parts.push(key.replace("_min", "-ge").replace("_max", "-le") + query[key]);
        }
        return parts.join("_").replace(/[^A-Za-z0-9._-]+/g, "-").slice(0, 80) || "all";
    }

    // ---------- Pure logic: filter options from condition groups ----------
    // Options for one categorical field, narrowed by the other selected categorical values.
    function optionsFromGroups(groups, field, selected) {
        const narrowing = {
            fuel_class: [], material: ["fuel_class"], geometry: ["fuel_class", "material"],
            flow_direction: ["fuel_class", "material", "geometry"],
        }[field] || [];
        const counts = new Map();
        for (const group of groups || []) {
            const conditions = group.conditions || {};
            if (narrowing.some(other => selected[other] && conditions[other] !== selected[other])) continue;
            const value = conditions[field];
            if (value === null || value === undefined || value === "") continue;
            counts.set(value, (counts.get(value) || 0) + (group.run_record_count || 0));
        }
        if (selected[field] && !counts.has(selected[field])) counts.set(selected[field], 0);
        return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))
            .map(([value, count]) => ({ value, count }));
    }

    // ---------- Pure logic: map model ----------
    function recordCodes(record) { return (record.flags || []).map(flag => flag.code); }
    function plotModel(records) {
        const model = { marks: [], total: records.length, plotted: 0, unknown: 0, intervals: 0, excluded: 0 };
        const byKey = new Map();
        for (const record of records) {
            const codes = recordCodes(record);
            if ((record.kind !== "run" && record.kind !== "range") || codes.includes("duplicate_row") ||
                codes.some(code => QUALITY_FLAGS.includes(code))) { model.excluded += 1; continue; }
            const o2 = record.conditions && record.conditions.o2_percent;
            const pressure = record.conditions && record.conditions.pressure_kpa;
            if (!FF.isKnownQuantity(o2, "percent") || !FF.isKnownQuantity(pressure, "kPa")) {
                model.unknown += 1; continue;
            }
            if (o2.min < 0 || o2.max > 100 || pressure.min < 0) { model.excluded += 1; continue; }
            const filled = FILLED_REVIEW.includes(record.review_status);
            const key = [o2.min, o2.max, pressure.min, pressure.max, filled].join("|");
            let mark = byKey.get(key);
            if (!mark) {
                mark = { key, o2: [o2.min, o2.max], pressure: [pressure.min, pressure.max], filled, ids: [],
                    interval: o2.min !== o2.max || pressure.min !== pressure.max };
                byKey.set(key, mark);
                model.marks.push(mark);
            }
            mark.ids.push(record.id);
            model.plotted += 1;
            if (mark.interval) model.intervals += 1;
        }
        return model;
    }

    function niceStep(raw) {
        const exponent = Math.floor(Math.log10(raw));
        const fraction = raw / Math.pow(10, exponent);
        const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
        return nice * Math.pow(10, exponent);
    }
    function niceAxis(low, high, target) {
        if (!(high > low)) { const pad = Math.max(Math.abs(low) * 0.1, 1); low -= pad; high += pad; }
        const step = niceStep((high - low) / (target || 6));
        const start = Math.floor(low / step + 1e-9) * step, end = Math.ceil(high / step - 1e-9) * step;
        const ticks = [];
        for (let i = 0; start + i * step <= end + step * 1e-6; i += 1) ticks.push(Number((start + i * step).toPrecision(12)));
        return { lo: start, hi: end, step, ticks };
    }
    // Axis extents from plotted data, reference atmospheres and the active filter window.
    function axisModel(model, query) {
        const xs = [], ys = [];
        for (const mark of model.marks) { xs.push(...mark.o2); ys.push(...mark.pressure); }
        for (const ref of REFERENCE_ATMOSPHERES) { xs.push(ref.o2); ys.push(ref.kpa); }
        for (const key of ["o2_min", "o2_max"]) if (key in query) xs.push(query[key]);
        for (const key of ["pressure_min", "pressure_max"]) if (key in query) ys.push(query[key]);
        const pad = (values, floor) => {
            const lo = Math.min(...values), hi = Math.max(...values);
            const margin = Math.max((hi - lo) * 0.06, floor);
            return [lo - margin, hi + margin];
        };
        const [xl, xh] = pad(xs, 1), [yl, yh] = pad(ys, 5);
        const x = niceAxis(xl, xh, 6), y = niceAxis(yl, yh, 6);
        if (x.lo < 0) { x.lo = 0; x.ticks = x.ticks.filter(t => t >= 0); }
        if (x.hi > 100) { x.hi = 100; x.ticks = x.ticks.filter(t => t <= 100); }
        if (y.lo < 0) { y.lo = 0; y.ticks = y.ticks.filter(t => t >= 0); }
        const atm = niceAxis(y.lo / FF.KPA_PER_ATM, y.hi / FF.KPA_PER_ATM, 5);
        y.atmTicks = atm.ticks.filter(t => t * FF.KPA_PER_ATM >= y.lo - 1e-9 && t * FF.KPA_PER_ATM <= y.hi + 1e-9);
        return { x, y };
    }

    function statusInfo(coverage, meta) {
        const data = coverage && coverage.data || {};
        const counts = data.counts || {};
        const value = data.coverage_status;
        const info = STATUS[value] || null;
        const empty = counts.source_records === 0;
        return {
            value, label: info ? info[0] : "Not available", text: info ? info[1] : "Coverage status was not returned for these filters.",
            gap: value === "not_in_PSI",
            emptyPending: empty && value !== "not_in_PSI" && Boolean(info),
            provisional: Boolean(meta && meta.provisional),
        };
    }

    function buildExport(state) {
        const health = FF.cache.health || {};
        return {
            exported_at: new Date().toISOString(),
            snapshot_date: health.snapshot_date || null,
            filters: state.query,
            api: { runs_meta: state.runs.meta, coverage: { data: state.coverage.data, meta: state.coverage.meta } },
            records: state.runs.data,
        };
    }

    // ---------- Small DOM helpers ----------
    function svg(tag, attributes, ...children) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [key, value] of Object.entries(attributes || {})) {
            if (value === null || value === undefined || value === false) continue;
            if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
            else node.setAttribute(key, String(value));
        }
        for (const child of children.flat()) {
            if (child === null || child === undefined) continue;
            node.append(typeof child === "string" ? child : child);
        }
        return node;
    }
    function num(value) { return FF.formatNumber(value, 4); }
    function span(value) { return value[0] === value[1] ? num(value[0]) : num(value[0]) + "–" + num(value[1]); }

    // ---------- View ----------
    let groupsPromise = null;
    function unfilteredGroups() {
        if (!groupsPromise) {
            groupsPromise = withRetry(() => FF.api("/api/coverage")).then(result => result.data.groups || []).catch(error => {
                groupsPromise = null; throw error;
            });
        }
        return groupsPromise;
    }

    // On narrow screens the filters start collapsed so the coverage summary and map are visible first.
    // On wide screens the panel is always open and its toggle is hidden (conditions.css).
    function filtersPanel(form) {
        const wide = typeof global.matchMedia !== "function" || global.matchMedia("(min-width: 60rem)").matches;
        return h("details", { class: "cond-filters", open: wide },
            h("summary", {}, "Filters"), form);
    }
    function mount(container, route) {
        const state = {
            container, params: cleanParams(route.params), query: {}, queryKey: null, controller: null,
            coverage: null, runs: null, groups: null, openedRun: null, selectedGroup: null,
            controls: {}, resize: null, alive: true, picked: null,
        };
        FF.conditions.current = state;
        state.regions = {};
        const region = (name, node) => { state.regions[name] = node; return node; };

        const form = buildForm(state);
        const main = h("div", { class: "cond-main" },
            region("status", h("div", { class: "cond-status", role: "status", "aria-live": "polite" })),
            region("summary", h("section", { class: "section cond-summary", "aria-labelledby": "cond-summary-h" })),
            region("map", h("section", { class: "section cond-map-section", "aria-labelledby": "cond-map-h" })),
            region("groups", h("section", { class: "section cond-groups" })),
            region("table", h("section", { class: "section cond-table-section", "aria-labelledby": "cond-table-h" })));
        clear(container,
            h("header", { class: "page-head" },
                h("h1", {}, "Condition explorer"),
                h("p", { class: "lede" }, "Which recorded runs in the saved PSI tables match an atmosphere, flow and material, and where the tables have gaps.")),
            h("div", { class: "layout-sidebar" }, filtersPanel(form), main));

        if (typeof global.ResizeObserver === "function") {
            let last = 0;
            state.observer = new global.ResizeObserver(entries => {
                const width = Math.round(entries[0].contentRect.width);
                if (Math.abs(width - last) > 4) { last = width; renderMap(state); }
            });
            state.observer.observe(state.regions.map);
        }
        unfilteredGroups().then(groups => { state.groups = groups; refreshOptions(state); })
            .catch(() => { refreshOptions(state); });
        syncForm(state);
        load(state);
    }

    function unmount() {
        const state = FF.conditions.current;
        if (!state) return;
        state.alive = false;
        if (state.controller) state.controller.abort();
        if (state.observer) state.observer.disconnect();
        FF.conditions.current = null;
    }

    function update(route) {
        const state = FF.conditions.current;
        if (!state) return;
        const previous = state.params;
        state.params = cleanParams(route.params);
        syncForm(state);
        const parsed = buildQuery(state.params);
        if (queryString(parsed.query) !== state.queryKey || state.error) { load(state); return; }
        if (previous.sort !== state.params.sort) renderTable(state);
        if (previous.p_unit !== state.params.p_unit) updateSentHint(state);
        openRunFromParams(state);
    }

    // ---------- Form ----------
    function buildForm(state) {
        const c = state.controls;
        const field = (id, label, control, hint) => h("div", { class: "field" },
            h("label", { for: id }, label), control, hint || null);
        const select = (key, label) => {
            c[key] = h("select", { id: "cond-" + key, name: key });
            c[key].addEventListener("change", () => { if (CATEGORY_KEYS.includes(key)) refreshOptions(state); });
            return field("cond-" + key, label, c[key]);
        };
        const range = rangeInfo => {
            const name = rangeInfo.name;
            c[name + "_min"] = h("input", { id: "cond-" + name + "_min", name: name + "_min", type: "text", inputmode: "decimal",
                autocomplete: "off", "aria-label": rangeInfo.short + " minimum" });
            c[name + "_max"] = h("input", { id: "cond-" + name + "_max", name: name + "_max", type: "text", inputmode: "decimal",
                autocomplete: "off", "aria-label": rangeInfo.short + " maximum" });
            for (const side of ["min", "max"]) c[name + "_" + side].addEventListener("input", () => updateSentHint(state));
            c["error_" + name] = h("p", { class: "error small cond-error", id: "cond-error-" + name });
            return h("fieldset", { class: "field", "aria-describedby": "cond-error-" + name },
                h("legend", {}, rangeInfo.name === "pressure" ? "Pressure" : rangeInfo.label),
                h("div", { class: "range-pair" }, c[name + "_min"], h("span", { "aria-hidden": "true" }, "to"), c[name + "_max"]),
                c["error_" + name]);
        };
        c.p_unit = h("select", { id: "cond-p_unit", name: "p_unit" },
            ...["kPa", "atm", "psia"].map(unit => h("option", { value: unit }, unit)));
        c.p_unit.addEventListener("change", () => convertPressure(state));
        c.sent = h("p", { class: "hint small muted", id: "cond-sent" });
        c.outcome = h("select", { id: "cond-outcome", name: "outcome" },
            h("option", { value: "" }, "Any outcome"),
            ...Object.entries(FF.LABELS.outcome).map(([value, label]) => h("option", { value }, label)));

        const form = h("form", { class: "filters", "aria-label": "Condition filters", novalidate: true },
            h("fieldset", { class: "stack" },
                h("legend", { class: "cond-legend" }, "Filter first by"),
                select("fuel_class", "Fuel class"), select("material", "Material"),
                select("geometry", "Geometry"), select("flow_direction", "Flow direction"),
                h("p", { class: "hint small muted", id: "cond-options-note" })),
            h("fieldset", { class: "stack" },
                h("legend", { class: "cond-legend" }, "Then narrow by"),
                range(RANGES[0]),
                h("div", { class: "field" }, h("label", { for: "cond-p_unit" }, "Pressure unit"), c.p_unit),
                range(RANGES[1]), c.sent,
                range(RANGES[2]),
                h("p", { class: "hint small muted" },
                    "BASS and BASS-II flows are instrument display readings; the record's flow note states whether a calibration was applied."),
                field("cond-outcome", "Outcome type", c.outcome),
                h("p", { class: "hint small muted" },
                    "A record matches a range when its recorded interval overlaps the requested bounds, endpoints included. Records with an unknown value never match a range."),
                h("p", { class: "hint small muted" },
                    "There is no gravity filter: gravity is recorded per outcome, and 1 g ground tests are paired with microgravity results.")),
            h("div", { class: "cluster" },
                h("button", { type: "submit", class: "btn btn-primary" }, "Apply"),
                h("button", { type: "button", class: "btn", onclick: () => go(state, {}) }, "Reset")));
        form.addEventListener("submit", event => { event.preventDefault(); applyForm(state); });
        return form;
    }

    function formValues(state) {
        const c = state.controls, values = {};
        for (const key of API_KEYS) values[key] = c[key] ? (c[key].value || "").trim() : "";
        values.p_unit = c.p_unit.value;
        return values;
    }
    function selectedCategories(state) {
        const out = {};
        for (const key of CATEGORY_KEYS) out[key] = state.controls[key].value || "";
        return out;
    }
    function refreshOptions(state) {
        for (let pass = 0; pass < 2; pass += 1) refreshOptionsOnce(state);
    }
    function refreshOptionsOnce(state) {
        const c = state.controls;
        const selected = selectedCategories(state);
        const have = Array.isArray(state.groups);
        for (const key of CATEGORY_KEYS) {
            let options = have ? optionsFromGroups(state.groups, key, selected) : (selected[key] ? [{ value: selected[key], count: null }] : []);
            if (key === "fuel_class" && !have) options = Object.keys(FF.LABELS.fuelClass).map(value => ({ value, count: null }));
            if (key === "flow_direction" && !have) options = Object.keys(FF.LABELS.flowDirection).map(value => ({ value, count: null }));
            const current = c[key].value;
            const display = option => (key === "fuel_class" ? FF.label("fuelClass", option.value) :
                key === "flow_direction" ? FF.label("flowDirection", option.value) : option.value.replace(/_/g, " ")) +
                (option.count !== null ? " (" + FF.formatNumber(option.count) + ")" : "");
            clear(c[key], h("option", { value: "" }, "Any"), ...options.map(option => h("option", { value: option.value }, display(option))));
            c[key].value = options.some(option => option.value === current) ? current : "";
            // An earlier selection that no longer exists under the new context is cleared.
        }
        const note = state.container.querySelector("#cond-options-note");
        if (note) note.textContent = have
            ? "Counts are distinct run records that pass the quality screen. Options are narrowed to combinations that exist."
            : "Option counts are unavailable.";
    }
    function syncForm(state) {
        const c = state.controls, params = state.params;
        c.p_unit.value = pressureUnit(params);
        refreshOptions(state);
        for (const key of API_KEYS) {
            if (CATEGORY_KEYS.includes(key)) {
                if (params[key] && !Array.from(c[key].children).some(option => option.getAttribute("value") === params[key])) {
                    c[key].append(h("option", { value: params[key] }, params[key].replace(/_/g, " ") + " (0)"));
                }
                c[key].value = params[key] || "";
            } else if (c[key]) c[key].value = params[key] || "";
        }
        refreshOptions(state);
        showErrors(state, buildQuery(params).errors);
        updateSentHint(state);
    }
    function showErrors(state, errors) {
        const c = state.controls;
        for (const range of RANGES) {
            const node = c["error_" + range.name];
            node.textContent = errors[range.name] || "";
            for (const side of ["min", "max"]) {
                if (errors[range.name]) c[range.name + "_" + side].setAttribute("aria-invalid", "true");
                else c[range.name + "_" + side].removeAttribute("aria-invalid");
            }
        }
    }
    function updateSentHint(state) {
        const values = formValues(state);
        const { query, errors } = buildQuery(values);
        const parts = [];
        if ("pressure_min" in query) parts.push("at least " + num(query.pressure_min) + " kPa");
        if ("pressure_max" in query) parts.push("at most " + num(query.pressure_max) + " kPa");
        state.controls.sent.textContent = errors.pressure ? "" :
            parts.length ? "Sent to the API as " + parts.join(" and ") + "." : "The API always receives pressure in kPa.";
    }
    function convertPressure(state) {
        const c = state.controls;
        const from = pressureUnit({ p_unit: state.lastUnit || state.params.p_unit });
        const to = c.p_unit.value;
        for (const key of ["pressure_min", "pressure_max"]) {
            const number = Number(c[key].value);
            if (c[key].value.trim() && Number.isFinite(number)) {
                c[key].value = String(Number((number * FACTORS[from] / FACTORS[to]).toPrecision(6)));
            }
        }
        state.lastUnit = to;
        updateSentHint(state);
    }
    function applyForm(state) {
        const values = formValues(state);
        const { errors } = buildQuery(values);
        showErrors(state, errors);
        if (Object.keys(errors).length) return;
        const next = Object.assign({}, values);
        if (state.params.sort) next.sort = state.params.sort;
        go(state, next);
    }
    function go(state, params) {
        const clean = cleanParams(params);
        state.lastUnit = clean.p_unit || "kPa";
        const hash = FF.buildHash("conditions", [], clean);
        if (global.location.hash === hash) { state.params = clean; load(state); } else FF.navigate("conditions", [], clean);
    }

    // Page through /api/runs like FF.apiAll, but retry each page on its own so one dropped
    // response does not restart all 21 pages. Sources are merged by investigation and table.
    async function fetchAllRuns(query, signal, onProgress) {
        const items = [], sources = new Map();
        let offset = 0, total = 0, meta = null;
        do {
            const params = new URLSearchParams(Object.assign({}, query, { limit: 100, offset }));
            const page = await withRetry(() => FF.api("/api/runs?" + params, { signal }));
            items.push(...page.data);
            meta = meta || page.meta;
            for (const item of page.meta.sources || []) sources.set(item.investigation + "/" + item.table, item);
            total = page.meta.total;
            offset += 100;
            if (onProgress) onProgress(Math.min(offset, total), total);
        } while (offset < total);
        return { data: items, meta: Object.assign({}, meta, { total, offset: 0, limit: items.length, sources: [...sources.values()] }) };
    }

    // ---------- Loading ----------
    // A dropped connection or truncated response is retried twice before an error is shown.
    async function withRetry(request) {
        for (let attempt = 0; ; attempt += 1) {
            try { return await request(); } catch (error) {
                const transient = error && (error.code === "network_error" || error.code === "contract");
                if (!transient || attempt >= 4) throw error;
            }
        }
    }
    async function load(state) {
        if (state.controller) state.controller.abort();
        const controller = new AbortController();
        state.controller = controller;
        state.lastUnit = pressureUnit(state.params);
        const { query, errors } = buildQuery(state.params);
        state.query = query;
        state.queryKey = queryString(query);
        state.error = null;
        state.selectedGroup = null;
        showErrors(state, errors);
        const statusNode = state.regions.status;
        const progress = h("span", {}, "Loading coverage and matching records…");
        clear(statusNode, progress, " ",
            h("button", { type: "button", class: "btn-link", onclick: () => controller.abort() }, "Cancel"));
        statusNode.className = "cond-status status status-loading";
        for (const name of ["summary", "map", "groups", "table"]) clear(state.regions[name]);
        const suffix = state.queryKey ? "?" + state.queryKey : "";
        try {
            const coverageRequest = withRetry(() => FF.api("/api/coverage" + suffix, { signal: controller.signal })).then(result => {
                if (state.controller === controller) { state.coverage = result; renderSummary(state); renderGroups(state); }
                return result;
            });
            const runsRequest = fetchAllRuns(query, controller.signal, (done, total) => {
                if (state.controller === controller) {
                    progress.textContent = "Loading matching records… " + FF.formatNumber(done) + " of " + FF.formatNumber(total);
                }
            });
            const failFast = Promise.all([coverageRequest, runsRequest]);
            failFast.catch(() => controller.abort());
            const [coverage, runs] = await failFast;
            if (state.controller !== controller || !state.alive) return;
            state.coverage = coverage;
            state.runs = runs;
            statusNode.className = "cond-status";
            const ignored = Object.keys(errors);
            clear(statusNode, ignored.length
                ? h("p", { class: "notice notice-warn" }, "Ignored invalid filter" + (ignored.length > 1 ? "s" : "") + ": " + ignored.join(", ") + ". Results use the remaining filters.")
                : null);
            renderSummary(state);
            renderGroups(state);
            renderMap(state);
            renderTable(state);
            openRunFromParams(state);
        } catch (error) {
            if (state.controller !== controller || !state.alive) return;
            state.error = error;
            if (error && error.name === "AbortError") {
                clear(statusNode, "Loading cancelled. ", h("button", { type: "button", class: "btn-link", onclick: () => load(state) }, "Load again"));
                statusNode.className = "cond-status status";
            } else {
                clear(statusNode, h("span", { class: "error" }, (error && error.message) || "The request failed."), " ",
                    h("button", { type: "button", class: "btn-link", onclick: () => load(state) }, "Retry"));
                statusNode.className = "cond-status status status-error";
            }
        }
    }

    // ---------- Summary ----------
    function renderSummary(state) {
        const node = state.regions.summary;
        const coverage = state.coverage;
        const data = coverage.data || {};
        const info = statusInfo(coverage, coverage.meta);
        const counts = data.counts;
        const health = FF.cache.health || {};
        const kids = [h("h2", { id: "cond-summary-h" }, "Coverage in the saved PSI snapshot")];
        if (!counts) {
            kids.push(h("p", { class: "muted" }, "Coverage counts are not available for this request."));
            clear(node, ...kids);
            return;
        }
        kids.push(h("p", { class: "cond-status-line" },
            h("strong", {}, "Coverage status: " + info.label + ". "), info.text));
        if (info.gap) kids.push(h("div", { class: "notice notice-gap", role: "note" }, h("p", {}, GAP_TEXT)));
        if (info.emptyPending) {
            kids.push(h("p", { class: "notice notice-warn" },
                "No records match these filters, but a gap cannot be claimed: records pending review or with unknown conditions exist in the saved snapshot and could change the answer."));
        }
        kids.push(h("p", { class: "small muted" },
            "Scope: saved PSI snapshot" + (health.snapshot_date ? " (" + health.snapshot_date + ")" : "") + ". " +
            (info.provisional ? "Counts are provisional while records are pending review or have unknown conditions. " : "") +
            "Counts follow the filters currently applied; \"distinct\" excludes duplicate rows and notes."));
        kids.push(h("dl", { class: "meta-list cond-counts" }, COUNT_ROWS.flatMap(([key, label]) =>
            counts[key] === undefined ? [] : [h("dt", {}, label), h("dd", { class: "num" }, FF.formatNumber(counts[key]))])));
        clear(node, ...kids);
    }

    // ---------- Map ----------
    function renderMap(state) {
        const node = state.regions.map;
        if (!state.runs) return;
        const model = plotModel(state.runs.data);
        const axes = axisModel(model, state.query);
        const width = Math.max(300, Math.min(900, Math.round((node.getBoundingClientRect().width) || 720)));
        const height = width < 520 ? 340 : 420;
        const margin = { left: 58, right: 54, top: 14, bottom: 48 };
        const pw = width - margin.left - margin.right, ph = height - margin.top - margin.bottom;
        const sx = v => margin.left + (v - axes.x.lo) / (axes.x.hi - axes.x.lo) * pw;
        const sy = v => margin.top + ph - (v - axes.y.lo) / (axes.y.hi - axes.y.lo) * ph;
        const q = state.query;
        const g = (cls, ...kids) => svg("g", { class: cls }, ...kids);
        const items = [];

        // Axes: thin lines, outward ticks, no gridlines.
        const axis = [];
        axis.push(svg("line", { x1: margin.left, y1: margin.top + ph, x2: margin.left + pw, y2: margin.top + ph }));
        axis.push(svg("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: margin.top + ph }));
        axis.push(svg("line", { x1: margin.left + pw, y1: margin.top, x2: margin.left + pw, y2: margin.top + ph }));
        const labels = [];
        for (const tick of axes.x.ticks) {
            axis.push(svg("line", { x1: sx(tick), y1: margin.top + ph, x2: sx(tick), y2: margin.top + ph + 4 }));
            labels.push(svg("text", { x: sx(tick), y: margin.top + ph + 17, "text-anchor": "middle" }, num(tick)));
        }
        for (const tick of axes.y.ticks) {
            axis.push(svg("line", { x1: margin.left - 4, y1: sy(tick), x2: margin.left, y2: sy(tick) }));
            labels.push(svg("text", { x: margin.left - 7, y: sy(tick) + 4, "text-anchor": "end" }, num(tick)));
        }
        for (const tick of axes.y.atmTicks) {
            const y = sy(tick * FF.KPA_PER_ATM);
            axis.push(svg("line", { x1: margin.left + pw, y1: y, x2: margin.left + pw + 4, y2: y }));
            labels.push(svg("text", { x: margin.left + pw + 7, y: y + 4, "text-anchor": "start" }, num(tick)));
        }
        items.push(g("cond-axis", ...axis), g("cond-ticklabels", ...labels));
        items.push(svg("text", { class: "cond-axis-title", x: margin.left + pw / 2, y: height - 6, "text-anchor": "middle" },
            "Oxygen (% by volume)"));
        items.push(svg("text", { class: "cond-axis-title", transform: "translate(13 " + (margin.top + ph / 2) + ") rotate(-90)", "text-anchor": "middle" },
            "Pressure (kPa)"));
        items.push(svg("text", { class: "cond-axis-title", transform: "translate(" + (width - 6) + " " + (margin.top + ph / 2) + ") rotate(90)", "text-anchor": "middle" },
            "Pressure (atm)"));

        // Active O2/pressure filter window.
        if (["o2_min", "o2_max", "pressure_min", "pressure_max"].some(key => key in q)) {
            const x1 = sx("o2_min" in q ? Math.max(q.o2_min, axes.x.lo) : axes.x.lo);
            const x2 = sx("o2_max" in q ? Math.min(q.o2_max, axes.x.hi) : axes.x.hi);
            const y1 = sy("pressure_max" in q ? Math.min(q.pressure_max, axes.y.hi) : axes.y.hi);
            const y2 = sy("pressure_min" in q ? Math.max(q.pressure_min, axes.y.lo) : axes.y.lo);
            items.push(svg("rect", { class: "cond-window", x: Math.min(x1, x2), y: Math.min(y1, y2),
                width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) }, svg("title", {}, "Active O2 and pressure filter window")));
        }

        // Reference atmospheres.
        const refs = REFERENCE_ATMOSPHERES.map(ref => {
            const x = sx(ref.o2), y = sy(ref.kpa), r = 5.5;
            const anchor = x > margin.left + pw - 70 ? "end" : x < margin.left + 60 ? "start" : "middle";
            const label = ref.psia + " psia, " + ref.o2 + "% O2";
            return svg("g", { class: "cond-ref" },
                svg("title", {}, "Reference atmosphere, not experimental data: " + label + " (" + num(ref.kpa) + " kPa)"),
                svg("polygon", { points: [x, y - r, x + r, y, x, y + r, x - r, y].join(","), class: "cond-ref-mark" }),
                svg("text", { x, y: y - r - 6, "text-anchor": anchor }, label));
        });

        // Data marks, widest intervals first so points stay on top.
        const open = mark => (mark.ids.length === 1 ? openRun(state, mark.ids[0]) : showPicked(state, mark));
        const markNodes = [];
        const ordered = model.marks.slice().sort((a, b) => Number(b.interval) - Number(a.interval));
        for (const mark of ordered) {
            const count = mark.ids.length;
            const review = mark.filled ? "reviewed or parsed" : "pending review";
            const title = (count > 1 ? count + " records" : mark.ids[0]) + ": O2 " + span(mark.o2) + " %, pressure " +
                span(mark.pressure) + " kPa (" + span(mark.pressure.map(v => Number((v / FF.KPA_PER_ATM).toPrecision(4)))) + " atm), " + review;
            const cls = "cond-mark " + (mark.filled ? "is-filled" : "is-pending") + (mark.interval ? " is-interval" : "");
            const x1 = sx(mark.o2[0]), x2 = sx(mark.o2[1]), y1 = sy(mark.pressure[1]), y2 = sy(mark.pressure[0]);
            let shape, hit;
            if (!mark.interval) {
                const r = Math.min(6.5, 2.8 + 0.9 * Math.sqrt(count - 1));
                shape = svg("circle", { class: "cond-shape", cx: x1, cy: y2, r });
                hit = svg("circle", { class: "cond-hit", cx: x1, cy: y2, r: Math.max(r + 4, 8) });
            } else if (mark.o2[0] !== mark.o2[1] && mark.pressure[0] !== mark.pressure[1]) {
                shape = svg("rect", { class: "cond-shape cond-box", x: x1, y: y1, width: Math.max(x2 - x1, 1), height: Math.max(y2 - y1, 1) });
                hit = svg("rect", { class: "cond-hit", x: x1 - 4, y: y1 - 4, width: x2 - x1 + 8, height: y2 - y1 + 8 });
            } else if (mark.o2[0] !== mark.o2[1]) {
                shape = svg("path", { class: "cond-shape cond-line", d: "M" + x1 + " " + (y2 - 4) + "V" + (y2 + 4) + "M" + x1 + " " + y2 + "H" + x2 + "M" + x2 + " " + (y2 - 4) + "V" + (y2 + 4) });
                hit = svg("rect", { class: "cond-hit", x: x1 - 4, y: y2 - 8, width: x2 - x1 + 8, height: 16 });
            } else {
                shape = svg("path", { class: "cond-shape cond-line", d: "M" + (x1 - 4) + " " + y1 + "H" + (x1 + 4) + "M" + x1 + " " + y1 + "V" + y2 + "M" + (x1 - 4) + " " + y2 + "H" + (x1 + 4) });
                hit = svg("rect", { class: "cond-hit", x: x1 - 8, y: y1 - 4, width: 16, height: y2 - y1 + 8 });
            }
            markNodes.push(svg("g", {
                class: cls, tabindex: 0, role: "button", "aria-label": title + (count > 1 ? ". Opens a list." : ". Opens run detail."),
                onclick: () => open(mark),
                onkeydown: event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(mark); } },
            }, svg("title", {}, title), hit, shape));
        }
        items.push(g("cond-marks", ...markNodes));
        // Reference atmospheres drawn last so data marks never hide them.
        items.push(g("cond-refs", ...refs));

        const figure = svg("svg", {
            class: "cond-svg", viewBox: "0 0 " + width + " " + height, width: "100%", role: "group",
            "aria-label": "Coverage map: oxygen against pressure for the matching records",
        }, svg("title", {}, "Oxygen against pressure for matching records"), ...items);
        figure.style.maxWidth = width + "px";

        const legend = h("ul", { class: "cond-legend-list small", "aria-label": "Map legend" },
            legendItem("cond-key-point is-filled", "Reviewed or parsed record"),
            legendItem("cond-key-point is-pending", "Record pending review"),
            legendItem("cond-key-range", "Interval (sweep or range)"),
            legendItem("cond-key-ref", "Reference atmosphere, not experimental data"),
            legendItem("cond-key-window", "Active O2 and pressure filter"));
        const interval = model.intervals;
        const caption = h("p", { class: "cond-caption small" },
            "Plotted: " + FF.formatNumber(model.plotted) + " of " + FF.formatNumber(model.total) + " matching records; " +
            FF.formatNumber(model.unknown) + " have unknown O2 or pressure and appear only in the table; " +
            FF.formatNumber(interval) + " use intervals. " +
            (model.excluded ? FF.formatNumber(model.excluded) + " are notes, sessions, duplicate rows or quality-excluded readings and are not plotted. " : "") +
            "Axes: O2 " + num(axes.x.lo) + "–" + num(axes.x.hi) + " %; pressure " + num(axes.y.lo) + "–" + num(axes.y.hi) + " kPa (" +
            num(axes.y.lo / FF.KPA_PER_ATM) + "–" + num(axes.y.hi / FF.KPA_PER_ATM) + " atm). Larger circles stand for several records with identical values.");
        state.model = model;
        state.regions.picked = state.regions.picked || h("div", { class: "cond-picked-slot", "aria-live": "polite" });
        clear(node, h("h2", { id: "cond-map-h" }, "Oxygen–pressure map"), h("div", { class: "cond-figure" }, figure),
            legend, caption, state.regions.picked);
        clear(state.regions.picked);
    }
    function legendItem(keyClass, label) {
        const key = svg("svg", { class: "cond-key " + keyClass, viewBox: "0 0 16 12", width: 16, height: 12, "aria-hidden": "true" },
            keyClass.includes("point") ? svg("circle", { class: "cond-shape", cx: 8, cy: 6, r: 3.5 }) :
            keyClass.includes("range") ? svg("path", { class: "cond-shape cond-line", d: "M2 6H14M2 3V9M14 3V9" }) :
            keyClass.includes("ref") ? svg("polygon", { class: "cond-ref-mark", points: "8,0.5 13.5,6 8,11.5 2.5,6" }) :
            svg("rect", { class: "cond-window", x: 1, y: 1, width: 14, height: 10 }));
        return h("li", {}, key, " ", label);
    }
    function showPicked(state, mark) {
        const slot = state.regions.picked;
        const shown = mark.ids.slice(0, 60);
        clear(slot, h("div", { class: "cond-picked" },
            h("p", { class: "small" }, h("strong", {}, FF.formatNumber(mark.ids.length) + " records"),
                " share O2 " + span(mark.o2) + " %, pressure " + span(mark.pressure) + " kPa (" + (mark.filled ? "reviewed or parsed" : "pending review") + ")."),
            h("ul", { class: "cond-picked-list" }, shown.map(id => h("li", {},
                h("button", { type: "button", class: "btn-link id", onclick: () => openRun(state, id) }, id)))),
            mark.ids.length > shown.length ? h("p", { class: "small muted" }, "Showing " + shown.length + " of " + mark.ids.length + "; the rest are in the table.") : null,
            h("button", { type: "button", class: "btn btn-quiet", onclick: () => clear(slot) }, "Close list")));
    }

    // ---------- Groups ----------
    function groupLabel(group) {
        const c = group.conditions || {};
        const part = (value, grp) => value === null || value === undefined ? "unknown" : (grp ? FF.label(grp, value) : value);
        return [part(c.fuel_class, "fuelClass"), part(c.material), part(c.geometry), part(c.flow_direction, "flowDirection")].join(" / ") +
            (c.hardware ? " / " + c.hardware : " / hardware unknown");
    }
    function renderGroups(state) {
        const node = state.regions.groups;
        const data = state.coverage.data || {};
        const groups = data.groups || [];
        const cell = (value, grp) => value === null || value === undefined
            ? h("td", {}, h("span", { class: "unknown" }, "Unknown")) : h("td", {}, grp ? FF.label(grp, value) : String(value));
        const body = groups.map((group, index) => {
            const c = group.conditions || {};
            return h("tr", { class: state.selectedGroup === index ? "is-selected" : null },
                cell(c.fuel_class, "fuelClass"), cell(c.material), cell(c.geometry), cell(c.flow_direction, "flowDirection"),
                h("td", { class: "cond-hardware" }, c.hardware ? c.hardware : h("span", { class: "unknown" }, "Unknown")),
                h("td", { class: "n" }, FF.formatNumber(group.run_record_count)),
                h("td", { class: "n" }, FF.formatNumber(group.verified_run_count)),
                h("td", {}, group.comparison_status === "compatible" ? "All five attributes known" : "Indeterminate"),
                h("td", {}, (STATUS[group.coverage_status] || [FF.label("", group.coverage_status)])[0]),
                h("td", {}, h("button", { type: "button", class: "btn-link", "aria-pressed": state.selectedGroup === index ? "true" : "false",
                    onclick: () => { state.selectedGroup = state.selectedGroup === index ? null : index; renderGroups(state); } },
                    "Differences")));
        });
        const details = h("details", { class: "cond-details", open: state.groupsOpen ? true : null });
        details.addEventListener("toggle", () => { state.groupsOpen = details.open; });
        details.append(h("summary", {}, "Condition groups (" + groups.length + ")"),
            h("div", { class: "stack" },
                h("p", { class: "small" },
                    "Runs are quantitatively comparable only within a group whose fuel class, material, geometry, flow direction and hardware are all known and equal. " +
                    "Two groups are incompatible when they differ in a listed field, and indeterminate when a field is unknown. Counts cover run records that pass the quality screen."),
                groups.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
                    h("thead", {}, h("tr", {}, ["Fuel class", "Material", "Geometry", "Flow direction", "Hardware", "Records", "Reviewed runs", "Comparison", "Coverage", ""]
                        .map((title, i) => h("th", { scope: "col", class: i === 5 || i === 6 ? "n" : null }, title)))),
                    h("tbody", {}, body))) : h("p", { class: "muted" }, "No condition groups for these filters."),
                differencesView(state, groups, data.comparisons || [])));
        clear(node, details);
    }
    function differencesView(state, groups, comparisons) {
        const index = state.selectedGroup;
        if (index === null || index === undefined || !groups[index]) return null;
        const rows = [];
        for (const pair of comparisons) {
            const [a, b] = pair.group_indices;
            if (a !== index && b !== index) continue;
            const other = a === index ? b : a;
            rows.push(h("li", {}, h("span", {}, groupLabel(groups[other])), ": ",
                pair.status === "incompatible"
                    ? "incompatible; differs in " + pair.differing_fields.map(field => field.replace(/_/g, " ")).join(", ")
                    : "indeterminate; a field is unknown"));
        }
        return h("div", { class: "cond-differences" },
            h("h3", {}, "Differences from " + groupLabel(groups[index])),
            rows.length ? h("ul", { class: "small" }, rows) : h("p", { class: "small muted" }, "No other groups."));
    }

    // ---------- Table and export ----------
    function renderTable(state) {
        const node = state.regions.table;
        if (!state.runs) return;
        const { data: records, meta } = state.runs;
        const coverageTotal = state.coverage && state.coverage.data && state.coverage.data.counts
            ? state.coverage.data.counts.source_records : null;
        const mismatch = coverageTotal !== null && coverageTotal !== meta.total;
        const holder = h("div", { class: "cond-table" });
        const exportDisabled = records.length === 0;
        clear(node,
            h("h2", { id: "cond-table-h" }, "Matching source rows"),
            h("p", { class: "cond-count", role: "status" }, h("strong", { class: "num" }, FF.formatNumber(meta.total)),
                " source rows (not individual experiments)."),
            mismatch ? h("p", { class: "notice notice-warn" }, "The coverage counts (" + FF.formatNumber(coverageTotal) +
                " source rows) and the runs list (" + FF.formatNumber(meta.total) + ") disagree for this filter set. Reload before relying on either.") : null,
            h("div", { class: "cluster no-print cond-export" },
                h("button", { type: "button", class: "btn", disabled: exportDisabled ? true : null, onclick: () => exportCsv(state) }, "Download CSV"),
                h("button", { type: "button", class: "btn", disabled: exportDisabled ? true : null, onclick: () => exportJson(state) }, "Download JSON"),
                h("span", { class: "small muted" }, "Exports the filtered set with its filters and snapshot date.")),
            records.length ? holder : h("p", { class: "empty" }, "No source rows match these filters."));
        if (!records.length) return;
        if (global.FF.runs && typeof FF.runs.renderTable === "function") {
            FF.runs.renderTable(holder, records, {
                sources: meta.sources, sort: state.params.sort,
                onSort: sort => {
                    state.params = cleanParams(Object.assign({}, state.params, { sort: sort || "" }));
                    pushParams(state);
                    renderTable(state);
                },
                onSelect: id => openRun(state, id),
            });
        } else {
            FF.append(holder, [h("p", { class: "small muted" }, "The runs table is not loaded; showing record identifiers only."),
                h("ul", { class: "small" }, records.slice(0, 300).map(record => h("li", {}, h("span", { class: "id" }, record.id), " ", FF.label("kind", record.kind)))),
                records.length > 300 ? h("p", { class: "small muted" }, "Showing 300 of " + records.length + ".") : null]);
        }
    }
    function pushParams(state) { FF.replaceParams("conditions", [], state.params); }
    function openRun(state, id) {
        state.openedRun = id;
        state.params = cleanParams(Object.assign({}, state.params, { run: id }));
        pushParams(state);
        if (FF.runs && typeof FF.runs.openDetail === "function") FF.runs.openDetail(id);
    }
    function openRunFromParams(state) {
        const id = state.params.run;
        if (id && id !== state.openedRun) {
            state.openedRun = id;
            if (FF.runs && typeof FF.runs.openDetail === "function") FF.runs.openDetail(id);
        }
    }
    function exportName(state, extension) {
        const date = ((FF.cache.health && FF.cache.health.snapshot_date) || new Date().toISOString().slice(0, 10));
        return "flame-in-freefall_runs_" + filterSlug(state.query) + "_" + date + "." + extension;
    }
    function exportCsv(state) {
        const { data, meta } = state.runs;
        let csv;
        if (FF.runs && typeof FF.runs.csv === "function") csv = FF.runs.csv(data, meta.sources);
        else {
            const range = quantity => FF.isKnownQuantity(quantity) ? (quantity.min === quantity.max ? quantity.min : quantity.min + "-" + quantity.max) : "";
            csv = FF.toCsv(["id", "kind", "review_status", "o2_percent", "pressure_kpa", "flow_cm_s"],
                data.map(r => [r.id, r.kind, r.review_status, range(r.conditions.o2_percent), range(r.conditions.pressure_kpa), range(r.conditions.flow_cm_s)]));
        }
        FF.download(exportName(state, "csv"), csv, "text/csv");
    }
    function exportJson(state) {
        FF.download(exportName(state, "json"), JSON.stringify(buildExport(state), null, 2) + "\n", "application/json");
    }

    FF.conditions = Object.assign(FF.conditions || {}, {
        buildQuery, queryString, cleanParams, filterSlug, optionsFromGroups, plotModel, axisModel, niceAxis, statusInfo,
        buildExport, REFERENCE_ATMOSPHERES, GAP_TEXT, current: null,
    });
    FF.views.conditions = { mount, update, unmount };
})(typeof window !== "undefined" ? window : globalThis);
