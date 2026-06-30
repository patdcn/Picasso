"""SAT Diving — saturation decompression profile planner.

Placeholder slot. The real tool implements the USN Diving Manual Ch.13 saturation
decompression schedule (storage depth -> surface), with a tabulated depth/time
profile and a depth-vs-time chart. Engine to be built once the source tables and
the open design decisions are confirmed.
"""
import dash
from app.pages._placeholder import placeholder

dash.register_page(__name__, path="/diving/sat-deco", name="SAT Decompression",
                   category="SAT Diving", order=0)

layout = placeholder(
    "SAT Decompression planner",
    "Saturation decompression profile from storage depth to surface, per the USN "
    "Diving Manual Ch.13 rates and rest-period rules. Indicative planning only. "
    "Engine under construction.",
)
