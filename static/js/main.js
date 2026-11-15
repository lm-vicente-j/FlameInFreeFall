// Boot: header status, navigation and hash routing. Loaded last.
(function (global) {
    "use strict";
    const FF = global.FF;
    const { h, clear, api, status } = FF;
    const NAV = [
        ["studies", "Investigations"],
        ["compare", "Compare"],
        ["conditions", "Condition explorer"],
        ["files", "Files"],
        ["about", "About the data"],
    ];
    // Views that own a detail route map back to their navigation entry.
    const NAV_ALIAS = { study: "studies" };

    async function loadHealth() {
        const node = document.getElementById("snapshot-status");
        try {
            const { data } = await api("/api/health");
            FF.cache.health = data;
            const count = value => value === null || value === undefined ? "unavailable" : FF.formatNumber(value);
            clear(node,
                "PSI snapshot ", h("strong", {}, data.snapshot_date || "date unavailable"), " · ",
                count(data.investigation_count), " investigations · ",
                count(data.run_record_count), " source rows (",
                count(data.verified_run_count), " reviewed runs)",
                data.readiness !== "ready" ? h("span", { class: "status-error" }, " · service " + data.readiness) : null);
            const footer = document.getElementById("footer-snapshot");
            if (footer) footer.textContent = data.snapshot_date || "unavailable";
        } catch (error) {
            status(node, error.message, "error");
        }
    }

    function renderNav(active) {
        const nav = document.getElementById("site-nav");
        clear(nav, h("ul", {}, NAV.map(([view, text]) => h("li", {},
            h("a", { href: "#/" + view, "aria-current": view === active ? "page" : null }, text)))));
    }

    let current = null;
    function route() {
        const parsed = FF.parseHash(global.location.hash);
        let view = parsed.view;
        if (!FF.views[view]) view = "studies";
        const navKey = NAV_ALIAS[view] || view;
        renderNav(navKey);
        const main = document.getElementById("view");
        const key = view + "/" + parsed.args.join("/");
        // Re-mount on path change; views handle param-only changes themselves via update().
        if (current && current.key === key && FF.views[view].update) {
            FF.views[view].update(parsed);
            return;
        }
        if (current && FF.views[current.view] && FF.views[current.view].unmount) {
            FF.views[current.view].unmount();
        }
        current = { key, view };
        clear(main);
        main.dataset.view = view;
        FF.views[view].mount(main, parsed);
        const title = NAV.find(([name]) => name === navKey);
        document.title = (title ? title[1] + " · " : "") + "Flame in Freefall";
        if (!parsed.params._keepScroll) global.scrollTo(0, 0);
    }

    document.addEventListener("DOMContentLoaded", () => {
        loadHealth();
        global.addEventListener("hashchange", route);
        route();
    });
    FF.route = route;
})(window);
