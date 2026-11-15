// File inventory browser (#/files, #/files/PSI-69?filename=&category=&extension=&page=).
// "Catalogued" means listed in the PSI file inventory, not downloaded or processed.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, status } = FF;

    const PAGE_SIZE = 50;
    const EXPORT_WARN_ROWS = 5000;
    const EXTENSION_PATTERN = /^\.[A-Za-z0-9][A-Za-z0-9_+-]*$/;

    // ---------- Pure helpers ----------
    // URL params -> validated filters. `error` is set when the extension cannot be sent to the API.
    function parseFilters(params = {}) {
        const filters = {
            filename: String(params.filename || "").trim(),
            category: String(params.category || "").trim(),
            extension: String(params.extension || "").trim(),
        };
        const page = Number.parseInt(params.page, 10);
        filters.page = Number.isFinite(page) && page >= 1 ? page : 1;
        const error = filters.extension && !EXTENSION_PATTERN.test(filters.extension)
            ? "The extension must start with a period, for example .csv." : null;
        return { filters, error };
    }
    // Filters only (no paging) as API params; empty values are omitted.
    function filterParams(filters) {
        const out = {};
        for (const key of ["filename", "category", "extension"]) if (filters[key]) out[key] = filters[key];
        return out;
    }
    function buildPath(accession, filters, page = filters.page) {
        const query = new URLSearchParams(Object.assign(filterParams(filters),
            { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }));
        return "/api/studies/" + FF.encodeId(accession) + "/files?" + query;
    }
    function shortHash(hash) { return hash ? String(hash).slice(0, 12) : null; }
    function csv(rows) {
        const header = ["accession", "file_id", "version", "key", "filename", "category", "extension", "bytes", "access", "download_sha256"];
        return FF.toCsv(header, rows.map(row => header.map(name => row[name])));
    }
    function optionLabel(study) { return study.accession + " · " + FF.studyLabel(study); }

    // ---------- Rendering ----------
    function renderRow(row) {
        const sha = shortHash(row.download_sha256);
        return h("tr", {},
            h("td", { class: "files-name", title: row.key || null },
                h("span", {}, row.filename || "Unnamed file"),
                row.version !== null && row.version !== undefined ? h("span", { class: "muted small" }, " v" + row.version) : null,
                h("span", { class: "files-key id small" }, row.key || "")),
            h("td", {}, row.category ? row.category : h("span", { class: "unknown" }, "Not recorded")),
            h("td", {}, row.extension ? h("span", { class: "id" }, row.extension) : h("span", { class: "unknown" }, "None")),
            h("td", { class: "n num" }, Number.isFinite(row.bytes) ? FF.formatBytes(row.bytes) : h("span", { class: "unknown" }, "Unknown")),
            h("td", {}, FF.label("access", row.access)),
            h("td", {}, sha
                ? [h("span", {}, "Bytes verified"), h("div", { class: "id small", title: row.download_sha256 }, "SHA-256 " + sha)]
                : h("span", { class: "muted" }, "Not downloaded")));
    }
    function renderTable(rows) {
        const head = ["File name", "Category", "Extension", "Size", "Access", "Download"];
        return h("div", { class: "table-wrap" }, h("table", { class: "table files-table" },
            h("caption", { class: "visually-hidden" }, "Catalogued files"),
            h("thead", {}, h("tr", {}, head.map(text => h("th", { scope: "col", class: text === "Size" ? "n" : null }, text)))),
            h("tbody", {}, rows.map(renderRow))));
    }

    // ---------- View ----------
    const categoriesSeen = new Map(); // accession -> Set(category)
    let ui = null;

    function mount(container, route) {
        unmount();
        const accession = route.args[0] || "";
        const select = h("select", { id: "files-acc" }, h("option", { value: "" }, "Select an investigation"));
        const filename = h("input", { type: "search", id: "files-filename", autocomplete: "off" });
        const category = h("input", { type: "text", id: "files-category", list: "files-categories", autocomplete: "off" });
        const datalist = h("datalist", { id: "files-categories" });
        const extension = h("input", { type: "text", id: "files-extension", placeholder: ".csv", autocomplete: "off",
            "aria-describedby": "files-extension-hint" });
        const extensionHint = h("span", { class: "hint", id: "files-extension-hint" }, "Starts with a period, for example .csv.");
        const form = h("form", { class: "filters files-filters" },
            h("div", { class: "field-row" },
                h("div", { class: "field" }, h("label", { for: "files-acc" }, "Investigation"), select),
                h("div", { class: "field" }, h("label", { for: "files-filename" }, "File name contains"), filename)),
            h("div", { class: "field-row" },
                h("div", { class: "field" }, h("label", { for: "files-category" }, "Category (exact)"), category, datalist),
                h("div", { class: "field" }, h("label", { for: "files-extension" }, "Extension"), extension, extensionHint),
                h("div", { class: "field files-apply" }, h("button", { type: "submit", class: "btn-primary" }, "Apply filters"))));
        const heading = h("p", { role: "status", "aria-live": "polite" });
        const headingWrap = h("div", { class: "files-heading" }, heading);
        const body = h("div", { class: "files-body" });
        const exportStatus = h("p", { class: "status", role: "status" });

        const state = { controller: null, exportController: null, token: 0, accession, total: null };
        ui = state;

        function refreshDatalist() {
            clear(datalist, [...(categoriesSeen.get(state.accession) || [])].sort().map(name => h("option", { value: name })));
        }
        function syncForm(filters) {
            filename.value = filters.filename;
            category.value = filters.category;
            extension.value = filters.extension;
        }
        function go(filters, page) {
            FF.navigate("files", state.accession ? [state.accession] : [],
                Object.assign(filterParams(filters), page > 1 ? { page } : {}));
        }
        function formFilters() {
            return { filename: filename.value.trim(), category: category.value.trim(), extension: extension.value.trim(), page: 1 };
        }

        select.addEventListener("change", () => {
            FF.navigate("files", select.value ? [select.value] : [], {});
        });
        form.addEventListener("submit", event => {
            if (event.preventDefault) event.preventDefault();
            // The select may still be loading its options; the accession from the URL remains valid.
            const chosen = select.value || state.accession;
            if (!chosen) { status(heading, "Choose an investigation first.", "error"); return; }
            const { error } = parseFilters(formFilters());
            if (error) { showExtensionError(error); return; }
            state.accession = chosen;
            go(formFilters(), 1);
        });
        function showExtensionError(message) {
            extension.setAttribute("aria-invalid", "true");
            clear(extensionHint, message);
            extensionHint.className = "hint error";
            extensionHint.setAttribute("role", "alert");
        }
        function clearExtensionError() {
            extension.removeAttribute("aria-invalid");
            clear(extensionHint, "Starts with a period, for example .csv.");
            extensionHint.className = "hint";
            extensionHint.removeAttribute("role");
        }

        async function load(route) {
            const { filters, error } = parseFilters(route.params);
            syncForm(filters);
            clearExtensionError();
            refreshDatalist();
            if (state.controller) state.controller.abort();
            if (!state.accession) {
                status(heading, "");
                clear(body, h("p", { class: "empty" }, "Choose an investigation to browse its catalogued files."));
                return;
            }
            if (error) {
                showExtensionError(error);
                status(heading, "No request was sent: " + error, "error");
                clear(body);
                return;
            }
            const token = ++state.token;
            state.controller = new AbortController();
            status(heading, state.accession + " · loading catalogued files…", "loading");
            clear(body);
            try {
                const result = await FF.api(buildPath(state.accession, filters), { signal: state.controller.signal });
                if (token !== state.token) return;
                state.total = result.meta.total;
                const seen = categoriesSeen.get(state.accession) || new Set();
                for (const row of result.data) if (row.category) seen.add(row.category);
                if (filters.category) seen.add(filters.category);
                categoriesSeen.set(state.accession, seen);
                refreshDatalist();
                renderResult(result, filters);
            } catch (failure) {
                if (failure.name === "AbortError" || token !== state.token) return;
                state.total = null;
                status(heading, state.accession + " · files unavailable", "error");
                clear(body, h("p", { class: "error", role: "alert" }, failure.status === 404
                    ? "No investigation " + state.accession + " in this dataset."
                    : failure.message));
            }
        }

        function renderResult(result, filters) {
            const total = result.meta.total;
            const offset = result.meta.offset || 0;
            const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
            status(heading, state.accession + " · " + FF.formatNumber(total) + " catalogued file" + (total === 1 ? "" : "s") + " match");
            const makePager = detailed => total > PAGE_SIZE ? h("div", { class: "pagination" },
                FF.button("Previous", () => go(filters, filters.page - 1), { disabled: filters.page <= 1 }),
                h("span", { class: "range" }, detailed
                    ? FF.formatNumber(offset + 1) + "–" + FF.formatNumber(offset + result.data.length) + " of " + FF.formatNumber(total) +
                        " (page " + filters.page + " of " + FF.formatNumber(pages) + ")"
                    : "Page " + filters.page + " of " + FF.formatNumber(pages)),
                FF.button("Next", () => go(filters, filters.page + 1), { disabled: filters.page >= pages })) : null;
            clear(body,
                result.data.length ? [makePager(true), renderTable(result.data), makePager(false)]
                    : h("p", { class: "empty" }, total === 0 ? "No catalogued files match these filters."
                        : "This page is past the last result. Return to page 1."));
        }

        async function exportAll() {
            const { filters, error } = parseFilters(state.route ? state.route.params : {});
            if (!state.accession || error) return;
            if (state.total > EXPORT_WARN_ROWS && typeof global.confirm === "function" &&
                !global.confirm("This will fetch " + FF.formatNumber(state.total) + " rows. Continue?")) return;
            if (state.exportController) state.exportController.abort();
            const controller = state.exportController = new AbortController();
            const cancel = FF.button("Cancel export", () => controller.abort());
            clear(exportStatus, h("span", {}, "Fetching file list…"), " ", cancel);
            exportStatus.className = "status status-loading";
            try {
                const result = await FF.apiAll("/api/studies/" + FF.encodeId(state.accession) + "/files", filterParams(filters), {
                    signal: controller.signal,
                    onProgress: (done, total) => { exportStatus.firstChild && (exportStatus.firstChild.textContent =
                        "Fetched " + FF.formatNumber(done) + " of " + FF.formatNumber(total) + " rows…"); },
                });
                FF.download("files_" + state.accession + ".csv", csv(result.data), "text/csv");
                status(exportStatus, "Exported " + FF.formatNumber(result.data.length) + " rows.");
            } catch (failure) {
                status(exportStatus, failure.name === "AbortError" ? "Export cancelled." : "Export failed: " + failure.message,
                    failure.name === "AbortError" ? "" : "error");
            }
        }

        const note = h("div", { class: "notice files-note" },
            h("p", {}, "Catalogued means listed in the PSI file inventory; it does not mean the contents were downloaded or processed. 'Bytes verified' means a downloaded copy matched its SHA-256."));
        const exportBar = h("div", { class: "cluster no-print" },
            FF.button("Export file list (CSV)", exportAll, { disabled: !accession }),
            accession ? FF.externalLink("Open investigation on PSI", FF.PSI_INVESTIGATION_URL + encodeURIComponent(accession)) : null);

        clear(container,
            h("header", { class: "page-head" }, h("h1", {}, "File inventory"),
                h("p", { class: "lede" }, "Browse the files catalogued by PSI for one investigation.")),
            form, headingWrap, note, exportBar, exportStatus, body);

        state.load = nextRoute => { state.route = nextRoute; state.accession = nextRoute.args[0] || ""; return load(nextRoute); };

        FF.studyIndex().then(index => {
            if (ui !== state) return;
            const known = new Set(index.map(study => study.accession));
            for (const study of index) select.append(h("option", { value: study.accession }, optionLabel(study)));
            if (accession && !known.has(accession)) select.append(h("option", { value: accession }, accession));
            select.value = accession;
        }).catch(() => {
            if (accession) select.append(h("option", { value: accession }, accession));
            select.value = accession;
        });

        return state.load(route);
    }

    function update(route) { if (ui) return ui.load(route); }
    function unmount() {
        if (ui) {
            if (ui.controller) ui.controller.abort();
            if (ui.exportController) ui.exportController.abort();
        }
        ui = null;
    }

    FF.files = { PAGE_SIZE, parseFilters, filterParams, buildPath, shortHash, csv, EXTENSION_PATTERN };
    FF.views.files = { mount, update, unmount };
})(typeof window !== "undefined" ? window : globalThis);
