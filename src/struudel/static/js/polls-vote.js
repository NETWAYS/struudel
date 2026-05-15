// Alpine factory used by polls/vote.html.
//
// Single config-object argument so call-sites are explicit and field-order
// changes can't silently swap meanings.
//
// Required keys:
//   mode            "YES_NO_MAYBE" | "SINGLE_CHOICE" | "MULTI_CHOICE"
//   options         [{id, ...}, ...] — order does not matter
//   initialVotes    { [optId]: "YES" | "MAYBE" | "NO" }
//   initialGuests   { [optId]: number }   — 0 if unset
//   maxYes          number | null         — only used in MULTI_CHOICE
//   allowGuests     boolean
//   maxGuests       number | null         — null means unlimited

function voteEditor({ mode, options, initialVotes, initialGuests, maxYes, allowGuests, maxGuests }) {
    const votes = {};
    const guests = {};
    options.forEach((o) => {
        votes[o.id] = initialVotes[o.id] || "NO";
        guests[o.id] = initialGuests[o.id] || 0;
    });
    return {
        mode,
        maxYes,
        allowGuests,
        maxGuests,
        votes,
        guests,
        set(id, status) {
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
            if (this.mode !== "MULTI_CHOICE" || !this.maxYes) return true;
            if (this.votes[id] === "YES") return true;
            return this.yesCount() < this.maxYes;
        },
        limitReached() {
            return this.mode === "MULTI_CHOICE" && this.maxYes && this.yesCount() >= this.maxYes;
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
