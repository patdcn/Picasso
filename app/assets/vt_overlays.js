/* Client-side renderers for the Tracker map asset overlays (dl.GeoJSON).
 *
 * Deliberately dumb and generic: every feature carries precomputed display
 * properties injected by app/engines/map_overlays.py (__color, __dash,
 * __shape, __tip, __fill). Adding a category never requires touching this
 * file - Python remains the single source of truth for styling.
 */
window.vtOverlays = Object.assign({}, window.vtOverlays, {

  style: function (feature) {
    var p = (feature && feature.properties) || {};
    return {
      color: p.__color || "#6b7280",
      weight: p.__weight || 1.6,
      opacity: 0.75,
      dashArray: p.__dash || null,
      fillColor: p.__color || "#6b7280",
      fillOpacity: p.__fill || 0,
      bubblingMouseEvents: false
    };
  },

  pointToLayer: function (feature, latlng) {
    var p = (feature && feature.properties) || {};
    var c = p.__color || "#6b7280";
    if (p.__shape === "square") {
      return L.marker(latlng, {
        interactive: true,
        bubblingMouseEvents: false,
        icon: L.divIcon({
          className: "",
          html: '<div style="width:9px;height:9px;background:' + c +
                ';border:1.5px solid white;box-shadow:0 0 1px #0006;"></div>',
          iconSize: [12, 12],
          iconAnchor: [6, 6]
        })
      });
    }
    if (p.__shape === "triangle") {
      return L.marker(latlng, {
        interactive: true,
        bubblingMouseEvents: false,
        icon: L.divIcon({
          className: "",
          html: '<div style="width:0;height:0;' +
                'border-left:6px solid transparent;' +
                'border-right:6px solid transparent;' +
                'border-bottom:11px solid ' + c +
                ';filter:drop-shadow(0 0 1px white);"></div>',
          iconSize: [12, 12],
          iconAnchor: [6, 7]
        })
      });
    }
    return L.circleMarker(latlng, {
      radius: 4.5,
      color: "white",
      weight: 1,
      fillColor: c,
      fillOpacity: 0.85,
      bubblingMouseEvents: false
    });
  },

  onEachFeature: function (feature, layer) {
    var p = (feature && feature.properties) || {};
    if (p.__tip) {
      layer.bindTooltip(p.__tip, { sticky: true, direction: "top" });
    }
  }
});
