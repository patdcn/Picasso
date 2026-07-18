"""
Admin - DP power consumers (admins only; guarded by the /admin prefix guard).

CRUD for the named non-thruster consumers used by the DP Capability & Ops
Check power panel. Planning kW figures are UPPER BOUNDS for duty consumers
(e.g. cranes at their DPR-observed maximum). Bus assignments start as
'Split over live buses' pending the 440 V distribution single-line — correct
them here once the feeding arrangement is confirmed.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx, no_update

from app import dp_consumers as dcon
from app.adminui import card, btn, status, back_link, INK, MUTED, ACCENT

dash.register_page(__name__, path="/admin/dp-consumers", name="DP power consumers")

_IN = {"width": "100%", "padding": "6px 8px", "borderRadius": "6px",
       "border": "1px solid #d1d5db", "boxSizing": "border-box",
       "fontSize": "0.85rem"}
_TH = {"textAlign": "left", "fontSize": "0.72rem", "color": MUTED,
       "textTransform": "uppercase", "letterSpacing": "0.03em",
       "padding": "4px 6px"}
_TD = {"padding": "4px 6px", "verticalAlign": "top"}

_BUS_OPTS = [{"label": dcon.BUS_LABELS[b], "value": b}
             for b in dcon.BUS_CHOICES]


def _row(r):
    cid = r["id"]
    return html.Tr([
        html.Td(dcc.Input(id={"type": "dpcon-name", "id": cid}, type="text",
                          value=r["name"], debounce=True, style=_IN), style={**_TD, "minWidth": "180px"}),
        html.Td(dcc.Input(id={"type": "dpcon-kw", "id": cid}, type="number",
                          value=r["kw"], min=0, step=1, debounce=True,
                          style={**_IN, "fontFamily": "ui-monospace,monospace"}),
                style={**_TD, "width": "90px"}),
        html.Td(dcc.Dropdown(id={"type": "dpcon-bus", "id": cid},
                             options=_BUS_OPTS, value=r["bus"], clearable=False,
                             searchable=False, style={"fontSize": "0.85rem"}),
                style={**_TD, "minWidth": "160px"}),
        html.Td(dcc.Input(id={"type": "dpcon-cat", "id": cid}, type="text",
                          value=r["category"], debounce=True, style=_IN),
                style={**_TD, "width": "130px"}),
        html.Td(dcc.Input(id={"type": "dpcon-src", "id": cid}, type="text",
                          value=r["source"], debounce=True, style=_IN),
                style={**_TD, "minWidth": "240px"}),
        html.Td(dcc.Checklist(id={"type": "dpcon-don", "id": cid},
                              options=[{"label": "", "value": "on"}],
                              value=["on"] if r["default_on"] else []),
                style={**_TD, "width": "60px", "textAlign": "center"}),
        html.Td(html.Button("\u2715", id={"type": "dpcon-del", "id": cid},
                            n_clicks=0, title="Delete consumer",
                            style={"border": "1px solid #fecaca", "color": "#b91c1c",
                                   "background": "#fff", "borderRadius": "6px",
                                   "cursor": "pointer", "padding": "4px 9px"}),
                style={**_TD, "width": "40px"}),
    ])


def _table():
    rs = dcon.rows()
    head = html.Thead(html.Tr([
        html.Th("Consumer", style=_TH), html.Th("kW (planning)", style=_TH),
        html.Th("Bus", style=_TH), html.Th("Category", style=_TH),
        html.Th("Source / provenance", style=_TH),
        html.Th("On by default", style=_TH), html.Th("", style=_TH)]))
    body = html.Tbody([_row(r) for r in rs]) if rs else html.Tbody(
        [html.Tr(html.Td("No consumers defined.", colSpan=7,
                         style={**_TD, "color": MUTED}))])
    return html.Table([head, body],
                      style={"width": "100%", "borderCollapse": "collapse"})


def layout():
    return html.Div([
        back_link(),
        html.H3("DP power consumers"),
        html.P("Named non-thruster consumers for the DP Capability & Ops Check "
               "power panel. Store UPPER-BOUND kW for duty consumers (cranes at "
               "their observed maximum) — under-budgeting generation is the "
               "expensive mistake. Bus assignments default to \u2018split over "
               "live buses\u2019 until confirmed against the 440 V distribution "
               "single-line.",
               style={"color": MUTED, "maxWidth": "760px"}),
        html.Div([
            html.Div(id="dpcon-table", children=_table()),
            html.Div(style={"height": "10px"}),
            btn("Save all", "dpcon-save"),
            status("dpcon-status"),
        ], style={"background": "#fff", "border": "1px solid #e5e7eb",
                  "borderRadius": "12px", "padding": "18px",
                  "marginBottom": "18px", "maxWidth": "1100px",
                  "overflowX": "auto"}),
        card([
            html.H4("Add consumer", style={"marginTop": 0}),
            html.Div([
                html.Div(dcc.Input(id="dpcon-new-name", type="text",
                                   placeholder="Name", style=_IN),
                         style={"flex": 2}),
                html.Div(dcc.Input(id="dpcon-new-kw", type="number", min=0,
                                   placeholder="kW", style=_IN),
                         style={"flex": 1}),
                html.Div(dcc.Dropdown(id="dpcon-new-bus", options=_BUS_OPTS,
                                      value="split", clearable=False,
                                      searchable=False,
                                      style={"fontSize": "0.85rem"}),
                         style={"flex": 1.4}),
            ], style={"display": "flex", "gap": "8px", "marginBottom": "8px"}),
            dcc.Input(id="dpcon-new-src", type="text",
                      placeholder="Source / provenance note", style=_IN),
            html.Div(style={"height": "8px"}),
            btn("Add", "dpcon-add"),
            status("dpcon-add-status"),
        ]),
    ], style={"maxWidth": "1140px"})


@callback(
    Output("dpcon-status", "children"),
    Output("dpcon-table", "children"),
    Input("dpcon-save", "n_clicks"),
    Input({"type": "dpcon-del", "id": ALL}, "n_clicks"),
    State({"type": "dpcon-name", "id": ALL}, "value"),
    State({"type": "dpcon-name", "id": ALL}, "id"),
    State({"type": "dpcon-kw", "id": ALL}, "value"),
    State({"type": "dpcon-bus", "id": ALL}, "value"),
    State({"type": "dpcon-cat", "id": ALL}, "value"),
    State({"type": "dpcon-src", "id": ALL}, "value"),
    State({"type": "dpcon-don", "id": ALL}, "value"),
    prevent_initial_call=True,
)
def _save_or_delete(_n, del_clicks, names, ids, kws, buses, cats, srcs, dons):
    trig = ctx.triggered_id
    if isinstance(trig, dict) and trig.get("type") == "dpcon-del":
        # Guard: pattern-matched buttons fire with n_clicks=0 when the table
        # re-renders; only act on a real click.
        if not any(del_clicks or []):
            return no_update, no_update
        _ok, msg = dcon.delete(trig["id"])
        return html.Span(msg, style={"color": ACCENT}), _table()
    updates = {}
    for i, cid_obj in enumerate(ids or []):
        cid = cid_obj["id"]
        updates[cid] = dict(
            name=(names or [None])[i] if i < len(names or []) else None,
            kw=(kws or [None])[i] if i < len(kws or []) else None,
            bus=(buses or [None])[i] if i < len(buses or []) else None,
            category=(cats or [None])[i] if i < len(cats or []) else None,
            source=(srcs or [None])[i] if i < len(srcs or []) else None,
            default_on=bool((dons or [[]])[i]) if i < len(dons or []) else False,
        )
    n, msg = dcon.update_many(updates)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"}), _table()


@callback(
    Output("dpcon-add-status", "children"),
    Output("dpcon-table", "children", allow_duplicate=True),
    Output("dpcon-new-name", "value"),
    Output("dpcon-new-kw", "value"),
    Output("dpcon-new-src", "value"),
    Input("dpcon-add", "n_clicks"),
    State("dpcon-new-name", "value"),
    State("dpcon-new-kw", "value"),
    State("dpcon-new-bus", "value"),
    State("dpcon-new-src", "value"),
    prevent_initial_call=True,
)
def _add(_n, name, kw, bus, src):
    ok, msg = dcon.add(name, kw, bus=bus or "split", source=src or "")
    span = html.Span(msg, style={"color": ACCENT if ok else "#b91c1c"})
    if not ok:
        return span, no_update, no_update, no_update, no_update
    return span, _table(), "", None, ""
