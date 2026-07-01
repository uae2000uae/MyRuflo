(function () {
    var form = document.getElementById("composerForm");
    if (!form) return;

    var messageList = document.getElementById("messageList");
    var thinkingHint = document.getElementById("thinkingHint");
    var errorEl = document.getElementById("composerError");
    var sendBtn = document.getElementById("sendBtn");
    var textarea = form.querySelector("textarea[name='text']");
    var conversationId = form.dataset.conversationId;

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

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        var text = textarea.value.trim();
        if (!text) return;

        errorEl.hidden = true;
        sendBtn.disabled = true;
        thinkingHint.hidden = false;

        // Optimistically show the user's message right away.
        var pending = document.createElement("div");
        pending.className = "msg msg-user";
        pending.innerHTML = '<div class="msg-bubble"></div>';
        pending.querySelector(".msg-bubble").textContent = text;
        messageList.appendChild(pending);
        scrollToBottom();

        var mode = form.mode.value;
        textarea.value = "";

        try {
            var response = await fetch("/chat/" + conversationId + "/message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text, mode: mode }),
            });
            if (!response.ok) {
                var data = await response.json().catch(function () { return {}; });
                errorEl.textContent = data.detail || "Something went wrong.";
                errorEl.hidden = false;
                pending.remove();
                textarea.value = text;
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
        } finally {
            sendBtn.disabled = false;
            thinkingHint.hidden = true;
        }
    });
})();
