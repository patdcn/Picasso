"""Air MG Diving — DCD (decompression) tables. Placeholder; built later."""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/air-diving/dcd-tables", name="DCD Tables",
                   category="Air MG Diving", order=1)

layout = placeholder(
    "DCD Tables",
    "Air diving decompression tables for MG (mixed-gas / surface-supplied air) "
    "operations. To be built out in a later session.",
)
