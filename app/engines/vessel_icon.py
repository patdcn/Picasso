"""
Ship-shaped DivMarker icons for the Tracker maps.

- Hull outline (pointed bow) as inline SVG, filled with the nav-status
  colour, rotated to the vessel's true heading (fallback: COG; unknown:
  drawn unrotated pointing north).
- Icon size scales RELATIVELY with vessel length (AIS Dimension A+B via
  `latest.length_m`): clamped 16..34 px so a 30 m workboat and a 300 m
  tanker are both readable at Gulf-wide zoom. Geographic true-scale is
  deliberately NOT used (a 115 m DSV would be sub-pixel).
- Selection ring (teal) for the Track Animated playlist.
"""
MIN_PX, MAX_PX = 16.0, 34.0
MIN_LEN, MAX_LEN = 20.0, 220.0


def icon_height(length_m):
    if not length_m or length_m <= 0:
        return 20.0
    frac = (min(max(length_m, MIN_LEN), MAX_LEN) - MIN_LEN) / (MAX_LEN - MIN_LEN)
    return round(MIN_PX + frac * (MAX_PX - MIN_PX), 1)


def rotation(heading, cog):
    if heading is not None and 0 <= heading < 360:
        return float(heading)
    if cog is not None and 0 <= cog < 360:
        return float(cog)
    return 0.0


def ship_div(color, heading=None, cog=None, length_m=None, selected=False):
    """Returns (html, iconSize, iconAnchor) for dl.DivMarker's iconOptions."""
    h = icon_height(length_m)
    w = round(h * 0.45, 1)
    rot = rotation(heading, cog)
    ring = ("filter: drop-shadow(0 0 3px #0f766e) drop-shadow(0 0 3px #0f766e);"
            if selected else "")
    # hull: bow tip top-centre, straight sides, square-ish stern
    svg = (
        f'<svg width="{w}" height="{h}" viewBox="0 0 20 44" '
        f'style="transform: rotate({rot}deg); transform-origin: 50% 50%; {ring}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="M10 1 L18 13 L18 40 L2 40 L2 13 Z" '
        f'fill="{color}" stroke="white" stroke-width="2" '
        f'stroke-linejoin="round"/></svg>'
    )
    size = max(w, h)                       # square hitbox so rotation fits
    return svg, [size, size], [size / 2, size / 2]
