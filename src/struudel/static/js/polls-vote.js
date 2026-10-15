// Alpine factory used by polls/vote.html.
//
// Single config-object argument so call-sites are explicit and field-order
// changes can't silently swap meanings.
//
// Required keys:
//   mode            "YES_NO_MAYBE" | "SINGLE_CHOICE" | "MULTI_CHOICE"
//   options         [{id, group_id, group_name, group_max_selections, ...}, ...] — order does not matter
//   initialVotes    { [optId]: "YES" | "MAYBE" | "NO" }
//   initialGuests   { [optId]: number }   — 0 if unset
//   maxYes          number | null         — only used in MULTI_CHOICE
//   allowGuests     boolean
//   maxGuests       number | null         — null means unlimited
//
// Option groups cap how many YES votes a voter may cast among a poll
// author-defined subset of options (e.g. "max 1 of A and B"), independent
// of `mode`/`maxYes` — the two mechanisms are enforced separately.

function voteEditor({ mode, options, initialVotes, initialGuests, maxYes, allowGuests, maxGuests }) {
    const votes = {};
    const guests = {};
    const groupByOption = {};
    options.forEach((o) => {
        votes[o.id] = initialVotes[o.id] || "NO";
        guests[o.id] = initialGuests[o.id] || 0;
        groupByOption[o.id] = {
            id: o.group_id,
            name: o.group_name,
            max: o.group_max_selections,
        };
    });
    return {
        mode,
        maxYes,
        allowGuests,
        maxGuests,
        votes,
        guests,
        groupYesCount(groupId) {
            return Object.entries(this.votes).filter(
                ([id, status]) => status === "YES" && groupByOption[id].id === groupId,
            ).length;
        },
        canSelectGroup(id) {
            // A single YES can never exceed a cap, and blocking here would
            // prevent switching between members of a group capped at 1.
            if (this.mode === "SINGLE_CHOICE") return true;
            const group = groupByOption[id];
            if (!group || group.id === null || !group.max) return true;
            if (this.votes[id] === "YES") return true;
            return this.groupYesCount(group.id) < group.max;
        },
        set(id, status) {
            if (status === "YES" && !this.canSelectGroup(id)) return;
            if (this.mode === "SINGLE_CHOICE" && status === "YES") {
                for (const k of Object.keys(this.votes)) {
                    this.votes[k] = "NO";
                    this.guests[k] = 0;
                }
            }
            if (this.mode === "MULTI_CHOICE" && status === "YES" && this.maxYes) {
                const count = Object.values(this.votes).filter((v) => v === "YES").length;
                if (count >= this.maxYes && this.votes[id] !== "YES") return;
            }
            this.votes[id] = status;
            if (status !== "YES") this.guests[id] = 0;
        },
        toggle(id) {
            this.set(id, this.votes[id] === "YES" ? "NO" : "YES");
        },
        clampGuests(id) {
            let n = Number(this.guests[id]) || 0;
            if (n < 0) n = 0;
            if (this.maxGuests && n > this.maxGuests) n = this.maxGuests;
            this.guests[id] = n;
        },
        yesCount() {
            return Object.values(this.votes).filter((v) => v === "YES").length;
        },
        canSelect(id) {
            if (!this.canSelectGroup(id)) return false;
            if (this.mode !== "MULTI_CHOICE" || !this.maxYes) return true;
            if (this.votes[id] === "YES") return true;
            return this.yesCount() < this.maxYes;
        },
        limitReached() {
            return this.mode === "MULTI_CHOICE" && this.maxYes && this.yesCount() >= this.maxYes;
        },
        groupsSummary() {
            if (this.mode === "SINGLE_CHOICE") return [];
            const seen = new Set();
            const summary = [];
            for (const o of options) {
                if (o.group_id === null || !o.group_max_selections || seen.has(o.group_id)) continue;
                seen.add(o.group_id);
                summary.push({
                    id: o.group_id,
                    name: o.group_name,
                    max: o.group_max_selections,
                    count: this.groupYesCount(o.group_id),
                });
            }
            return summary;
        },
        serialize() {
            return JSON.stringify(
                Object.entries(this.votes).map(([option_id, status]) => ({
                    option_id: Number(option_id),
                    status,
                    guest_count: status === "YES" ? Number(this.guests[option_id]) || 0 : 0,
                })),
            );
        },
    };
}
