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

function optionsEditor(initial) {
    let seq = 0;
    const mk = (o) => {
        const dt = (o && o.datetime_value) || "";
        return {
            _uid: ++seq,
            type: (o && o.type) || "DATE",
            date_value: (o && o.date_value) || "",
            datetime_date: dt.length >= 10 ? dt.slice(0, 10) : "",
            datetime_hour: dt.length >= 13 ? dt.slice(11, 13) : "10",
            text_value: (o && o.text_value) || "",
        };
    };
    return {
        options: (initial || []).map(mk),
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
            this.options.push(mk());
        },
        remove(i) {
            this.options.splice(i, 1);
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
                return base;
            }));
        },
    };
}
