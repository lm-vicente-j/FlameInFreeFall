// Investigations: search/list (#/studies), detail page (#/study/ACC) and the shared evidence dialog.
// Classic script; registers FF.views.studies, FF.views.study, FF.evidence and the testable helpers FF.studies.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, status, api, encodeId } = FF;

    const PAGE_SIZE = 50;
    const CATEGORIES = ["prevention", "detection", "suppression"];
    const NOT_STATED = "Not stated in this card";

    // ---------- Pure helpers ----------
    function escapeRegExp(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

    function queryTerms(query) {
        const seen = new Set();
        const terms = [];
        for (const raw of String(query || "").split(/[\s"“”(),;:]+/)) {
            const term = raw.trim();
            if (term.length < 2 || seen.has(term.toLowerCase())) continue;
            seen.add(term.toLowerCase());
            terms.push(term);
        }
        return terms.sort((a, b) => b.length - a.length);
    }

    // Split text into plain strings and <mark> nodes. Never uses innerHTML.
    function highlight(text, query) {
        const value = String(text === null || text === undefined ? "" : text);
        const terms = queryTerms(query);
        if (!terms.length) return [value];
        const pattern = new RegExp("(" + terms.map(escapeRegExp).join("|") + ")", "gi");
        return value.split(pattern).map((part, index) => index % 2 === 1 ? h("mark", {}, part) : part)
            .filter(part => part !== "");
    }

    // A short window of an excerpt around the first query-term hit.
    function excerptWindow(text, query, max = 320) {
        const flat = String(text || "").replace(/\s+/g, " ").trim();
        if (flat.length <= max) return flat;
        const terms = queryTerms(query);
        let index = -1;
        for (const term of terms) {
            const found = flat.toLowerCase().indexOf(term.toLowerCase());
            if (found >= 0 && (index < 0 || found < index)) index = found;
        }
        const start = Math.max(0, index < 0 ? 0 : index - 100);
        const end = Math.min(flat.length, start + max);
        return (start > 0 ? "… " : "") + flat.slice(start, end).trim() + (end < flat.length ? " …" : "");
    }

    function listParams(state) {
        const params = { limit: PAGE_SIZE, offset: (Math.max(1, state.page || 1) - 1) * PAGE_SIZE };
        if (state.q) params.q = state.q;
        if (state.category) params.safety_category = state.category;
        return new URLSearchParams(params);
    }

    function formatLocator(locator) {
        if (!locator || typeof locator !== "object") return "Locator not recorded";
        const parts = [];
        if (locator.kind === "metadata") {
            parts.push("PSI metadata field “" + (locator.field || "unknown") + "”");
        } else if (locator.kind === "pdf") {
            parts.push((locator.filename || "PDF file") + (locator.page !== undefined ? ", page " + locator.page : ""));
        } else if (locator.kind === "table") {
            parts.push((locator.filename || "Table file") + (locator.row !== undefined ? ", row " + locator.row : ""));
            if (locator.sheet) parts.push("sheet " + locator.sheet);
            if (locator.columns) parts.push("columns " + [].concat(locator.columns).join(", "));
        } else {
            parts.push((locator.kind || "source") + (locator.filename ? ": " + locator.filename : ""));
        }
        return parts.join(" · ");
    }

    function datePart(value) { return typeof value === "string" && value ? value.slice(0, 10) : null; }

    // meta.source, tolerant of string or object entries. Returns null when absent: nothing is invented.
    function normalizeSource(source) {
        if (!source || typeof source !== "object") return null;
        const people = (Array.isArray(source.investigators) ? source.investigators : []).map(item =>
            typeof item === "string" ? { name: item } :
            { name: item && item.name,
              role: item && (Array.isArray(item.roles) ? item.roles.filter(Boolean).join("; ") : item.role) || null,
              roles: item && Array.isArray(item.roles) ? item.roles : (item && item.role ? [item.role] : []),
              affiliation: item && (item.affiliation || item.institution || item.organization) })
            .filter(person => person.name);
        const publications = (Array.isArray(source.publications) ? source.publications : []).map(item =>
            typeof item === "string" ? { title: item } : item).filter(Boolean);
        const doi = source.doi ? String(source.doi) : null;
        return {
            title: source.title || null,
            doi,
            doiUrl: doi ? (/^https?:/i.test(doi) ? doi : "https://doi.org/" + doi.replace(/^doi:\s*/i, "")) : null,
            psiUrl: source.psi_url || source.url || source.source_url || null,
            license: source.license || null,
            startDate: source.start_date || null,
            endDate: source.end_date || null,
            retrievedAt: source.retrieved_at || null,
            investigators: people,
            publications,
        };
    }
    function authorNames(publication) {
        const authors = publication.authors;
        if (!authors) return "";
        return Array.isArray(authors) ? authors.map(a => typeof a === "string" ? a : a && a.name).filter(Boolean).join(", ") : String(authors);
    }

    function bibtexEscape(text) { return String(text).replace(/[\\{}]/g, "\\$&"); }

    // Dataset citation built only from what the server gave. Returns {available, text, bibtex, notes}.
    function buildCitation(card, rawSource) {
        const source = normalizeSource(rawSource);
        const accession = card.accession;
        const psiUrl = FF.PSI_INVESTIGATION_URL + encodeURIComponent(accession);
        if (!source || !source.investigators.length) {
            const text = [card.title, "NASA Physical Sciences Informatics, " + accession, psiUrl].join(". ") + ".";
            return { available: false, text, bibtex: null,
                reason: "Investigator and publication metadata are not available from this server, so author and date fields are omitted. This is a locator citation only." };
        }
        // Authors: people PSI lists with an investigator role (PI, Co-I, Investigator), in source order.
        // Project scientists and other contacts are not authors. Falls back to everyone listed if no role says investigator.
        const investigatorRole = person => person.roles.some(role => /investigator|\(PI\)|\(Co-I\)/i.test(role));
        const authors = source.investigators.some(investigatorRole) ? source.investigators.filter(investigatorRole) : source.investigators;
        const names = authors.map(person => person.name);
        // PSI gives no publication year; the investigation dates are not one. Cite the snapshot access date instead.
        const accessed = datePart(source.retrievedAt);
        const title = source.title || card.title;
        const version = card.source_version !== undefined && card.source_version !== null ? "version " + card.source_version : null;
        const link = source.doiUrl || psiUrl;
        const text = names.join(", ") + ". " + title + " [Data set]. " +
            ["NASA Physical Sciences Informatics", accession, version].filter(Boolean).join(", ") + ". " + link +
            (accessed ? " (accessed " + accessed + ")" : "") + ".";
        const key = accession.replace(/[^A-Za-z0-9]/g, "") + "_v" + (card.source_version ?? "");
        const fields = [["author", names.map(bibtexEscape).join(" and ")], ["title", bibtexEscape(title)]];
        fields.push(["howpublished", "NASA Physical Sciences Informatics, " + accession], ["publisher", "NASA Physical Sciences Informatics"]);
        if (version) fields.push(["version", String(card.source_version)]);
        if (source.doi) fields.push(["doi", source.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "")]);
        fields.push(["url", source.doiUrl || psiUrl]);
        if (accessed) fields.push(["urldate", accessed]);
        const bibtex = "@misc{" + key + ",\n" + fields.map(([k, v]) => "  " + k + " = {" + v + "}").join(",\n") + "\n}";
        return { available: true, text, bibtex, reason: null };
    }
    function buildRecordCitation(card, snapshotDate) {
        const review = card.review || {};
        return "Flame in Freefall research card for " + card.accession + ", source version " + card.source_version +
            ", review state: " + FF.label("review", review.status, "not given") +
            (review.reviewer && review.reviewed_at ? " (" + review.reviewer + ", " + datePart(review.reviewed_at) + ")" : "") +
            ", PSI snapshot " + (snapshotDate || "date unavailable") + ".";
    }

    function exportFilename(card) { return card.accession + "_v" + card.source_version + "_research-card.json"; }
    function exportText(card) { return JSON.stringify(card, null, 2); }

    // Reference numbering: one number per evidence item in card.evidence order; unknown cited ids follow.
    function buildNumbering(card) {
        const map = {};
        let next = 1;
        for (const item of card.evidence || []) if (!(item.id in map)) map[item.id] = next++;
        const add = ids => { for (const id of ids || []) if (!(id in map)) map[id] = next++; };
        add(card.summary && card.summary.evidence_ids);
        for (const c of card.safety_categories || []) add(c.evidence_ids);
        for (const entry of Object.values(card.comparison || {})) add(entry && entry.evidence_ids);
        for (const c of card.claims || []) add(c.evidence_ids);
        for (const f of card.findings || []) add(f.conditions && f.conditions.evidence_ids);
        for (const l of card.limitations || []) add(l.evidence_ids);
        for (const m of card.modeling_resources || []) add(m.evidence_ids);
        return map;
    }

    async function copyText(text, feedback) {
        let ok = false;
        try {
            if (global.navigator && navigator.clipboard) { await navigator.clipboard.writeText(text); ok = true; }
        } catch { ok = false; }
        if (!ok) {
            try {
                const area = h("textarea", { "aria-hidden": "true", class: "visually-hidden" });
                area.value = text;
                document.body.append(area);
                if (area.select) area.select();
                ok = typeof document.execCommand === "function" ? document.execCommand("copy") : false;
                area.remove();
            } catch { ok = false; }
        }
        if (feedback) feedback.textContent = ok ? "Copied." : "Copy failed; select the text and copy it manually.";
        return ok;
    }

    // ---------- Evidence dialog and citation markers ----------
    let numbering = {};
    const sourceCache = new Map();
    const ui = { dialog: null, controller: null, token: 0, opener: null, accession: null, ids: [], index: 0, context: "" };

    function numberFor(id, fallbackIndex) { return id in numbering ? numbering[id] : fallbackIndex + 1; }

    function citeMarkers(accession, ids, contextLabel) {
        const list = (ids || []).filter(Boolean);
        if (!list.length) return h("span", { class: "cite-missing" }, "[no evidence]");
        return h("sup", { class: "cite" }, list.map((id, index) => h("button", {
            type: "button", "aria-label": "Evidence " + numberFor(id, index) + (contextLabel ? " for " + contextLabel : ""),
            onclick: event => open(accession, list, contextLabel, index, event && event.target),
        }, "[" + numberFor(id, index) + "]")));
    }

    function getSource(accession) {
        if (!sourceCache.has(accession)) {
            sourceCache.set(accession, api("/api/studies/" + encodeURIComponent(accession))
                .then(result => result.meta.source || null)
                .catch(() => { sourceCache.delete(accession); return null; }));
        }
        return Promise.resolve(sourceCache.get(accession));
    }

    function ensureDialog() {
        if (ui.dialog) return ui.dialog;
        const dialog = h("dialog", { class: "dialog evidence-dialog", "aria-labelledby": "evidence-title" });
        ui.title = h("h2", { id: "evidence-title" }, "Evidence");
        ui.closeButton = FF.button("Close", () => dialog.close());
        ui.context = h("p", { class: "muted small" });
        ui.position = h("span", { class: "small muted", role: "status" });
        ui.prev = FF.button("Previous", () => step(-1));
        ui.next = FF.button("Next", () => step(1));
        ui.nav = h("div", { class: "cluster evidence-nav" }, ui.prev, ui.position, ui.next);
        ui.status = h("p", { class: "status", role: "status" });
        ui.excerpt = h("blockquote", { class: "excerpt" });
        ui.details = h("dl", { class: "meta-list" });
        ui.attribution = h("p", { class: "small muted" });
        ui.body = h("div", { class: "dialog-body" }, ui.context, ui.nav, ui.status, ui.excerpt, ui.details, ui.attribution);
        dialog.append(h("div", { class: "dialog-head" }, ui.title, ui.closeButton), ui.body);
        dialog.addEventListener("close", () => {
            // "close" is dispatched asynchronously; if a citation was opened again in the meantime,
            // this late event must not cancel the new request.
            if (dialog.open) return;
            if (ui.controller) ui.controller.abort();
            ui.token += 1;
            const opener = ui.opener;
            ui.opener = null;
            if (opener && typeof opener.focus === "function") opener.focus();
        });
        dialog.addEventListener("keydown", event => { if (event.key === "Escape") dialog.close(); });
        document.body.append(dialog);
        ui.dialog = dialog;
        return dialog;
    }

    function step(delta) {
        const next = ui.index + delta;
        if (next < 0 || next >= ui.ids.length) return;
        showCitation(next);
    }

    function resetBody() {
        ui.excerpt.replaceChildren();
        ui.excerpt.hidden = true;
        ui.details.replaceChildren();
        ui.attribution.replaceChildren();
    }

    async function showCitation(index) {
        ui.index = index;
        const id = ui.ids[index];
        if (ui.controller) ui.controller.abort();
        const controller = new AbortController();
        ui.controller = controller;
        const token = ++ui.token;
        resetBody();
        ui.position.textContent = "Citation " + (index + 1) + " of " + ui.ids.length;
        ui.prev.disabled = index === 0;
        ui.next.disabled = index === ui.ids.length - 1;
        ui.nav.hidden = ui.ids.length < 2;
        status(ui.status, "Loading evidence…", "loading");
        try {
            const { data } = await api("/api/evidence/" + encodeId(id), { signal: controller.signal });
            if (token !== ui.token) return;
            status(ui.status, "");
            ui.excerpt.hidden = false;
            ui.excerpt.textContent = data.excerpt;
            const idCell = h("dd", {}, h("span", { class: "id" }, data.id || id), " ",
                FF.button("Copy ID", event => copyText(data.id || id, copyNote), { class: "btn-link" }));
            const copyNote = h("span", { class: "small muted", role: "status" });
            idCell.append(" ", copyNote);
            ui.details.replaceChildren(
                h("dt", {}, "Location"), h("dd", {}, formatLocator(data.locator)),
                h("dt", {}, "Evidence ID"), idCell,
                h("dt", {}, "Investigation"), h("dd", {}, h("a", { href: FF.buildHash("study", [data.investigation || ui.accession]) }, data.investigation || ui.accession)),
                h("dt", {}, "Source"), h("dd", {}, FF.externalLink("Open the PSI source page", data.source_url)));
            const accession = data.investigation || ui.accession;
            ui.attribution.textContent = "Checking attribution…";
            const source = normalizeSource(await getSource(accession));
            if (token !== ui.token) return;
            if (source && source.investigators.length) {
                ui.attribution.textContent = "PSI investigators: " + source.investigators.map(p => p.name).join(", ") +
                    ". The cited document’s own authorship may differ; consult the source for its authors.";
            } else {
                ui.attribution.textContent = "Attribution metadata is not available from this server. Consult the PSI source page for the investigators and the document’s authors.";
            }
        } catch (error) {
            if (error.name === "AbortError" || token !== ui.token) return;
            resetBody();
            const message = error.status === 503 ? "The evidence text is unavailable."
                : error.status === 404 ? "Unknown evidence id." : error.message;
            status(ui.status, message + " (" + id + ")", "error");
        }
    }

    function open(accession, ids, contextLabel, startIndex = 0, opener) {
        const list = (ids || []).filter(Boolean);
        if (!list.length) return;
        const dialog = ensureDialog();
        ui.opener = opener || (document.activeElement && document.activeElement !== document.body ? document.activeElement : null);
        ui.accession = accession;
        ui.ids = list;
        ui.context.textContent = contextLabel ? "Cited in: " + contextLabel + " (" + accession + ")" : accession;
        ui.title.textContent = "Evidence " + numberFor(list[startIndex], startIndex);
        if (!dialog.open) dialog.showModal();
        showCitation(startIndex);
    }

    function setNumbering(map) { numbering = map || {}; }
    FF.evidence = { open, citeMarkers, setNumbering, setSource: (accession, source) => sourceCache.set(accession, Promise.resolve(source || null)),
        formatLocator };

    // ---------- Studies list ----------
    const selection = [];   // accessions ticked for comparison (max two), kept across searches
    const listState = { q: "", category: "", page: 1, controller: null, timer: null, pending: Promise.resolve(), nodes: null };

    function setSelection(accession, on) {
        const index = selection.indexOf(accession);
        if (on && index < 0 && selection.length < 2) selection.push(accession);
        if (!on && index >= 0) selection.splice(index, 1);
    }

    function renderCompareBar() {
        const nodes = listState.nodes;
        if (!nodes) return;
        nodes.bar.hidden = selection.length === 0;
        clear(nodes.bar);
        if (!selection.length) return;
        if (selection.length === 1) {
            nodes.bar.append(h("span", {}, "Selected ", h("span", { class: "id" }, selection[0]), ". Tick one more investigation to compare."),
                FF.button("Clear", () => { selection.length = 0; syncChecks(); }, { class: "btn-link" }));
        } else {
            nodes.bar.append(
                FF.button("Compare " + selection[0] + " and " + selection[1], () => FF.navigate("compare", [selection[0], selection[1]]), { class: "btn-primary" }),
                FF.button("Clear", () => { selection.length = 0; syncChecks(); }, { class: "btn-link" }));
        }
    }
    function syncChecks() {
        const nodes = listState.nodes;
        if (!nodes) return;
        for (const box of nodes.list.querySelectorAll("input")) {
            const accession = box.dataset.accession;
            box.checked = selection.includes(accession);
            box.disabled = !box.checked && selection.length >= 2;
        }
        renderCompareBar();
    }

    function studyItem(card, match, query) {
        const box = h("input", { type: "checkbox", dataset: { accession: card.accession },
            onchange: event => { setSelection(card.accession, event.target.checked); syncChecks(); } });
        const categories = (card.safety_categories || []).map(c => h("span", { class: "tag" }, FF.label("category", c.category)));
        const item = h("li", { class: "study-item" },
            h("h2", { class: "study-title" },
                h("a", { href: FF.buildHash("study", [card.accession]) }, card.title),
                card.acronym ? h("span", { class: "acronym" }, " (" + card.acronym + ")") : null),
            h("p", { class: "study-meta" },
                h("span", { class: "id" }, card.accession), " · ",
                "Source version " + card.source_version, " · ",
                FF.label("coverage", card.coverage), " · ", FF.reviewBadge(card.review && card.review.status),
                categories.length ? [" · ", h("span", { class: "tags tags-inline" }, categories)] : null),
            h("p", { class: "summary" }, card.summary ? card.summary.text : ""),
            h("label", { class: "check compare-check" }, box, "Compare"));
        if (query) {
            const passages = match && match.evidence ? match.evidence : [];
            const block = h("div", { class: "matches" });
            if (match) block.append(h("p", { class: "small muted" }, "Relevance rank " + match.rank));
            if (!passages.length) {
                block.append(h("p", { class: "small muted" }, "Matched on title or acronym; no evidence passage."));
            } else {
                block.append(h("ul", { class: "excerpt-list" }, passages.slice(0, 3).map(passage => h("li", {},
                    h("p", { class: "excerpt-text" }, highlight(excerptWindow(passage.excerpt, query), query)),
                    h("p", { class: "small muted" }, formatLocator(passage.locator), " · ",
                        FF.button("Open evidence", event => open(card.accession, [passage.id], "Search result", 0, event.target), { class: "btn-link" })))))
                );
                if (passages.length > 3) block.append(h("p", { class: "small muted" }, "and " + (passages.length - 3) + " more matching passages on the investigation page."));
            }
            item.append(block);
        }
        return item;
    }

    function load() {
        const nodes = listState.nodes;
        if (!nodes) return Promise.resolve();
        if (listState.controller) listState.controller.abort();
        const controller = new AbortController();
        listState.controller = controller;
        const state = { q: listState.q, category: listState.category, page: listState.page };
        status(nodes.count, "Loading investigations…", "loading");
        nodes.list.replaceChildren();
        nodes.pager.replaceChildren();
        nodes.note.hidden = true;
        listState.pending = (async () => {
            try {
                const { data, meta } = await api("/api/studies?" + listParams(state), { signal: controller.signal });
                if (controller !== listState.controller) return;
                renderList(data, meta, state);
            } catch (error) {
                if (error.name === "AbortError" || controller !== listState.controller) return;
                status(nodes.count, error.message, "error");
                nodes.list.replaceChildren();
            }
        })();
        return listState.pending;
    }

    function renderList(data, meta, state) {
        const nodes = listState.nodes;
        const query = (meta.query || "").trim();
        const total = meta.total;
        const categoryText = state.category ? " in " + FF.label("category", state.category).toLowerCase() : "";
        if (query) {
            status(nodes.count, total + (total === 1 ? " match for “" : " matches for “") + query + "”" + categoryText);
            nodes.note.hidden = false;
        } else {
            status(nodes.count, total + (total === 1 ? " investigation" : " investigations") + categoryText);
            nodes.note.hidden = true;
        }
        const matches = new Map((meta.matches || []).map(m => [m.accession, m]));
        if (!data.length) {
            nodes.list.append(h("li", { class: "empty" }, query
                ? "No investigations match “" + query + "”. Try fewer terms or clear the category filter."
                : "No investigations are available" + categoryText + "."));
        } else {
            for (const card of data) nodes.list.append(studyItem(card, matches.get(card.accession), query));
        }
        const limit = meta.limit || PAGE_SIZE, offset = meta.offset || 0;
        if (total > limit) {
            const last = Math.ceil(total / limit);
            nodes.pager.append(
                FF.button("Previous", () => goPage(state.page - 1), { disabled: state.page <= 1 }),
                h("span", { class: "range" }, "Showing " + (offset + 1) + "–" + Math.min(offset + data.length, total) + " of " + total),
                FF.button("Next", () => goPage(state.page + 1), { disabled: state.page >= last }));
        }
        syncChecks();
    }

    function pushUrl() {
        FF.replaceParams("studies", [], { q: listState.q, category: listState.category, page: listState.page > 1 ? listState.page : "" });
    }
    function goPage(page) {
        listState.page = Math.max(1, page);
        pushUrl();
        load();
        if (global.scrollTo) global.scrollTo(0, 0);
    }

    function readRoute(route) {
        const params = (route && route.params) || {};
        listState.q = (params.q || "").slice(0, 200);
        listState.category = CATEGORIES.includes(params.category) ? params.category : "";
        const page = parseInt(params.page, 10);
        listState.page = Number.isFinite(page) && page > 1 ? page : 1;
    }

    function syncControls() {
        const nodes = listState.nodes;
        nodes.input.value = listState.q;
        for (const radio of nodes.radios) radio.checked = radio.value === listState.category;
    }

    const studiesView = {
        mount(container, route) {
            readRoute(route);
            const input = h("input", { type: "search", id: "study-search", class: "search-lg", autocomplete: "off", maxlength: "200",
                placeholder: "e.g. extinction, methanol, SF6", oninput: event => {
                    listState.q = event.target.value.trim();
                    listState.page = 1;
                    pushUrl();
                    clearTimeout(listState.timer);
                    listState.timer = setTimeout(load, 300);
                } });
            const radios = [["", "All"], ...CATEGORIES.map(c => [c, FF.label("category", c)])].map(([value, text]) => {
                const radio = h("input", { type: "radio", name: "safety-category", value, onchange: () => {
                    listState.category = value;
                    listState.page = 1;
                    pushUrl();
                    load();
                } });
                return Object.assign(radio, { _wrap: h("label", { class: "check" }, radio, text) });
            });
            const nodes = {
                input, radios,
                count: h("p", { class: "status", role: "status", "aria-live": "polite" }),
                note: h("p", { class: "small muted" }, "Results are ordered by text relevance to the query. Relevance is not a measure of fire risk."),
                list: h("ol", { class: "study-list" }),
                pager: h("div", { class: "pagination" }),
                bar: h("div", { class: "compare-bar", role: "region", "aria-label": "Comparison selection" }),
            };
            nodes.note.hidden = true;
            listState.nodes = nodes;
            clear(container,
                h("header", { class: "page-head" },
                    h("h1", {}, "Investigations"),
                    h("p", { class: "lede" }, "NASA PSI microgravity combustion investigations with cited research cards. Search the evidence text or filter by fire-safety category.")),
                h("form", { class: "filters", role: "search", onsubmit: event => event.preventDefault() },
                    h("div", { class: "field" }, h("label", { for: "study-search" }, "Search investigations and evidence"), input),
                    h("fieldset", { class: "category-filter" }, h("legend", {}, "Safety category"),
                        h("div", { class: "cluster" }, radios.map(r => r._wrap)))),
                nodes.count, nodes.note, nodes.list, nodes.pager, nodes.bar);
            syncControls();
            renderCompareBar();
            load();
        },
        update(route) {
            readRoute(route);
            syncControls();
            load();
        },
        unmount() {
            clearTimeout(listState.timer);
            if (listState.controller) listState.controller.abort();
            listState.controller = null;
            listState.nodes = null;
        },
    };

    // ---------- Study detail ----------
    const detail = { controller: null, card: null, pending: Promise.resolve(), citeDialog: null };

    function cite(card, ids, label) { return citeMarkers(card.accession, ids, label); }

    function proseWithCites(card, text, ids, label) {
        return h("p", {}, text, " ", cite(card, ids, label));
    }

    function section(id, title, ...children) {
        return h("section", { class: "section", id }, h("h2", {}, title), ...children);
    }

    function claimLookup(card) { return new Map((card.claims || []).map(c => [c.id, c])); }

    function claimItem(card, claim) {
        return h("li", { class: "claim", id: "claim-" + claim.id },
            h("span", { class: "id claim-id" }, claim.id), " ",
            h("span", { class: "tag" }, FF.label("claim", claim.type)), " ",
            claim.text, " ", cite(card, claim.evidence_ids, "claim " + claim.id));
    }

    function claimsSection(card) {
        const groups = [
            ["Reported observations", ["reported_observation"], "Statements the cited sources report as having been observed or recorded."],
            ["Objectives and hypotheses (not results)", ["objective", "hypothesis", "approach"], "What the investigation set out to do or expected. These are not findings."],
            ["Expected impacts and potential applications (not results)", ["expected_impact", "potential_application"], "Anticipated uses or consequences stated by the sources. These are not findings."],
        ];
        const known = new Set(groups.flatMap(g => g[1]));
        const nodes = [];
        for (const [title, types, note] of groups) {
            const claims = (card.claims || []).filter(c => types.includes(c.type));
            if (!claims.length) continue;
            nodes.push(h("div", { class: "claim-group" }, h("h3", {}, title), h("p", { class: "small muted" }, note),
                h("ul", { class: "claims" }, claims.map(c => claimItem(card, c)))));
        }
        const other = (card.claims || []).filter(c => !known.has(c.type));
        if (other.length) nodes.push(h("div", { class: "claim-group" }, h("h3", {}, "Other statements (not results)"),
            h("ul", { class: "claims" }, other.map(c => claimItem(card, c)))));
        return section("claims", "Claims", nodes.length ? nodes : h("p", { class: "unknown" }, "No claims are recorded in this card."));
    }

    function findingsSection(card) {
        const claims = claimLookup(card);
        const claimText = id => {
            const claim = claims.get(id);
            return claim ? [h("a", { href: "#claim-" + id, class: "id", onclick: jump("claim-" + id) }, id), " ", claim.text, " ", cite(card, claim.evidence_ids, "claim " + id)]
                : [h("span", { class: "id" }, id || "—"), " ", h("span", { class: "unknown" }, "(claim not found in this card)")];
        };
        const items = (card.findings || []).map((finding, index) => h("li", { class: "finding" },
            h("p", {}, h("strong", {}, "Observation. "), claimText(finding.observation)),
            h("p", {}, h("strong", {}, "Conditions. "),
                finding.conditions ? [finding.conditions.text, " ", cite(card, finding.conditions.evidence_ids, "finding " + (index + 1) + " conditions")] : h("span", { class: "unknown" }, NOT_STATED)),
            finding.implication ? h("p", {}, h("strong", {}, "Implication (not a result). "), claimText(finding.implication)) : null,
            finding.category ? h("p", { class: "small muted" }, "Category: " + FF.label("category", finding.category)) : null));
        return section("findings", "Findings",
            h("p", { class: "small muted" }, "Each finding pairs a reported observation with the conditions it was reported under, and any implication the draft attaches."),
            items.length ? h("ol", { class: "findings" }, items) : h("p", { class: "unknown" }, "No findings are recorded in this card."));
    }
    function jump(id) {
        return event => {
            const target = document.getElementById ? document.getElementById(id) : null;
            if (target && target.scrollIntoView) { if (event && event.preventDefault) event.preventDefault(); target.scrollIntoView(); }
        };
    }

    function comparisonSection(card) {
        const rows = Object.keys(FF.LABELS.comparison).map(key => {
            const entry = card.comparison ? card.comparison[key] : null;
            return h("tr", {}, h("th", { scope: "row" }, FF.label("comparison", key)),
                entry ? h("td", {}, entry.text) : h("td", { class: "unknown" }, NOT_STATED),
                h("td", {}, entry ? cite(card, entry.evidence_ids, FF.label("comparison", key)) : null));
        });
        return section("attributes", "Comparison attributes",
            h("div", { class: "table-wrap" }, h("table", { class: "table attributes" },
                h("caption", {}, "As stated in the cited sources; a blank is not a measured absence."),
                h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Attribute"), h("th", { scope: "col" }, "Statement"), h("th", { scope: "col" }, "Evidence"))),
                h("tbody", {}, rows))));
    }

    function sourceSection(card, rawSource) {
        const source = normalizeSource(rawSource);
        if (!source) {
            return section("source", "Source and investigators",
                h("p", { class: "unknown" }, "Investigator and publication metadata are not available from this server."));
        }
        const rows = [];
        const row = (label, value) => { if (value) rows.push(h("dt", {}, label), h("dd", {}, value)); };
        row("DOI", source.doiUrl ? FF.externalLink(source.doi, source.doiUrl) : null);
        row("PSI page", FF.externalLink(source.psiUrl || FF.PSI_INVESTIGATION_URL + card.accession, source.psiUrl || FF.PSI_INVESTIGATION_URL + card.accession));
        row("License", source.license);
        row("Start date", source.startDate);
        row("End date", source.endDate);
        const nodes = [h("dl", { class: "meta-list" }, rows)];
        nodes.push(h("h3", {}, "Investigators"));
        nodes.push(source.investigators.length ? h("ul", { class: "people" }, source.investigators.map(p => h("li", {},
            h("strong", {}, p.name), p.role ? ", " + p.role : "", p.affiliation ? " (" + p.affiliation + ")" : "")))
            : h("p", { class: "unknown" }, "No investigators are listed."));
        nodes.push(h("h3", {}, "Publications"));
        nodes.push(source.publications.length ? h("ul", { class: "publications" }, source.publications.map(pub => {
            const authors = authorNames(pub);
            const doiUrl = pub.doi ? (/^https?:/i.test(pub.doi) ? pub.doi : "https://doi.org/" + pub.doi) : null;
            return h("li", {}, authors ? authors + ". " : "", pub.title || "Untitled", pub.year ? " (" + pub.year + ")" : "", ". ",
                doiUrl ? FF.externalLink("DOI", doiUrl) : (pub.url ? FF.externalLink("Link", pub.url) : null));
        })) : h("p", { class: "unknown" }, "No publications are listed."));
        return section("source", "Source and investigators", nodes);
    }

    function referencesSection(card) {
        const known = new Map((card.evidence || []).map(item => [item.id, item]));
        const entries = Object.entries(numbering).sort((a, b) => a[1] - b[1]);
        const items = entries.map(([id, number]) => {
            const item = known.get(id);
            const full = item ? item.excerpt || "" : "";
            const limit = 280;
            const text = h("span", { class: "ref-text" }, full.length > limit ? full.slice(0, limit).trimEnd() + " …" : full);
            const li = h("li", { id: "ref-" + number, class: "reference", value: number },
                h("span", { class: "ref-number num" }, "[" + number + "]"), " ",
                item ? [text, " "] : h("span", { class: "unknown" }, "This id is cited but not in the card’s evidence list. "),
                item && full.length > limit ? FF.button("show full", event => {
                    const expanded = event.target.getAttribute("aria-expanded") === "true";
                    text.textContent = expanded ? full.slice(0, limit).trimEnd() + " …" : full;
                    event.target.setAttribute("aria-expanded", expanded ? "false" : "true");
                    event.target.textContent = expanded ? "show full" : "show less";
                }, { class: "btn-link", "aria-expanded": "false" }) : null,
                h("div", { class: "small muted ref-meta" },
                    item ? [formatLocator(item.locator), " · "] : null,
                    h("span", { class: "id" }, id), " · ", h("a", { href: FF.buildHash("study", [id.split(":")[0]]) }, id.split(":")[0]),
                    item ? [" · ", FF.externalLink("PSI source", item.source_url)] : null,
                    " · ", FF.button("Open", event => open(card.accession, [id], "References", 0, event.target), { class: "btn-link" })));
            return li;
        });
        return section("references", "References",
            h("p", { class: "small muted" }, "All evidence excerpts cited by this card, numbered as the markers appear above. Excerpts are verbatim from the PSI source."),
            h("ol", { class: "references" }, items));
    }

    function openCiteDialog(card, source, snapshotDate, opener) {
        if (!detail.citeDialog) {
            const dialog = h("dialog", { class: "dialog cite-dialog", "aria-labelledby": "cite-title" });
            dialog.addEventListener("keydown", event => { if (event.key === "Escape") dialog.close(); });
            dialog.addEventListener("close", () => { const o = detail.citeOpener; if (o && o.focus) o.focus(); });
            document.body.append(dialog);
            detail.citeDialog = dialog;
        }
        const dialog = detail.citeDialog;
        detail.citeOpener = opener;
        const citation = buildCitation(card, source);
        const block = (title, text) => {
            const note = h("span", { class: "small muted", role: "status" });
            return h("div", { class: "cite-block" }, h("h3", {}, title),
                h("pre", { class: "cite-text" }, text),
                h("p", {}, FF.button("Copy", () => copyText(text, note)), " ", note));
        };
        const blocks = [block(citation.available ? "Dataset citation" : "Locator citation (PSI URL)", citation.text)];
        if (!citation.available) blocks.push(h("p", { class: "notice notice-warn" }, citation.reason));
        if (citation.bibtex) blocks.push(block("BibTeX", citation.bibtex));
        blocks.push(block("This tool’s card record", buildRecordCitation(card, snapshotDate)));
        clear(dialog,
            h("div", { class: "dialog-head" }, h("h2", { id: "cite-title" }, "Cite " + card.accession), FF.button("Close", () => dialog.close())),
            h("div", { class: "dialog-body" }, blocks));
        if (!dialog.open) dialog.showModal();
    }

    function renderDetail(container, card, meta) {
        detail.card = card;
        numbering = buildNumbering(card);
        const source = meta && meta.source ? meta.source : null;
        FF.evidence.setSource(card.accession, source);
        const review = card.review || {};
        const gen = card.generation || {};
        const reviewLine = h("p", { class: "review-line" }, FF.reviewBadge(review.status),
            review.status === "approved" && review.reviewer ? " by " + review.reviewer + (review.reviewed_at ? " on " + datePart(review.reviewed_at) : "") + "." : null,
            gen.generated_at || gen.model ? " Drafted with the " + (gen.skill || "research-card") + " skill" + (gen.model ? " (" + gen.model + ")" : "") + (gen.generated_at ? " on " + datePart(gen.generated_at) : "") + "." : null);
        const snapshotDate = FF.cache.health && FF.cache.health.snapshot_date;
        const actions = h("div", { class: "cluster actions no-print" },
            FF.button("Export card (JSON)", () => FF.download(exportFilename(card), exportText(card), "application/json")),
            FF.button("Cite", event => openCiteDialog(card, source, snapshotDate, event.target)),
            FF.button("Add to comparison", () => FF.navigate("compare", [card.accession])),
            h("a", { class: "btn", href: FF.buildHash("files", [card.accession]) }, "Browse files"),
            FF.externalLink("View on PSI", FF.PSI_INVESTIGATION_URL + card.accession, { class: "btn" }));
        const safety = card.safety_categories || [];
        clear(container,
            h("a", { class: "back", href: "#/studies" }, "← All investigations"),
            h("header", { class: "page-head study-head" },
                h("p", { class: "eyebrow" }, card.accession + " · source version " + card.source_version + " · " + FF.label("coverage", card.coverage)),
                h("h1", {}, card.title, card.acronym ? " (" + card.acronym + ")" : ""),
                reviewLine,
                h("p", { class: "notice" }, "The summary and the sections below are prepared content drafted from cited PSI evidence, stored with this snapshot. They are not generated when you open the page."),
                actions),
            section("summary", "Summary", h("div", { class: "prose" }, proseWithCites(card, card.summary ? card.summary.text : "", card.summary && card.summary.evidence_ids, "summary"))),
            section("safety", "Safety categories", safety.length ? h("ul", { class: "plain-list" }, safety.map(c => h("li", {},
                h("strong", {}, FF.label("category", c.category)), " ", cite(card, c.evidence_ids, FF.label("category", c.category) + " category"))))
                : h("p", { class: "unknown" }, "No fire-safety category is assigned in this card.")),
            comparisonSection(card),
            claimsSection(card),
            findingsSection(card),
            section("limitations", "Limitations", (card.limitations || []).length ? h("ul", { class: "limitations" }, card.limitations.map(item => h("li", {},
                h("span", { class: "tag" }, FF.label("limitationBasis", item.basis)), " ", item.text, " ", cite(card, item.evidence_ids, "limitation"))))
                : h("p", { class: "unknown" }, "No limitations are recorded in this card.")),
            section("modeling", "Modeling resources", (card.modeling_resources || []).length ? h("ul", { class: "resources" }, card.modeling_resources.map(res => h("li", {},
                res.description, " ", cite(card, res.evidence_ids, "modeling resource"),
                (res.file_keys || []).length ? h("ul", { class: "file-keys small" }, res.file_keys.map(key => {
                    const name = String(key).split("/").pop();
                    return h("li", {}, h("a", { href: FF.buildHash("files", [card.accession], { filename: name }) }, name));
                })) : null)))
                : h("p", { class: "unknown" }, "No modeling resources are recorded in this card.")),
            sourceSection(card, source),
            referencesSection(card));
        document.title = card.accession + " · Flame in Freefall";
    }

    const studyView = {
        mount(container, route) {
            const accession = route.args[0] || "";
            const back = h("a", { class: "back", href: "#/studies" }, "← All investigations");
            const note = h("p", { class: "status", role: "status" });
            clear(container, back, note);
            status(note, "Loading " + accession + "…", "loading");
            if (detail.controller) detail.controller.abort();
            const controller = new AbortController();
            detail.controller = controller;
            detail.pending = (async () => {
                try {
                    const { data, meta } = await api("/api/studies/" + encodeURIComponent(accession), { signal: controller.signal });
                    if (controller !== detail.controller) return;
                    renderDetail(container, data, meta);
                } catch (error) {
                    if (error.name === "AbortError" || controller !== detail.controller) return;
                    const message = error.status === 404 ? "No investigation with accession " + accession + " in this snapshot."
                        : error.status === 503 ? "Investigation data is unavailable from the local server" + (error.state ? " (" + error.state + ")" : "") + "."
                        : error.message;
                    status(note, message, "error");
                }
            })();
        },
        unmount() {
            if (detail.controller) detail.controller.abort();
            detail.controller = null;
            detail.card = null;
            numbering = {};
        },
    };

    FF.views.studies = studiesView;
    FF.views.study = studyView;
    FF.studies = {
        highlight, excerptWindow, queryTerms, listParams, formatLocator, normalizeSource, buildCitation, buildRecordCitation,
        exportFilename, exportText, buildNumbering,
        idle: () => Promise.all([listState.pending, detail.pending]),
        state: listState,
        selection,
    };
})(typeof window !== "undefined" ? window : globalThis);
