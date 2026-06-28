"""Lifting — crane curves (140T main hoist envelope will land here)."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/lifting/crane-curves", name="Crane curves",
                   category="Lifting", order=1)

layout = placeholder("Crane curves",
                     "The 140T main hoist envelope tool will be ported in here as the first real page.")
