"""Diving — umbilical excursion charts."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/diving/umbilical", name="Umbilical excursion",
                   category="SAT Diving", order=2)

layout = placeholder("Umbilical excursion charts")
