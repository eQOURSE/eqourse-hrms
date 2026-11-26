(function () {
    if (window.eqoursePhoneCheckInBound) return;
    window.eqoursePhoneCheckInBound = true;

    async function post(url, csrf, body) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrf },
            body,
        });
        const contentType = response.headers.get("Content-Type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("Could not open check-in. Refresh the page and try again.");
        }
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        return result;
    }

    async function showQr(button) {
        if (document.querySelector(".eqourse-phone-qr[open]")) return;
        const template = document.getElementById("eqourse-phone-qr-template");
        const dialog = template.content.firstElementChild.cloneNode(true);
        const status = dialog.querySelector("[data-phone-qr-status]");
        const image = dialog.querySelector("img");
        let pollTimer;
        status.textContent = "Creating your QR code…";
        dialog.querySelector("[data-phone-qr-close]").addEventListener("click", () => dialog.close());
        dialog.addEventListener("close", () => {
            clearTimeout(pollTimer);
            dialog.remove();
            if (button.isConnected) button.focus();
        }, { once: true });
        document.body.append(dialog);
        dialog.showModal();
        try {
            const result = await post(template.dataset.issueUrl, button.dataset.csrf,
                new URLSearchParams({ action: button.dataset.punchAction }));
            if (!dialog.open) return;
            image.src = result.image;
            image.hidden = false;
            status.textContent = "Use the camera app on your phone to scan this code.";
            const poll = async () => {
                try {
                    const progress = await post(template.dataset.statusUrl, button.dataset.csrf,
                        new URLSearchParams({ handoff: result.token }));
                    if (!dialog.open) return;
                    if (!progress.saved) {
                        pollTimer = setTimeout(poll, 2000);
                        return;
                    }
                    document.getElementById("attendance-activity-container").innerHTML = progress.controls;
                    updateTimers();
                    dialog.close();
                } catch (error) {
                    if (!dialog.open) return;
                    image.hidden = true;
                    status.textContent = error.message;
                }
            };
            pollTimer = setTimeout(poll, 2000);
        } catch (error) {
            status.textContent = error.message;
        }
    }

    function showChoice(button) {
        if (document.querySelector(".eqourse-punch-choice[open]")) return;
        const template = document.getElementById("eqourse-punch-choice-template");
        const dialog = template.content.firstElementChild.cloneNode(true);
        dialog.querySelector("h2").textContent = button.dataset.punchAction === "check-out" ? "Check out" : "Check in";
        dialog.querySelector("[data-choice-phone]").addEventListener("click", () => {
            dialog.close();
            showQr(button);
        });
        dialog.querySelector("[data-choice-laptop]").addEventListener("click", () => {
            dialog.close();
            document.dispatchEvent(new CustomEvent("eqourse:laptop-punch", { detail: button }));
        });
        dialog.querySelector("[data-choice-close]").addEventListener("click", () => dialog.close());
        dialog.addEventListener("close", () => dialog.remove(), { once: true });
        document.body.append(dialog);
        dialog.showModal();
    }

    function updateTimers() {
        for (const timer of document.querySelectorAll("[data-punch-elapsed]")) {
            if (!timer.dataset.punchAnchor) timer.dataset.punchAnchor = Date.now();
            const elapsed = Math.floor(Math.max(0, Number(timer.dataset.punchElapsed) || 0) +
                (Date.now() - Number(timer.dataset.punchAnchor)) / 1000);
            timer.textContent = [Math.floor(elapsed / 3600), Math.floor(elapsed / 60) % 60, elapsed % 60]
                .map((part) => String(part).padStart(2, "0")).join(":");
        }
    }

    async function openPhonePage(page) {
        const token = location.hash.slice(1);
        const status = page.querySelector("[data-phone-status]");
        const button = page.querySelector("[data-punch-url]");
        const signIn = page.querySelector("[data-phone-sign-in]");
        if (!/^[A-Za-z0-9_-]{32}$/.test(token)) {
            status.textContent = "Scan a new QR code from your laptop to start check-in.";
            return;
        }
        if (signIn) signIn.elements.attendance_handoff.value = token;
        if (page.dataset.authenticated === "false") {
            status.textContent = "Sign in with the same eQOURSE account you used on your laptop.";
            if (signIn) signIn.hidden = false;
            return;
        }
        try {
            const result = await post(page.dataset.verifyUrl, button.dataset.csrf, new URLSearchParams({ handoff: token }));
            status.textContent = "Continue with your phone’s camera and precise location.";
            button.querySelector(".hr-Check-In-out-text").textContent =
                result.action === "check-out" ? "Check out" : "Check in";
            button.dataset.punchHandoff = token;
            button.hidden = false;
        } catch (error) {
            status.textContent = error.message;
            if (signIn) signIn.hidden = false;
        }
    }

    document.addEventListener("eqourse:punch-choice", (event) => showChoice(event.detail));
    updateTimers();
    setInterval(updateTimers, 1000);
    const page = document.getElementById("eqourse-phone-check-in");
    if (page) openPhonePage(page);
})();
