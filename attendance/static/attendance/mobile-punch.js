(function () {
    if (window.eqoursePunchPreviewBound) return;
    window.eqoursePunchPreviewBound = true;

    const locationErrors = {
        1: "Location permission is blocked. Allow precise location for this site and your browser, then retry.",
        2: "Your phone could not find its location. Turn on location services, move to an open spot, and retry.",
        3: "Getting your location took too long. Move to an open spot and retry.",
    };
    const metres = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });

    function describeLocation(details) {
        const accuracy = metres(details.accuracy_meters);
        if (Number.isFinite(details.distance_meters)) {
            return `Estimated distance: ${metres(details.distance_meters)} m. GPS uncertainty: ${accuracy} m. Combined: ${metres(details.distance_meters + details.accuracy_meters)} m. Office limit: ${metres(details.radius_meters)} m.`;
        }
        return `GPS uncertainty: ${accuracy} m. Maximum allowed: ${metres(details.accuracy_limit_meters)} m.`;
    }

    function openPunch(button, method) {
        const template = document.getElementById("eqourse-punch-template");
        if (!template || document.querySelector(".eqourse-punch-dialog[open]")) return;
        const dialog = template.content.firstElementChild.cloneNode(true);
        const elapsed = button.querySelector("[data-punch-elapsed]");
        if (elapsed) {
            const summary = dialog.querySelector("[data-checkout-elapsed]");
            summary.append(elapsed.cloneNode(true));
            summary.hidden = false;
        }
        const video = dialog.querySelector("video");
        const preview = dialog.querySelector("img");
        const cameraStatus = dialog.querySelector("[data-camera-status]");
        const locationStatus = dialog.querySelector("[data-location-status]");
        const error = dialog.querySelector("[data-punch-error]");
        const take = dialog.querySelector("[data-take-photo]");
        const retake = dialog.querySelector("[data-retake-photo]");
        const retry = dialog.querySelector("[data-retry-location]");
        const submit = dialog.querySelector("[data-submit-punch]");
        const cancel = dialog.querySelector("[data-close-punch]");
        let stream, photo, photoUrl, position;
        let sending = false;
        let active = true;

        function showError(message) {
            error.textContent = message;
            error.hidden = !message;
        }

        function updateSubmit() {
            submit.disabled = sending || !photo || !position;
        }

        function stopCamera() {
            if (stream) stream.getTracks().forEach((track) => track.stop());
            stream = null;
            video.srcObject = null;
        }

        function clearPhoto() {
            if (photoUrl) URL.revokeObjectURL(photoUrl);
            photoUrl = null;
            photo = null;
            preview.removeAttribute("src");
            preview.hidden = true;
            updateSubmit();
        }

        async function startCamera() {
            take.disabled = true;
            retake.hidden = true;
            video.hidden = false;
            cameraStatus.textContent = "Opening camera…";
            try {
                const camera = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } },
                    audio: false,
                });
                if (!active) {
                    camera.getTracks().forEach((track) => track.stop());
                    return;
                }
                stream = camera;
                video.srcObject = stream;
                await video.play();
                if (!active) return;
                cameraStatus.textContent = "";
                take.disabled = false;
            } catch (exception) {
                if (!active) return;
                stopCamera();
                cameraStatus.textContent = exception.name === "NotAllowedError"
                    ? "Camera permission is blocked. Allow the camera for this site, then try again."
                    : "The camera could not open. Check that it is available, then try again.";
                retake.hidden = false;
            }
        }

        function getLocation() {
            position = null;
            updateSubmit();
            retry.disabled = true;
            locationStatus.textContent = "Getting your location…";
            if (!navigator.geolocation) {
                locationStatus.textContent = "This browser does not provide location access.";
                return;
            }
            navigator.geolocation.getCurrentPosition((reading) => {
                if (!active) return;
                position = reading;
                retry.disabled = false;
                locationStatus.textContent = `Location ready. Reported GPS uncertainty: ${metres(reading.coords.accuracy)} m.`;
                updateSubmit();
            }, (failure) => {
                if (!active) return;
                retry.disabled = false;
                locationStatus.textContent = locationErrors[failure.code] || "Could not get a location reading. Please retry.";
            }, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
        }

        take.addEventListener("click", () => {
            if (!video.videoWidth || !video.videoHeight) {
                cameraStatus.textContent = "Wait for the camera preview, then try again.";
                return;
            }
            take.disabled = true;
            const canvas = document.createElement("canvas");
            const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
            canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
            const context = canvas.getContext("2d");
            if (!context) {
                cameraStatus.textContent = "This browser could not capture a photo.";
                take.disabled = false;
                return;
            }
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            canvas.toBlob((capture) => {
                if (!active) return;
                if (!capture) {
                    cameraStatus.textContent = "The photo could not be captured. Try again.";
                    take.disabled = false;
                    return;
                }
                photo = capture;
                photoUrl = URL.createObjectURL(capture);
                preview.src = photoUrl;
                preview.hidden = false;
                video.hidden = true;
                stopCamera();
                retake.hidden = false;
                cameraStatus.textContent = "Review your photo before submitting.";
                updateSubmit();
            }, "image/jpeg", 0.9);
        });

        retake.addEventListener("click", () => {
            clearPhoto();
            showError("");
            startCamera();
        });
        retry.addEventListener("click", () => {
            showError("");
            getLocation();
        });

        submit.addEventListener("click", async () => {
            if (sending || !photo || !position) return;
            sending = true;
            updateSubmit();
            cancel.disabled = retake.disabled = retry.disabled = true;
            showError("");
            const form = new FormData();
            form.append("face_image", photo, "attendance-face.jpg");
            form.append("latitude", position.coords.latitude);
            form.append("longitude", position.coords.longitude);
            form.append("accuracy", position.coords.accuracy);
            form.append("location_timestamp", position.timestamp);
            if (button.dataset.punchHandoff) form.append("handoff", button.dataset.punchHandoff);
            if (method === "laptop") form.append("punch_method", method);
            try {
                const response = await fetch(button.dataset.punchUrl, {
                    method: "POST",
                    body: form,
                    credentials: "same-origin",
                    headers: {
                        "HX-Request": "true",
                        "X-Punch-Client": "1",
                        "X-CSRFToken": button.dataset.csrf,
                    },
                });
                if (response.redirected) {
                    window.location.reload();
                    return;
                }
                if (!response.ok) {
                    const type = response.headers.get("content-type") || "";
                    const payload = type.includes("application/json") ? await response.json() : {};
                    if (payload.location) {
                        locationStatus.textContent = describeLocation(payload.location);
                        position = null;
                    }
                    throw new Error(payload.error || "Attendance could not be recorded. Please try again.");
                }
                if (button.dataset.punchHandoff) {
                    const result = await response.json();
                    if (result.saved !== true) throw new Error("Check-in could not be confirmed.");
                    document.querySelector("[data-phone-status]").textContent =
                        result.action === "check-out" ? "Check-out saved. You can close this page." : "Check-in saved. You can close this page.";
                    button.hidden = true;
                    history.replaceState(null, "", location.pathname);
                } else {
                    const html = await response.text();
                    document.getElementById("attendance-activity-container").innerHTML = html;
                }
                dialog.close();
            } catch (exception) {
                showError(exception.message || "Attendance could not be recorded. Please try again.");
            } finally {
                sending = false;
                cancel.disabled = retake.disabled = retry.disabled = false;
                updateSubmit();
            }
        });

        function closePunch() {
            active = false;
            stopCamera();
            clearPhoto();
            dialog.remove();
            window.removeEventListener("pagehide", closePunch);
            if (button.isConnected && document.hasFocus()) button.focus();
        }

        cancel.addEventListener("click", () => dialog.close());
        dialog.addEventListener("cancel", (event) => { if (sending) event.preventDefault(); });
        dialog.addEventListener("close", closePunch, { once: true });
        window.addEventListener("pagehide", closePunch, { once: true });
        dialog.querySelector("h2").textContent = button.querySelector(".hr-Check-In-out-text").textContent;
        document.body.append(dialog);
        dialog.showModal();
        startCamera();
        getLocation();
    }

    document.addEventListener("click", (event) => {
        const button = event.target.closest(".eqourse-punch-btn");
        if (!button || button.disabled) return;
        const desktop = /Windows NT|Macintosh|X11|CrOS/i.test(navigator.userAgent) &&
            !navigator.userAgentData?.mobile && !/Android|Mobile|iPhone|iPad|iPod/i.test(navigator.userAgent);
        if (desktop && button.hasAttribute("data-punch-choice")) {
            document.dispatchEvent(new CustomEvent("eqourse:punch-choice", { detail: button }));
        } else {
            openPunch(button);
        }
    });
    document.addEventListener("eqourse:laptop-punch", (event) => openPunch(event.detail, "laptop"));
})();
