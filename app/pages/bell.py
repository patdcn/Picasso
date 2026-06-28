"""Diving — single vs twin bell configuration."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/diving/bell", name="Single vs twin bell",
                   category="Diving", order=1)

layout = placeholder("Single vs twin bell")
