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
        status.textContent = "Creating your QR code…";
        dialog.querySelector("[data-phone-qr-close]").addEventListener("click", () => dialog.close());
        dialog.addEventListener("close", () => {
            dialog.remove();
            button.focus();
        }, { once: true });
        document.body.append(dialog);
        dialog.showModal();
        try {
            const result = await post(button.dataset.phoneQr, button.dataset.csrf);
            if (!dialog.open) return;
            image.src = result.image;
            image.hidden = false;
            status.textContent = "Use the camera app on your phone to scan this code.";
        } catch (error) {
            status.textContent = error.message;
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
            await post(page.dataset.verifyUrl, button.dataset.csrf, new URLSearchParams({ handoff: token }));
            status.textContent = "Continue with your phone’s camera and precise location.";
            button.dataset.punchHandoff = token;
            button.hidden = false;
        } catch (error) {
            status.textContent = error.message;
            if (signIn) signIn.hidden = false;
        }
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-phone-qr]");
        if (button) showQr(button);
    });
    const page = document.getElementById("eqourse-phone-check-in");
    if (page) openPhonePage(page);
})();
