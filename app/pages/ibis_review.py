"""
Calculation — IBIS review.

Embeds the self-contained IBIS calculation review tool
(app/assets/ibis_review.html). The tool reads IBIS ``.xtb`` files (SQLite)
entirely in the browser via sql.js — nothing is uploaded to the server. It
presents:

* Calculation  — chapter/line tree with editable aantal / unit price / markup;
* Hourly rates — editable wage rates;
* Staart       — overhead / profit / CAR premiums (editable, written back to a
                 NEW .xtb copy; the original is never touched);
* Quote & levies — location/asset-scoped levies that feed the Excel export and
                 the on-screen quote only (never written into IBIS);
* Report       — drill-down by cost type and by group (stuurcode);

plus a footer "Export quote to Excel" (quote lines + hourly rates + summary
sheets) available from any tab.

To update the tool itself, replace app/assets/ibis_review.html — it is a single
self-contained file (sql.js + SheetJS loaded from cdnjs at runtime).
"""
import dash
from dash import html

dash.register_page(
    __name__,
    path="/calculation/ibis-review",
    name="IBIS review",
    title="IBIS calculation review",
    category="Calculation",
    order=1,
)


def layout():
    return html.Div(
        [
            html.Iframe(
                src=dash.get_asset_url("ibis_review.html"),
                title="IBIS calculation review",
                style={
                    "width": "100%",
                    "height": "calc(100vh - 118px)",
                    "border": "none",
                    "borderRadius": "12px",
                    "background": "#0f1420",
                    "display": "block",
                },
            ),
        ],
        style={"margin": "0"},
    )
