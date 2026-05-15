// Show a spinner while the OIDC redirect runs.

document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("login-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
        this.classList.add("hidden");
        const spinner = document.getElementById("login-spinner");
        if (spinner) {
            spinner.classList.remove("hidden");
            spinner.classList.add("flex");
        }
    });
});
