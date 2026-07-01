(function () {
    var form = document.getElementById("composerForm");
    if (!form) return;

    var messageList = document.getElementById("messageList");
    var statusLine = document.getElementById("statusLine");
    var statusText = document.getElementById("statusText");
    var errorEl = document.getElementById("composerError");
    var sendBtn = document.getElementById("sendBtn");
    var textarea = form.querySelector("textarea[name='text']");
    var conversationId = form.dataset.conversationId;
    var fileInput = document.getElementById("fileInput");
    var attachBtn = document.getElementById("attachBtn");
    var stagingEl = document.getElementById("attachmentStaging");
    var enhanceBtn = document.getElementById("enhanceBtn");

    var stagedFiles = [];
    var statusPollTimer = null;

    function setStatus(text) {
        statusText.textContent = text;
        statusLine.hidden = false;
    }

    function startStatusPolling() {
        setStatus("Thinking about how to approach this…");
        statusPollTimer = setInterval(async function () {
            try {
                var response = await fetch("/chat/" + conversationId + "/status");
                if (!response.ok) return;
                var data = await response.json();
                if (data.status) setStatus(data.status);
            } catch (err) {
                // Ignore transient polling errors — the next tick will retry.
            }
        }, 1200);
    }

    function stopStatusPolling() {
        if (statusPollTimer) {
            clearInterval(statusPollTimer);
            statusPollTimer = null;
        }
        statusLine.hidden = true;
    }

    function scrollToBottom() {
        messageList.scrollTop = messageList.scrollHeight;
    }
    scrollToBottom();

    textarea.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    // --- attachments ---

    function renderStaging() {
        stagingEl.innerHTML = "";
        stagingEl.hidden = stagedFiles.length === 0;
        stagedFiles.forEach(function (file, index) {
            var chip = document.createElement("span");
            chip.className = "attachment-chip staged";
            chip.textContent = (file.type.startsWith("image/") ? "🖼 " : "📄 ") + file.name;
            var remove = document.createElement("button");
            remove.type = "button";
            remove.className = "attachment-remove";
            remove.setAttribute("aria-label", "Remove " + file.name);
            remove.textContent = "×";
            remove.addEventListener("click", function () {
                stagedFiles.splice(index, 1);
                renderStaging();
            });
            chip.appendChild(remove);
            stagingEl.appendChild(chip);
        });
    }

    attachBtn.addEventListener("click", function () {
        fileInput.click();
    });

    fileInput.addEventListener("change", function () {
        stagedFiles = stagedFiles.concat(Array.from(fileInput.files));
        fileInput.value = "";
        renderStaging();
    });

    // --- enhance ---

    enhanceBtn.addEventListener("click", async function () {
        var text = textarea.value.trim();
        if (!text) return;
        errorEl.hidden = true;
        enhanceBtn.disabled = true;
        enhanceBtn.classList.add("spinning");
        try {
            var response = await fetch("/chat/" + conversationId + "/enhance", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text }),
            });
            var data = await response.json().catch(function () { return {}; });
            if (!response.ok) {
                errorEl.textContent = data.detail || "Could not enhance the prompt.";
                errorEl.hidden = false;
                return;
            }
            textarea.value = data.text;
            textarea.focus();
        } catch (err) {
            errorEl.textContent = "Network error — please try again.";
            errorEl.hidden = false;
        } finally {
            enhanceBtn.disabled = false;
            enhanceBtn.classList.remove("spinning");
        }
    });

    // --- sending a message ---

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        var text = textarea.value.trim();
        if (!text) return;

        errorEl.hidden = true;
        sendBtn.disabled = true;
        startStatusPolling();

        // Optimistically show the user's message right away.
        var pending = document.createElement("div");
        pending.className = "msg msg-user";
        pending.innerHTML = '<div class="msg-bubble"></div>';
        pending.querySelector(".msg-bubble").textContent = text;
        messageList.appendChild(pending);
        scrollToBottom();

        var mode = form.mode.value;
        var filesToSend = stagedFiles;
        textarea.value = "";
        stagedFiles = [];
        renderStaging();

        var formData = new FormData();
        formData.append("text", text);
        formData.append("mode", mode);
        filesToSend.forEach(function (file) {
            formData.append("files", file, file.name);
        });

        try {
            var response = await fetch("/chat/" + conversationId + "/message", {
                method: "POST",
                body: formData,
            });
            if (!response.ok) {
                var data = await response.json().catch(function () { return {}; });
                errorEl.textContent = data.detail || "Something went wrong.";
                errorEl.hidden = false;
                pending.remove();
                textarea.value = text;
                stagedFiles = filesToSend;
                renderStaging();
                return;
            }
            var html = await response.text();
            messageList.innerHTML = html;
            scrollToBottom();
        } catch (err) {
            errorEl.textContent = "Network error — please try again.";
            errorEl.hidden = false;
            pending.remove();
            textarea.value = text;
            stagedFiles = filesToSend;
            renderStaging();
        } finally {
            sendBtn.disabled = false;
            stopStatusPolling();
        }
    });
})();
