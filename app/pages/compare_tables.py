"""Air MG Diving - Compare Tables. Placeholder; built later.

Planned: pick up to three in-water or surface-decompression schedules (from the
DCD and US Navy tables) and plot their dive profiles on one chart to compare
run times, stop depths and gas usage side by side. Limited to in-water and
surface-decompression (SurD) tables \u2014 no-stop-limit and RNT tables are excluded.
"""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/air-diving/compare-tables", name="Compare Tables",
                   category="Air MG Diving", order=3)

layout = placeholder(
    "Compare Tables",
    "Select up to three schedules \u2014 from the DCD and US Navy in-water and "
    "surface-decompression (SurD) tables \u2014 and plot their dive profiles on a single "
    "chart to compare run times, stop depths and gas usage. No-decompression-limit and "
    "residual-nitrogen tables are excluded. Placeholder for now.",
)
