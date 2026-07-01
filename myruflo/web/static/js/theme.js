(function () {
    var root = document.documentElement;
    var toggleBtn = document.getElementById("themeToggle");
    if (toggleBtn) {
        toggleBtn.addEventListener("click", function () {
            var current = root.getAttribute("data-theme") === "light" ? "light" : "dark";
            var next = current === "dark" ? "light" : "dark";
            root.setAttribute("data-theme", next);
            localStorage.setItem("myruflo-theme", next);
        });
    }

    var sidebarToggle = document.getElementById("sidebarToggle");
    var sidebar = document.getElementById("sidebar");
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener("click", function () {
            sidebar.classList.toggle("open");
        });
    }
})();
