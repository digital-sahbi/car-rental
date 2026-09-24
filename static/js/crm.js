/* Smart Rent Car — small UI helpers. No framework required. */
(function () {
    "use strict";

    /** Mobile sidebar toggle. */
    const burger = document.querySelector("[data-toggle-nav]");
    const sidebar = document.querySelector("[data-sidebar]");
    if (burger && sidebar) {
        burger.addEventListener("click", () => sidebar.classList.toggle("is-open"));
    }

    /** Auto-dismiss success messages after a few seconds. */
    document.querySelectorAll(".messages__item--success, .messages__item--info").forEach((el) => {
        window.setTimeout(() => {
            el.style.transition = "opacity .4s ease";
            el.style.opacity = "0";
            window.setTimeout(() => el.remove(), 400);
        }, 5000);
    });

    /**
     * Live rental price preview on the booking form.
     * The server always recomputes the authoritative total — this is a hint.
     */
    const carSelect = document.querySelector("[data-price-source]");
    const startInput = document.querySelector("[data-start-date]");
    const endInput = document.querySelector("[data-end-date]");
    const preview = document.querySelector("[data-price-preview]");

    function daysBetween(start, end) {
        const ms = new Date(end) - new Date(start);
        return Math.floor(ms / 86400000) + 1;
    }

    function refresh() {
        if (!carSelect || !preview) return;
        const option = carSelect.options[carSelect.selectedIndex];
        const price = parseFloat(option?.dataset?.price || "0");
        if (!price || !startInput?.value || !endInput?.value) {
            preview.textContent = "—";
            return;
        }
        const days = daysBetween(startInput.value, endInput.value);
        if (!Number.isFinite(days) || days <= 0) {
            preview.textContent = "—";
            return;
        }
        preview.textContent = `${days} × ${price.toFixed(2)} = ${(days * price).toFixed(2)} MAD`;
    }

    [carSelect, startInput, endInput].forEach((el) => {
        if (el) el.addEventListener("change", refresh);
    });
    refresh();

    /** Confirm destructive actions. */
    document.querySelectorAll("[data-confirm]").forEach((el) => {
        el.addEventListener("click", (event) => {
            if (!window.confirm(el.dataset.confirm)) event.preventDefault();
        });
    });

    /**
     * Header notification bell.
     * Opening the panel marks the notifications as seen, which clears the
     * badge server-side until something new arrives.
     */
    const notif = document.querySelector("[data-notif]");
    if (notif) {
        const toggle = notif.querySelector("[data-notif-toggle]");
        const panel = notif.querySelector("[data-notif-panel]");
        const badge = notif.querySelector("[data-notif-badge]");
        let markedSeen = false;

        const close = () => {
            panel.setAttribute("hidden", "");
            toggle.setAttribute("aria-expanded", "false");
        };

        toggle.addEventListener("click", (event) => {
            event.stopPropagation();
            const willOpen = panel.hasAttribute("hidden");
            if (willOpen) {
                panel.removeAttribute("hidden");
                toggle.setAttribute("aria-expanded", "true");
            } else {
                close();
            }

            if (willOpen && !markedSeen) {
                markedSeen = true;
                window
                    .fetch(notif.dataset.notifSeenUrl, {
                        method: "POST",
                        headers: {
                            "X-CSRFToken": notif.dataset.csrf,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    })
                    .then(() => {
                        if (badge) badge.hidden = true;
                    })
                    .catch(() => {
                        /* the badge simply stays until the next page load */
                    });
            }
        });

        document.addEventListener("click", (event) => {
            if (!notif.contains(event.target)) close();
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") close();
        });
    }
})();
