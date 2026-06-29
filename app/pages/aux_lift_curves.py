"""Aux Lift Curves — auxiliary winch load chart (placeholder)."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/lifting/aux-lift-curves", name="Aux Lift Curves",
                   category="Lifting", order=2)

layout = placeholder("Aux Lift Curves — auxiliary winch (coming soon)")
