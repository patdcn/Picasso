"""Vessel Tracker - Fleet (placeholder).

Will become the Manage Vessels app: add/remove/deactivate vessels in the
fleet table of the AIS database. The collector picks up fleet changes
automatically within 5 minutes.
"""
import dash

from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/vessel-tracker/fleet", name="Fleet",
                   category="Vessel Tracker", order=1)

layout = placeholder(
    "Fleet",
    "Manage which vessels are tracked: add, deactivate and edit vessels in the "
    "AIS fleet database. The collector follows changes automatically.",
)
