// Alpine factories used by polls/edit.html.
// Loaded as an external script so the page itself doesn't need inline JS
// (keeps `script-src` CSP free of `'unsafe-inline'`).

// Splits a datetime-local string into a date + hour pair so users never see
// a minute spinner. Re-combines into "YYYY-MM-DDTHH:00" for form submission.
function dateHourPicker(initial) {
    let date = "";
    let hour = "";
    if (initial && initial.length >= 13) {
        date = initial.slice(0, 10);
        hour = initial.slice(11, 13);
    }
    return {
        date,
        hour,
        init() {
            this.$watch("date", (newDate, oldDate) => {
                if (newDate && !oldDate && !this.hour) {
                    this.hour = "10";
                }
            });
        },
        clear() {
            this.date = "";
            this.hour = "";
        },
        combined() {
            if (!this.date) return "";
            return this.date + "T" + (this.hour || "00") + ":00";
        },
    };
}

function optionsEditor(initial, initialGroups) {
    let seq = 0;
    let groupSeq = 0;
    const mkGroup = (g) => ({
        _uid: ++groupSeq,
        // Not derived from groupSeq: it restarts on every re-render, while
        // keys of new groups survive a rejected submit via the form payload.
        clientKey: (g && g.client_key) || `new-${crypto.randomUUID()}`,
        name: (g && g.name) || "",
        maxSelections: (g && g.max_selections) || null,
    });
    const optionGroups = (initialGroups || []).map(mkGroup);
    const groupUidByClientKey = {};
    optionGroups.forEach((g) => {
        groupUidByClientKey[g.clientKey] = g._uid;
    });

    const mk = (o) => {
        const dt = (o && o.datetime_value) || "";
        const groupClientKey = (o && o.group_client_key) || null;
        return {
            _uid: ++seq,
            type: (o && o.type) || "DATE",
            date_value: (o && o.date_value) || "",
            datetime_date: dt.length >= 10 ? dt.slice(0, 10) : "",
            datetime_hour: dt.length >= 13 ? dt.slice(11, 13) : "10",
            text_value: (o && o.text_value) || "",
            group_uid: groupClientKey ? groupUidByClientKey[groupClientKey] ?? null : null,
        };
    };
    return {
        options: (initial || []).map(mk),
        optionGroups,
        init() {
            this.$watch("options", (val) => {
                this.$dispatch("options-count-changed", { count: val.length });
            });
            this.$nextTick(() => {
                Sortable.create(this.$refs.list, {
                    handle: ".handle",
                    animation: 150,
                    onEnd: (e) => {
                        if (e.oldIndex === e.newIndex) return;
                        const [moved] = this.options.splice(e.oldIndex, 1);
                        this.options.splice(e.newIndex, 0, moved);
                    },
                });
            });
        },
        add() {
            const above = this.options[this.options.length - 1];
            const newOption = mk(above ? { type: above.type } : null);
            newOption.group_uid = above ? above.group_uid : null;
            this.options.push(newOption);
        },
        remove(i) {
            this.options.splice(i, 1);
        },
        addGroup() {
            this.optionGroups.push(mkGroup());
        },
        // Matches the server-side FK (ON DELETE SET NULL): removing a group
        // ungroups its member options rather than deleting them.
        removeGroup(gUid) {
            this.options.forEach((o) => {
                if (o.group_uid === gUid) o.group_uid = null;
            });
            this.optionGroups = this.optionGroups.filter((g) => g._uid !== gUid);
        },
        groupFor(opt) {
            return this.optionGroups.find((g) => g._uid === opt.group_uid) || null;
        },
        serializeGroups() {
            return JSON.stringify(this.optionGroups.map((g) => ({
                client_key: g.clientKey,
                name: g.name,
                max_selections: g.maxSelections || null,
            })));
        },
        serialize() {
            return JSON.stringify(this.options.map((o) => {
                const base = { type: o.type };
                if (o.type === "DATE") base.date_value = o.date_value || null;
                if (o.type === "DATETIME") {
                    base.datetime_value = o.datetime_date
                        ? o.datetime_date + "T" + (o.datetime_hour || "00") + ":00"
                        : null;
                }
                if (o.type === "TEXT") base.text_value = o.text_value || null;
                const group = this.groupFor(o);
                base.group_client_key = group ? group.clientKey : null;
                return base;
            }));
        },
    };
}

