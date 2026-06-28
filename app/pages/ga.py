"""Reference — Picasso general arrangement."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/reference/ga", name="Picasso GA",
                   category="Reference", order=1)

layout = placeholder("DSV Picasso — General Arrangement")
