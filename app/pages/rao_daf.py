"""Motions — DAF vs RAO."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/motions/rao-daf", name="DAF vs RAO",
                   category="Motions", order=1)

layout = placeholder("DAF vs RAO")
