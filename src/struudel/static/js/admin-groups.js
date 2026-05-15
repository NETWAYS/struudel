// Alpine factory used by admin/groups.html.
// Pure client-side filter — all rows stay in the DOM so the single-submit
// "save all" semantics keep working. We only toggle visibility.

function groupsFilter(initialQ, initialVisibility) {
    return {
        q: initialQ || "",
        visibility: initialVisibility || "all", // "all" | "visible" | "hidden"

        rowMatches(ds) {
            const qLower = this.q.trim().toLowerCase();
            if (qLower) {
                const inCanonical = ds.canonical.toLowerCase().includes(qLower);
                const inAlias = ds.alias.toLowerCase().includes(qLower);
                if (!inCanonical && !inAlias) return false;
            }
            if (this.visibility === "all") return true;
            const isHidden = ds.hidden === "true";
            return this.visibility === "hidden" ? isHidden : !isHidden;
        },
    };
}
