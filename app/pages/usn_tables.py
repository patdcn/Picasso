"""Air MG Diving - US Navy decompression tables. Placeholder; built later.

Planned: USN Rev 7 no-decompression limits + repetitive groups, air in-water
decompression, surface decompression (SurDO2 / SurDair) and N2O2 (nitrox) tables,
stored in the same /data store as the DCD tables for side-by-side comparison.
"""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/air-diving/usn-tables", name="US Navy Tables",
                   category="Air MG Diving", order=2)

layout = placeholder(
    "US Navy Tables",
    "US Navy Diving Manual (Rev 7) decompression tables \u2014 no-decompression limits & "
    "repetitive groups, air in-water decompression, surface decompression (SurDO2 / SurDair) "
    "and nitrox (N2O2). To be extracted and loaded alongside the DCD tables so the two "
    "standards can be compared. Placeholder for now.",
)
