// "About the data": methods, definitions, limits, programmatic access and citation guidance.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h } = FF;

    function section(id, title, ...children) {
        return h("section", { class: "section", id: "about-" + id, "aria-labelledby": "about-" + id + "-h" },
            h("h2", { id: "about-" + id + "-h" }, title), ...children);
    }
    function definitions(rows) {
        return h("dl", { class: "meta-list about-defs" }, rows.map(([term, text]) => [h("dt", {}, term), h("dd", {}, text)]));
    }
    function apiRow(path, description) {
        return h("tr", {}, h("td", {}, h("code", {}, path)), h("td", {}, description));
    }

    function mount(container) {
        const snapshot = h("span", {}, FF.cache.health?.snapshot_date || "…");
        if (!FF.cache.health) {
            FF.api("/api/health").then(({ data }) => { snapshot.textContent = data.snapshot_date || "an unrecorded date"; })
                .catch(() => { snapshot.textContent = "an unavailable date"; });
        }
        const toc = [["scope", "Scope"], ["cards", "Investigation records"], ["runs", "Source rows and conditions"],
            ["review", "Review states"], ["comparison", "Comparing runs"], ["gaps", "Coverage and gaps"],
            ["limits", "What this tool does not do"], ["api", "Programmatic access"], ["cite", "Citing"]];

        container.append(
            h("div", { class: "page-head" },
                h("h1", {}, "About the data"),
                h("p", { class: "lede" }, "How the records in this explorer were prepared, what each label means, " +
                    "and which conclusions the data can and cannot support.")),
            h("nav", { class: "about-toc", "aria-label": "On this page" },
                h("ol", {}, toc.map(([id, text]) => h("li", {}, h("a", { href: "#/about", "data-target": "about-" + id,
                    onclick: event => { event.preventDefault(); document.getElementById("about-" + id).scrollIntoView(); } }, text))))),

            section("scope", "Scope",
                h("div", { class: "prose" },
                    h("p", {}, "The explorer covers 24 combustion investigations from NASA Physical Sciences Informatics (PSI), " +
                        "retrieved on ", snapshot, ". It works offline from that saved snapshot; it does not query PSI at run time. " +
                        "Links to PSI and DOI landing pages need a network connection."),
                    h("p", {}, "It holds three kinds of record: an investigation record (research card) per investigation, " +
                        "the evidence excerpts those records cite, and every non-empty row of the 22 PSI experimental tables, " +
                        "normalized into source rows with conditions, outcomes and provenance. The PSI file inventory " +
                        "(about 61,000 entries) is browsable but its files were not all downloaded or processed."))),

            section("cards", "Investigation records",
                h("div", { class: "prose" },
                    h("p", {}, "Each record was drafted with an AI model from a fixed evidence packet (PSI metadata, " +
                        "extracted passages from a sample of documents, and citable table rows), validated automatically, " +
                        "and then reviewed by a person. The reviewer and review date are shown on each record. " +
                        "Nothing is generated while you use the explorer."),
                    h("p", {}, "Every summary sentence, claim, comparison attribute, finding and limitation cites one or more " +
                        "evidence excerpts. Select a citation number to read the exact excerpt with its locator " +
                        "(metadata field, PDF page or table row) and a link to the source.")),
                definitions([
                    ["Reported observation", "A result stated by the source authors. Only these are presented as results."],
                    ["Objective, approach, hypothesis", "What the investigation set out to do or expected. Not a result."],
                    ["Expected impact, potential application", "The authors' stated relevance. Not a demonstrated outcome."],
                    ["Limitation", "A constraint stated by the source, or a gap in the evidence available for this record."],
                    ["Coverage", "Whether the record draws on metadata only or also on processed documents and tables."],
                ])),

            section("runs", "Source rows and conditions",
                h("div", { class: "prose" },
                    h("p", {}, "A source row is one non-empty row of an experimental table. Most are individual runs, but some " +
                        "are ranges (sweeps), session summaries or notes; the Kind column says which. Counts therefore refer " +
                        "to source rows, not to verified experiments, unless labelled as reviewed runs."),
                    h("p", {}, "Oxygen is given as percent by volume and pressure in kPa (converted from the source unit; " +
                        "the record keeps the conversion note). Flow is in cm/s. A sweep keeps one inclusive minimum–maximum " +
                        "interval; steps between the endpoints are not invented. Missing values stay unknown and are never " +
                        "replaced by defaults. A recorded zero is a value.")),
                definitions([
                    ["Parsed from table", "Read directly from a numeric or categorical table cell."],
                    ["Mapped via reviewed alias", "Short repeated text (for example a material name) mapped through an alias a person approved."],
                    ["AI-extracted", "Extracted from free text (BASS observations) by an AI model; the source text is shown with the value, together with its review state."],
                    ["Set by curator", "An investigation-level constant stated in the source, such as FLEX burning isolated droplets."],
                    ["Not recorded", "The table does not record this condition or outcome."],
                    ["Gravity", "Attached to each outcome, not to the row. Normal-gravity results are labelled “1 g ground test”; " +
                        "in Saffire-II they are paired with microgravity results. There is no gravity filter for this reason."],
                    ["BASS and BASS-II flow", "Instrument display readings. A physical velocity needs the fan calibration matched by test date " +
                        "and restrictor count; the 2014 calibration does not establish 2012–2013 velocities, so those readings remain uncalibrated."],
                ])),

            section("review", "Review states",
                h("p", {}, "Review state is shown next to every record and value."),
                h("dl", { class: "meta-list about-defs" },
                    h("dt", {}, FF.reviewBadge("approved")), h("dd", {}, "A person reviewed the record or value."),
                    h("dt", {}, FF.reviewBadge("pending")), h("dd", {}, "Proposed but not yet reviewed. Shown for transparency; not used as a reviewed result or as verified coverage."),
                    h("dt", {}, FF.reviewBadge("not_required")), h("dd", {}, "Parsed directly from the table or set from a stated investigation-level constant; no interpretation needed review."),
                    h("dt", {}, FF.reviewBadge("rejected")), h("dd", {}, "Reviewed and rejected; excluded from results."))),

            section("comparison", "Comparing runs",
                h("div", { class: "prose" },
                    h("p", {}, "Runs are compared quantitatively only within a condition group whose fuel class, material, geometry, " +
                        "flow direction and hardware are all known and equal. Groups that differ in any of these are incompatible; " +
                        "groups with an unknown attribute are indeterminate. The explorer does not rank runs by distance to a " +
                        "scenario and does not treat different hardware as equivalent."),
                    h("p", {}, "The investigation comparison view places two records' cited statements side by side. " +
                        "It does not normalize, merge or judge them."))),

            section("gaps", "Coverage and gaps",
                h("div", { class: "prose" },
                    h("p", {}, "Numeric filters match by inclusive overlap: a sweep from 18% to 25% O₂ matches a filter of 21–30%. " +
                        "The coverage summary reports one of four states for the active filters:")),
                definitions([
                    ["Covered", "Reviewed source rows with the required conditions match the filters."],
                    ["Pending review", "Matching or potentially matching rows rely on proposals not yet reviewed, so no definite answer is given."],
                    ["Unknown conditions", "Rows exist but lack the condition values needed to decide."],
                    ["Not in PSI", "No row of the saved PSI tables covers the filters and ranges."],
                ]),
                h("div", { class: "notice notice-gap" },
                    h("p", {}, "“Not in PSI” describes the saved PSI snapshot only. It does not establish whether the scenario " +
                        "has been studied elsewhere, whether it is safe, or what would happen. Saffire-IV–VI and SoFIE results " +
                        "outside PSI are not verified here."))),

            section("limits", "What this tool does not do",
                h("ul", { class: "prose" },
                    h("li", {}, "It does not predict fire behaviour, estimate risk or simulate scenarios."),
                    h("li", {}, "Search relevance reflects text matching, not fire risk or scientific importance."),
                    h("li", {}, "It does not answer questions with generated text; all text was prepared and reviewed beforehand."),
                    h("li", {}, "It does not read scanned documents (no OCR) or video."),
                    h("li", {}, "A catalogued file is listed in the PSI inventory; that does not mean its contents were processed."))),

            section("api", "Programmatic access",
                h("p", { class: "prose" }, "The explorer is a thin layer over a local JSON API. Every response has " +
                    h("code", {}, "data"), " and ", h("code", {}, "meta"), "; lists accept ", h("code", {}, "limit"),
                    " (1–100) and ", h("code", {}, "offset"), ". Evidence identifiers contain ", h("code", {}, "#"),
                    ", which must be percent-encoded as ", h("code", {}, "%23"), "."),
                h("div", { class: "table-wrap" }, h("table", { class: "table" },
                    h("thead", {}, h("tr", {}, h("th", {}, "Endpoint"), h("th", {}, "Returns"))),
                    h("tbody", {},
                        apiRow("/api/studies?q=extinction&safety_category=suppression", "Investigation records matching a full-text query, with matching excerpts"),
                        apiRow("/api/studies/PSI-69", "One investigation record; meta carries source and investigator metadata"),
                        apiRow("/api/evidence/PSI-69%3Ameta%3Aobjective%23f4c7ee946a30", "One evidence excerpt with its locator and source URL"),
                        apiRow("/api/studies/PSI-69/files?category=Experimental%20table", "Catalogued PSI files for an investigation"),
                        apiRow("/api/runs?fuel_class=solid&o2_min=21&o2_max=30", "Source rows matching typed condition filters"),
                        apiRow("/api/runs/PSI-69%3Aflex%3A1", "One source row with its table provenance"),
                        apiRow("/api/coverage?fuel_class=solid", "Counts, coverage state and condition groups for the filters"),
                        apiRow("/api/health", "Snapshot date, loaded counts and service readiness")))),
                h("p", { class: "small muted" }, "Every view's state is in its URL, so a search, a comparison or a filtered " +
                    "set of runs can be bookmarked or shared. Tables and records can be downloaded as CSV or JSON from their views.")),

            section("cite", "Citing",
                h("div", { class: "prose" },
                    h("p", {}, "Cite the original PSI dataset for any data you use: each investigation page offers a citation " +
                        "built from its PSI metadata (investigators, title, accession, version and DOI). PSI data are released " +
                        "under the licence stated on each investigation, usually CC0 1.0."),
                    h("p", {}, "When you rely on a prepared record from this explorer, also state the accession, record version, " +
                        "review state and snapshot date, and check the cited excerpts against the source."))));
    }

    FF.views.about = { mount };
})(window);
