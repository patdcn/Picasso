"""Structural — seafastening."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/structural/seafastening", name="Seafastening",
                   category="Structural", order=1)

layout = placeholder("Seafastening")
