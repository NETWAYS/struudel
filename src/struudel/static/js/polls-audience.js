// Alpine factory used by polls/audience.html.

function audienceEditor(initialUsers, initialGroups) {
    return {
        users: initialUsers || [],
        groups: initialGroups || [],
        userSearchOpen: false,
        groupSearchOpen: false,
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
    };
}
