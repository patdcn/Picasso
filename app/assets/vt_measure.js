/* Client-side helpers for the Tracker map.
 *
 * 1. Live cursor lat/lon readout on mousemove (server round-trips would lag).
 * 2. Drawing-mode flag: while the measure tool is drawing / editing /
 *    deleting, map clicks must NOT deselect the vessel (they are vertex or
 *    tool clicks). The flag is set from Leaflet.Draw's map events wired via
 *    dl.Map eventHandlers, PLUS a DOM-level fallback on the toolbar buttons
 *    in case those events do not bridge through dash-leaflet.
 * 3. Click classification: a capture-phase listener records whether the last
 *    click landed on a marker / track line / drawn shape. Such clicks never
 *    deselect either - only a genuine empty-sea click does.
 *
 * The clientside callback in vessel_tracks.py reads window.vtMeasure.drawing
 * and window.vtMeasure.clickOnFeature to decide whether a map click may
 * reach the server as a deselect.
 */
window.vtMeasure = Object.assign({}, window.vtMeasure, {

  drawing: false,
  clickOnFeature: false,
  _stopTimer: null,

  /* --- cursor readout ---------------------------------------------------- */
  onMove: function (e) {
    try {
      var el = document.getElementById("vtt-hovercoord");
      if (!el || !e || !e.latlng) { return; }
      var lat = e.latlng.lat;
      var lon = e.latlng.lng;
      lon = ((lon + 180) % 360 + 360) % 360 - 180;
      var ns = lat >= 0 ? "N" : "S";
      var ew = lon >= 0 ? "E" : "W";
      el.textContent =
        Math.abs(lat).toFixed(4) + "\u00b0" + ns + "  " +
        Math.abs(lon).toFixed(4) + "\u00b0" + ew;
    } catch (err) { /* never break the map on a mouse move */ }
  },

  /* --- drawing-mode flag (Leaflet.Draw events via dl.Map eventHandlers) -- */
  onModeStart: function () {
    var m = window.vtMeasure;
    if (m._stopTimer) { clearTimeout(m._stopTimer); m._stopTimer = null; }
    m.drawing = true;
  },

  onModeStop: function () {
    var m = window.vtMeasure;
    if (m._stopTimer) { clearTimeout(m._stopTimer); }
    // Linger: the click/double-click that FINISHES a line fires around the
    // same moment as drawstop - keep the flag up briefly so that click is
    // still swallowed and cannot deselect the vessel.
    m._stopTimer = setTimeout(function () {
      window.vtMeasure.drawing = false;
      window.vtMeasure._stopTimer = null;
    }, 450);
  }

});

/* --- DOM-level fallbacks + click classification (installed once) --------- */
(function () {
  if (window.vtMeasure._domInstalled) { return; }
  window.vtMeasure._domInstalled = true;

  document.addEventListener("click", function (e) {
    var m = window.vtMeasure;
    var t = e.target;
    if (!t || !t.closest) { m.clickOnFeature = false; return; }

    /* Fallback: entering a draw/edit/delete mode via the toolbar buttons.
       Matches the Leaflet.Draw control anchors. */
    if (t.closest(".leaflet-draw-toolbar a")) {
      var href = (t.closest("a") || {}).className || "";
      if (/leaflet-draw-(draw|edit)-/.test(href)) {
        m.onModeStart();
      }
      m.clickOnFeature = true;      // toolbar clicks never deselect
      return;
    }
    /* Fallback: the Finish / Cancel / Save action links end the mode. */
    if (t.closest(".leaflet-draw-actions")) {
      m.onModeStop();
      m.clickOnFeature = true;
      return;
    }

    /* Classification: markers (vessel icons, vertex handles), vector paths
       (track polylines, measure lines, asset shapes) and div-icons never
       count as an empty-sea deselect click. */
    m.clickOnFeature = !!t.closest(
      ".leaflet-marker-icon, .leaflet-interactive, .leaflet-div-icon");
  }, true);   /* capture phase: runs before Leaflet's own handlers */

  document.addEventListener("keyup", function (e) {
    if (e.key === "Escape") { window.vtMeasure.onModeStop(); }
  }, true);
})();
