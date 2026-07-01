/* Sidebar accordion: clicking a group header expands it and collapses the
 * others. Uses event delegation on the document so it keeps working after Dash
 * re-renders the sidebar on navigation. The server (build_nav) sets the initial
 * open group to the one containing the current page; this only handles clicks. */
(function () {
  function sync(sidebar) {
    sidebar.querySelectorAll(".nav-group").forEach(function (g) {
      var open = g.classList.contains("open");
      var h = g.querySelector(".nav-group-header");
      if (h) h.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  document.addEventListener("click", function (e) {
    var header = e.target.closest ? e.target.closest(".nav-group-header") : null;
    if (!header) return;
    var group = header.parentElement;
    if (!group || !group.classList.contains("nav-group")) return;

    var willOpen = !group.classList.contains("open");
    var sidebar = group.closest(".sidebar") || document;

    // accordion: collapse every group first, then open the clicked one if needed
    sidebar.querySelectorAll(".nav-group.open").forEach(function (g) {
      g.classList.remove("open");
    });
    if (willOpen) group.classList.add("open");
    sync(sidebar);
  });
})();
