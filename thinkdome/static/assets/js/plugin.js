/**
 * plugin.js — ThinkDome Frontend Plugin Architecture
 * Allows pluggable applications to dynamically add custom routes, dashboard widgets, and pages.
 */

window.ThinkDomePlugin = {
    pages: [],
    widgets: [],
    routes: [],
    menus: [],

    registerPage(name, iconSvg, renderFn) {
        this.pages.push({ name, icon: iconSvg, render: renderFn });
        console.log(`[Frontend Plugin] Registered Page: ${name}`);
    },

    registerWidget(name, renderFn) {
        this.widgets.push({ name, render: renderFn });
        console.log(`[Frontend Plugin] Registered Widget: ${name}`);
    },

    registerRoute(path, renderFn) {
        this.routes.push({ path, render: renderFn });
        console.log(`[Frontend Plugin] Registered Route: ${path}`);
    },

    registerMenu(label, path, iconSvg) {
        this.menus.push({ label, path, icon: iconSvg });
        console.log(`[Frontend Plugin] Registered Menu Link: ${label}`);
    }
};
