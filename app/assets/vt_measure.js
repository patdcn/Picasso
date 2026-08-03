/* Client-side helpers for the Tracker map: live cursor lat/lon readout on
 * mousemove. The measure tool itself (drawing polylines) is handled by
 * dash-leaflet's EditControl; distance is computed server-side from the
 * drawn geometry. This file only does the lightweight hover readout, which
 * must be client-side to feel live (no server round-trip per mouse move).
 */
window.vtMeasure = Object.assign({}, window.vtMeasure, {

  onMove: function (e) {
    try {
      var el = document.getElementById("vtt-hovercoord");
      if (!el || !e || !e.latlng) { return; }
      var lat = e.latlng.lat;
      var lon = e.latlng.lng;
      // normalise lon to -180..180
      lon = ((lon + 180) % 360 + 360) % 360 - 180;
      var ns = lat >= 0 ? "N" : "S";
      var ew = lon >= 0 ? "E" : "W";
      el.textContent =
        Math.abs(lat).toFixed(4) + "\u00b0" + ns + "  " +
        Math.abs(lon).toFixed(4) + "\u00b0" + ew;
    } catch (err) { /* never break the map on a mouse move */ }
  }

});
