"""Home / landing."""
import dash
from dash import html

dash.register_page(__name__, path="/", name="Home")

layout = html.Div([
    html.H3("DSV Picasso Engineering Portal"),
    html.P("Select a tool from the menu on the left. Tools are grouped by discipline.",
           style={"color": "#374151", "maxWidth": "640px", "lineHeight": "1.5"}),
    html.P("Use the \u2630 button in the header to collapse the menu (and to open it on a tablet).",
           style={"color": "#6b7280", "maxWidth": "640px", "lineHeight": "1.5", "fontSize": "0.9rem"}),
])