// The single Alpine component for the whole edit form. Owns:
//  - top-level form state (status, visibility, mandatory, ...)
//  - the inline audience picker state (users/groups + search dropdowns)
//  - save-button gating logic
function pollEditor(initial) {
    return {
        ...initial,
        users: initial.initialUsers || [],
        groups: initial.initialGroups || [],
        userSearchOpen: false,
        groupSearchOpen: false,
        // Audience picker is auto-expanded on PRIVATE (mandatory) or when an
        // audience already exists; on a fresh PUBLIC poll it starts collapsed
        // to reduce visual noise — user can opt in via the compact toggle.
        audienceExpanded:
            initial.visibility === "PRIVATE" ||
            (initial.initialUsers || []).length > 0 ||
            (initial.initialGroups || []).length > 0,
        statusHelp: {
            DRAFT: "Hidden from the audience. Saved but not yet open for voting.",
            ACTIVE: "Open for voting. Audience members can submit responses.",
            CLOSED: "No more votes accepted. Results remain visible.",
        },
        // Forward-only lifecycle: DRAFT → ACTIVE → CLOSED. For new polls
        // (originalStatus == null) CLOSED is also blocked — you can't create
        // an already-closed poll.
        statusAllowed(target) {
            const from = this.originalStatus;
            if (from === null) return target === "DRAFT" || target === "ACTIVE";
            if (from === "DRAFT") return target === "DRAFT" || target === "ACTIVE";
            if (from === "ACTIVE") return target === "ACTIVE" || target === "CLOSED";
            if (from === "CLOSED") return target === "CLOSED";
            return false;
        },
        visibilityHelp: {
            PRIVATE: "Only invited users or groups can see and vote.",
            PUBLIC: "Visible to everyone signed in. Anyone in the audience below still gets an invitation email.",
        },
        modeHelp: {
            YES_NO_MAYBE: "Voters mark each option as Yes, Maybe, or No.",
            SINGLE_CHOICE: "Voters pick exactly one option.",
            MULTI_CHOICE: "Voters pick any number of options (with optional cap).",
        },
        addUser(u) {
            if (!u || !u.id) return;
            if (!this.users.find((x) => x.id === u.id)) {
                this.users.push({
                    id: u.id,
                    label: u.label || "",
                    sublabel: u.sublabel || "",
                });
            }
            this.userSearchOpen = false;
            if (this.$refs.userSearchInput) {
                this.$refs.userSearchInput.value = "";
            }
            const dropdown = document.getElementById("user-search-results");
            if (dropdown) dropdown.innerHTML = "";
        },
        addGroup(g) {
            if (!g || !g.id) return;
            if (!this.groups.find((x) => x.id === g.id)) {
                this.groups.push({
                    id: g.id,
                    label: g.label || "",
                    sublabel: g.sublabel || "",
                });
            }
            this.groupSearchOpen = false;
            if (this.$refs.groupSearchInput) {
                this.$refs.groupSearchInput.value = "";
            }
            const dropdown = document.getElementById("group-search-results");
            if (dropdown) dropdown.innerHTML = "";
        },
        removeUser(id) {
            this.users = this.users.filter((x) => x.id !== id);
        },
        removeGroup(id) {
            this.groups = this.groups.filter((x) => x.id !== id);
        },
        serializeUsers() {
            return JSON.stringify(this.users.map((x) => ({ id: x.id })));
        },
        serializeGroups() {
            return JSON.stringify(this.groups.map((x) => ({ id: x.id })));
        },
        saveBlocked() {
            if (this.status !== "ACTIVE") return false;
            if (!this.hasOptions) return true;
            if (this.visibility === "PRIVATE" && this.users.length === 0 && this.groups.length === 0) {
                return true;
            }
            return false;
        },
        saveBlockedReason() {
            if (this.status === "ACTIVE" && !this.hasOptions) {
                return "Add at least one option to activate this poll.";
            }
            if (
                this.status === "ACTIVE" &&
                this.visibility === "PRIVATE" &&
                this.users.length === 0 &&
                this.groups.length === 0
            ) {
                return "Invite at least one user or group to activate this private poll.";
            }
            return "";
        },
    };
}
