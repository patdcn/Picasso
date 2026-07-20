"""
Admin - SAT systems (admins only; guarded by the /admin before_request).

Define saturation spreads used by the SAT gas calculator: build the floodable
volume from named components (each with an include toggle), set bell volume,
single/twin configuration and default operating depths + diver count. Stored as
JSON documents on the data volume via app.sat_system.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx, no_update
from dash.exceptions import PreventUpdate

from app import sat_system
from app.adminui import (card, btn, status, back_link,
                         is_admin, denied, INK, MUTED, ACCENT)

dash.register_page(__name__, path="/admin/sat-system", name="SAT systems")

NEW = "__new__"

NUM = {"width": "110px", "padding": "6px 8px", "borderRadius": "8px",
       "border": "1px solid #d1d5db", "fontFamily": "ui-monospace,monospace"}
TXT = {"flex": "1", "padding": "6px 8px", "borderRadius": "8px",
       "border": "1px solid #d1d5db", "minWidth": "0"}


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def _dropdown_options():
    opts = [{"label": s.get("name") or s["id"], "value": s["id"]}
            for s in sat_system.list_systems()]
    opts.append({"label": "\uff0b  New system\u2026", "value": NEW})
    return opts


def _label(txt):
    return html.Label(txt, style={"fontSize": "0.78rem", "fontWeight": 600,
                                  "color": INK, "display": "block",
                                  "marginBottom": "3px"})


def _scalar_row():
    def field(lbl, comp):
        return html.Div([_label(lbl), comp], style={"marginBottom": "10px"})

    return html.Div([
        field("System name",
              dcc.Input(id="satsys-name", type="text", style={**TXT, "width": "100%"})),
        html.Div([
            field("Bell volume [m\u00b3]",
                  dcc.Input(id="satsys-bellvol", type="number", step=0.1, min=0, style=NUM)),
            field("Bell configuration",
                  dcc.RadioItems(id="satsys-bellcfg",
                                 options=[{"label": " Single", "value": "single"},
                                          {"label": " Twin", "value": "twin"}],
                                 value="single",
                                 labelStyle={"display": "inline-block", "marginRight": "14px"},
                                 style={"marginTop": "4px"})),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
        html.Div([
            field("Default storage depth [m]",
                  dcc.Input(id="satsys-storage", type="number", step=1, min=0, style=NUM)),
            field("Default working depth [m]",
                  dcc.Input(id="satsys-working", type="number", step=1, min=0, style=NUM)),
            field("Divers in saturation",
                  dcc.Input(id="satsys-divers", type="number", step=1, min=0, style=NUM)),
        ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"}),
    ])


def layout():
    if not is_admin():
        return denied()
    systems = sat_system.list_systems()
    first = systems[0]["id"] if systems else NEW
    return html.Div([
        back_link(),
        html.H3("SAT systems"),
        html.P(["Define the saturation spreads the ", html.Code("SAT gas"),
                " calculator can select. The system's floodable volume is the sum "
                "of its included components; that total and the bell volume feed the "
                "gas calculations."],
               style={"color": MUTED, "maxWidth": "640px"}),

        dcc.Store(id="satsys-current-id", data=first),
        dcc.Store(id="satsys-rows", data=[]),

        card([
            _label("System"),
            dcc.Dropdown(id="satsys-select", options=_dropdown_options(),
                         value=first, clearable=False, style={"marginBottom": "14px"}),
            _scalar_row(),

            html.Div("Volume components", style={
                "fontWeight": 700, "fontSize": "0.82rem", "color": MUTED,
                "margin": "14px 0 6px", "textTransform": "uppercase",
                "letterSpacing": "0.03em"}),
            html.Div([
                html.Span("Include", style={"width": "58px", "fontSize": "0.72rem", "color": MUTED}),
                html.Span("Component", style={"flex": "1", "fontSize": "0.72rem", "color": MUTED}),
                html.Span("Volume [m\u00b3]", style={"width": "110px", "fontSize": "0.72rem", "color": MUTED}),
                html.Span("", style={"width": "34px"}),
            ], style={"display": "flex", "gap": "10px", "alignItems": "center",
                      "padding": "0 2px 4px"}),
            html.Div(id="satsys-components"),
            html.Button("\uff0b Add component", id="satsys-add", n_clicks=0, style={
                "padding": "6px 12px", "borderRadius": "8px", "border": "1px dashed #cbd5e1",
                "background": "#fff", "color": ACCENT, "fontWeight": 600, "cursor": "pointer",
                "marginTop": "6px"}),

            html.Div(id="satsys-volume", style={
                "marginTop": "14px", "fontWeight": 700, "color": INK, "fontSize": "0.95rem"}),

            html.Div(style={"height": "10px"}),
            btn("Save system", "satsys-save"),
            btn("Delete", "satsys-delete", primary=False),
            status("satsys-status"),
        ]),
    ], style={"maxWidth": "720px"})


# --------------------------------------------------------------------------- #
# Component rows
# --------------------------------------------------------------------------- #
def _component_row(i, comp):
    return html.Div([
        dcc.Checklist(id={"type": "satsys-inc", "index": i},
                      options=[{"label": "", "value": "inc"}],
                      value=["inc"] if comp.get("include", True) else [],
                      style={"width": "58px"}),
        dcc.Input(id={"type": "satsys-lbl", "index": i}, type="text",
                  value=comp.get("label", ""), placeholder="component name", style=TXT),
        dcc.Input(id={"type": "satsys-vol", "index": i}, type="number", step=0.1, min=0,
                  value=comp.get("vol_m3"), style=NUM),
        html.Button("\u00d7", id={"type": "satsys-rm", "index": i}, n_clicks=0, title="Remove",
                    style={"width": "34px", "border": "1px solid #fecaca", "borderRadius": "8px",
                           "background": "#fff", "color": "#b91c1c", "cursor": "pointer",
                           "fontWeight": 700}),
    ], style={"display": "flex", "gap": "10px", "alignItems": "center", "marginBottom": "6px"})


@callback(Output("satsys-components", "children"), Input("satsys-rows", "data"))
def _render_rows(rows):
    return [_component_row(i, c) for i, c in enumerate(rows or [])]


def _rows_from_dom(labels, vols, incs, ids):
    """Reassemble the component list from the pattern-matched DOM inputs,
    preserving on-screen order by index."""
    triples = []
    for lbl, vol, inc, _id in zip(labels or [], vols or [], incs or [], ids or []):
        triples.append((_id["index"], {"label": (lbl or "").strip(),
                                       "vol_m3": vol,
                                       "include": bool(inc)}))
    triples.sort(key=lambda t: t[0])
    return [c for _, c in triples]


# --------------------------------------------------------------------------- #
# Load a system into the form
# --------------------------------------------------------------------------- #
@callback(
    Output("satsys-rows", "data"),
    Output("satsys-current-id", "data"),
    Output("satsys-name", "value"),
    Output("satsys-bellvol", "value"),
    Output("satsys-bellcfg", "value"),
    Output("satsys-storage", "value"),
    Output("satsys-working", "value"),
    Output("satsys-divers", "value"),
    Input("satsys-select", "value"),
)
def _load(sel):
    if not is_admin():
        raise PreventUpdate
    sysd = sat_system.blank_system() if (sel == NEW or not sel) else \
        (sat_system.get_system(sel) or sat_system.blank_system())
    return (sysd.get("components", []),
            NEW if sel == NEW else sel,
            sysd.get("name", ""),
            sysd.get("bell_vol_m3"),
            sysd.get("bell_config", "single"),
            sysd.get("default_storage_m"),
            sysd.get("default_working_m"),
            sysd.get("divers"))


# --------------------------------------------------------------------------- #
# Add / remove component (rebuild the rows store from the current DOM)
# --------------------------------------------------------------------------- #
@callback(
    Output("satsys-rows", "data", allow_duplicate=True),
    Input("satsys-add", "n_clicks"),
    Input({"type": "satsys-rm", "index": ALL}, "n_clicks"),
    State({"type": "satsys-lbl", "index": ALL}, "value"),
    State({"type": "satsys-vol", "index": ALL}, "value"),
    State({"type": "satsys-inc", "index": ALL}, "value"),
    State({"type": "satsys-lbl", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def _add_remove(add_clicks, rm_clicks, labels, vols, incs, ids):
    rows = _rows_from_dom(labels, vols, incs, ids)
    trig = ctx.triggered_id
    if trig == "satsys-add":
        rows.append({"label": "", "vol_m3": None, "include": True})
    elif isinstance(trig, dict) and trig.get("type") == "satsys-rm":
        # a remove button actually fired (ignore the initial 0-click volley)
        if any(rm_clicks or []):
            idx = trig["index"]
            rows = [c for j, c in enumerate(rows) if j != idx]
        else:
            return no_update
    return rows


# --------------------------------------------------------------------------- #
# Live system-volume readout
# --------------------------------------------------------------------------- #
@callback(
    Output("satsys-volume", "children"),
    Input({"type": "satsys-vol", "index": ALL}, "value"),
    Input({"type": "satsys-inc", "index": ALL}, "value"),
)
def _volume(vols, incs):
    total = 0.0
    for v, inc in zip(vols or [], incs or []):
        if inc and "inc" in inc:
            try:
                total += float(v or 0)
            except (TypeError, ValueError):
                pass
    return f"System volume (included components):  {round(total, 2)} m\u00b3"


# --------------------------------------------------------------------------- #
# Save / delete
# --------------------------------------------------------------------------- #
@callback(
    Output("satsys-status", "children"),
    Output("satsys-select", "options"),
    Output("satsys-select", "value"),
    Input("satsys-save", "n_clicks"),
    State("satsys-current-id", "data"),
    State("satsys-name", "value"),
    State("satsys-bellvol", "value"),
    State("satsys-bellcfg", "value"),
    State("satsys-storage", "value"),
    State("satsys-working", "value"),
    State("satsys-divers", "value"),
    State({"type": "satsys-lbl", "index": ALL}, "value"),
    State({"type": "satsys-vol", "index": ALL}, "value"),
    State({"type": "satsys-inc", "index": ALL}, "value"),
    State({"type": "satsys-lbl", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def _save(_n, cur_id, name, bellvol, bellcfg, storage, working, divers,
          labels, vols, incs, ids):
    if not is_admin():
        raise PreventUpdate
    if not (name or "").strip():
        return (html.Span("Give the system a name before saving.", style={"color": "#b91c1c"}),
                no_update, no_update)
    components = [c for c in _rows_from_dom(labels, vols, incs, ids) if c["label"]]
    data = {
        "name": name.strip(),
        "components": components,
        "bell_vol_m3": bellvol,
        "bell_config": bellcfg or "single",
        "default_storage_m": storage,
        "default_working_m": working,
        "divers": divers,
    }
    save_id = None if cur_id in (None, NEW) else cur_id
    saved = sat_system.save_system(save_id, data)
    return (html.Span(f"Saved \u201c{saved['name']}\u201d.", style={"color": ACCENT}),
            _dropdown_options(), saved["id"])


@callback(
    Output("satsys-status", "children", allow_duplicate=True),
    Output("satsys-select", "options", allow_duplicate=True),
    Output("satsys-select", "value", allow_duplicate=True),
    Input("satsys-delete", "n_clicks"),
    State("satsys-current-id", "data"),
    prevent_initial_call=True,
)
def _delete(_n, cur_id):
    if not is_admin():
        raise PreventUpdate
    if cur_id in (None, NEW):
        return (html.Span("Nothing to delete \u2014 this system isn't saved yet.",
                          style={"color": "#b91c1c"}), no_update, no_update)
    sat_system.delete_system(cur_id)
    remaining = sat_system.list_systems()
    nxt = remaining[0]["id"] if remaining else NEW
    return (html.Span("Deleted.", style={"color": ACCENT}), _dropdown_options(), nxt)
