"""Vessel Tracker - Tracks (placeholder).

Will become the Track Vessels app: dash-leaflet map with latest positions
and 24h track lines, reusing the Copernicus page's EMODnet/OpenSeaMap layers.
"""
import dash

from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/vessel-tracker/tracks", name="Tracks",
                   category="Vessel Tracker", order=2)

layout = placeholder(
    "Tracks",
    "Map view of the tracked fleet: latest positions and 24-hour track lines "
    "on the familiar EMODnet / OpenSeaMap layers.",
)
