// Site-wide JS bridge code, loaded on every page from base.html.
// Bundles cross-cutting glue: HTMX/CSRF/Alpine integration and a generic
// confirmation helper that replaces inline `onsubmit="return confirm(...)"`.

(function () {
    "use strict";

    // HTMX → CSRF: attach the token from the <meta> tag to every HTMX request.
    document.body.addEventListener("htmx:configRequest", function (e) {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) {
            e.detail.headers["X-CSRFToken"] = meta.content;
        }
    });

    // HTMX → Alpine: re-initialize Alpine on swapped subtrees so directives
    // inside server-rendered partials become reactive.
    document.body.addEventListener("htmx:afterSettle", function (e) {
        if (window.Alpine) {
            window.Alpine.initTree(e.detail.target);
        }
    });

    // Generic confirm-on-submit. Replaces `<form onsubmit="return confirm(...)">`.
    // Usage: <form data-confirm="Are you sure?">…</form>
    document.addEventListener("submit", function (e) {
        const form = e.target;
        if (!(form instanceof HTMLFormElement)) return;
        const msg = form.dataset.confirm;
        if (msg && !window.confirm(msg)) {
            e.preventDefault();
        }
    });
})();
