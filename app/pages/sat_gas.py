"""
SAT Diving — saturation gas calculator.

Two tools on one page:
  1. Minimum gas onboard — the BUKOM `Minimum Gas` model (BSS-402 / IMCA D050):
     the bottom-mix and oxygen volumes that must remain onboard once the system
     is at depth, below which diving stops and decompression starts. Per-job
     figures are entered here; the model coefficients are tunable parameters
     (locked for accounts without the edit-parameters grant, like the other
     tools). System floodable volume + bell volume come from a SAT system
     defined under Admin -> SAT systems.
  2. Blowdown gas mix — blow down on a rich gas to establish a chamber PPO2,
     then switch to lean; plus a two-gas fill to make a target bottom mix.

INDICATIVE PLANNING ONLY. The diving supervisor / gas man remains responsible.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL

from app import params, sat_system
from app.engines import sat_gas as eng

dash.register_page(__name__, path="/diving/sat-gas", name="SAT Gas",
                   category="SAT Diving", order=1)

MODULE = "/diving/sat-gas"

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
AMBER = "#b45309"

# SAT coefficient param key -> min_gas_bukom keyword argument.
KEY_TO_KW = {
    "sat_dive_rmv": "dive_rmv_lpm",
    "sat_dive_run_min": "dive_run_min",
    "sat_dive_runs": "dive_runs",
    "sat_bibs_lpm": "bibs_lpm",
    "sat_bibs_hours": "bibs_hours",
    "sat_blowdowns": "blowdowns",
    "sat_lineloss_m3_day": "lineloss_m3_day",
    "sat_lineloss_cycles": "lineloss_cycles",
    "sat_therapeutic_lpm": "therapeutic_lpm",
    "sat_therapeutic_min": "therapeutic_min_per_diver",
    "sat_o2_metabolic": "o2_metabolic",
    "sat_o2_deco_coeff": "o2_deco_coeff",
    "sat_o2_ppo2_coeff": "o2_ppo2_coeff",
    "sat_o2_reserve": "o2_reserve",
}
COEF_DEFS = [p for p in params.definitions() if p["key"] in KEY_TO_KW]

NUM = {"width": "120px", "padding": "7px 9px", "borderRadius": "8px",
       "border": "1px solid #d1d5db", "fontFamily": "ui-monospace,monospace"}
CARD = {"background": "#fff", "border": f"1px solid {GRID}", "borderRadius": "12px",
        "padding": "18px", "marginBottom": "16px"}


# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #
def _label(txt, hint=None):
    return html.Div([
        html.Label(txt, style={"fontSize": "0.76rem", "fontWeight": 600, "color": MUTED}),
        html.Div(hint, style={"fontSize": "0.68rem", "color": MUTED}) if hint else None,
    ], style={"marginBottom": "3px"})


def _field(lbl, comp, hint=None):
    return html.Div([_label(lbl, hint), comp], style={"marginBottom": "10px"})


def _section(title):
    return html.Div(title, style={"fontWeight": 700, "fontSize": "0.82rem", "color": MUTED,
                                  "textTransform": "uppercase", "letterSpacing": "0.03em",
                                  "margin": "4px 0 8px"})


def _sys_options():
    return [{"label": s.get("name") or s["id"], "value": s["id"]}
            for s in sat_system.list_systems()]


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def _job_inputs():
    systems = sat_system.list_systems()
    first = systems[0] if systems else sat_system.blank_system()
    fid = first.get("id")
    sv = sat_system.system_volume(first)
    return html.Div([
        _section("SAT system"),
        _field("System", dcc.Dropdown(id="sg-system", options=_sys_options(),
                                      value=fid, clearable=False)),
        html.Div([
            _field("Storage depth [m]",
                   dcc.Input(id="sg-storage", type="number", value=first.get("default_storage_m"),
                             step=1, min=0, debounce=True, style=NUM)),
            _field("Working / excursion depth [m]",
                   dcc.Input(id="sg-working", type="number", value=first.get("default_working_m"),
                             step=1, min=0, debounce=True, style=NUM)),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div([
            _field("System volume [m\u00b3]",
                   dcc.Input(id="sg-sysvol", type="number", value=sv, step=0.1, min=0,
                             debounce=True, style=NUM),
                   hint="From the selected system; override if needed"),
            _field("Bell configuration",
                   dcc.RadioItems(id="sg-bellcfg",
                                  options=[{"label": " Single", "value": "single"},
                                           {"label": " Twin", "value": "twin"}],
                                  value=first.get("bell_config", "single"),
                                  labelStyle={"display": "inline-block", "marginRight": "14px"},
                                  style={"marginTop": "6px"}),
                   hint="Twin doubles the dive/bell gas reserve only"),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),

        _section("Job"),
        html.Div([
            _field("Decompression time [h]",
                   dcc.Input(id="sg-decoh", type="number", value=108, step=1, min=0,
                             debounce=True, style=NUM),
                   hint="Read off the SAT Decompression page"),
            _field("Divers in saturation",
                   dcc.Input(id="sg-divers", type="number", value=first.get("divers", 9),
                             step=1, min=0, debounce=True, style=NUM)),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),

        _section("Crew change"),
        html.Div([
            _field("Divers locked out per bell",
                   dcc.Input(id="sg-lockout", type="number", value=2, step=1, min=0,
                             debounce=True, style=NUM),
                   hint="Feeds the dive/bell gas reserve"),
            _field("Bell runs per day",
                   dcc.Input(id="sg-runsday", type="number", value=3, step=1, min=0,
                             debounce=True, style=NUM),
                   hint="Recorded now; feeds the later deco/recompression model"),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div("Bell runs per day does not change the minimum gas below \u2014 it is "
                 "recorded for the diver decompression / recompression model coming next.",
                 style={"fontSize": "0.68rem", "color": MUTED, "marginTop": "-2px"}),
    ])


def _coefficients_panel():
    try:
        from app import auth
        locked = not auth.may_edit_params(auth.current_user(), MODULE)
    except Exception:
        locked = True
    note = html.Div(
        "Gas-model coefficients are set by an administrator and locked for your account.",
        style={"fontSize": "0.72rem", "color": AMBER, "background": "#fffbeb",
               "border": "1px solid #fde68a", "borderRadius": "6px", "padding": "6px 8px",
               "marginBottom": "10px"}) if locked else None

    fields = []
    for p in COEF_DEFS:
        fields.append(html.Div([
            html.Label(p["label"] + (f"  [{p['unit']}]" if p["unit"] else ""),
                       style={"fontSize": "0.72rem", "fontWeight": 600, "color": INK,
                              "display": "block", "marginBottom": "2px"}),
            dcc.Input(id={"type": "sg-coef", "key": p["key"]}, type="number",
                      value=params.get_float(p["key"]), step=p["step"], min=0,
                      debounce=True, disabled=locked,
                      style={**NUM, "width": "100%", "boxSizing": "border-box"}),
        ], style={"marginBottom": "8px"}))

    body = [
        _section("Gas-model coefficients (BUKOM / BSS-402)"),
        note,
        html.Div(fields, style={"display": "grid",
                                "gridTemplateColumns": "repeat(auto-fill,minmax(170px,1fr))",
                                "gap": "0 14px"}),
    ]
    if not locked:
        body += [
            html.Button("Save as defaults", id="sg-coef-save", n_clicks=0, style={
                "padding": "8px 14px", "borderRadius": "8px", "border": "none",
                "background": ACCENT, "color": "#fff", "fontWeight": 600,
                "cursor": "pointer", "marginTop": "4px"}),
            html.Div(id="sg-coef-status", style={"fontSize": "0.78rem", "marginTop": "6px",
                                                 "minHeight": "1em"}),
        ]
    else:
        body += [html.Div(id="sg-coef-status", style={"display": "none"})]
    return html.Div(body, style=CARD)


def _blowdown_panel():
    return html.Div([
        _section("Blowdown gas mix"),
        html.Div("Blow down on the rich gas to establish the chamber PPO\u2082, then switch "
                 "to the lean gas for the rest.", style={"fontSize": "0.74rem", "color": MUTED,
                                                         "marginBottom": "8px"}),
        html.Div([
            _field("Target chamber PPO\u2082 [mb]",
                   dcc.Input(id="sg-ppo2", type="number", value=500, step=10, min=0,
                             debounce=True, style=NUM)),
            _field("Chamber depth [m]",
                   dcc.Input(id="sg-chdepth", type="number", value=40, step=1, min=0,
                             debounce=True, style=NUM)),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div([
            _field("Rich gas O\u2082 [%]",
                   dcc.Input(id="sg-rich", type="number", value=7.5, step=0.1, min=0,
                             debounce=True, style=NUM)),
            _field("Lean gas O\u2082 [%]",
                   dcc.Input(id="sg-lean", type="number", value=2.2, step=0.1, min=0,
                             debounce=True, style=NUM)),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div(id="sg-blowdown-out", style={"marginTop": "6px"}),

        html.Div(style={"height": "10px", "borderTop": f"1px solid {GRID}", "marginTop": "10px"}),
        _section("Make a bottom mix (two gas)"),
        html.Div([
            _field("Target mix O\u2082 [%]",
                   dcc.Input(id="sg-tgt", type="number", value=12, step=0.1, min=0,
                             debounce=True, style=NUM)),
            _field("Fill to [bar]",
                   dcc.Input(id="sg-fill", type="number", value=200, step=1, min=0,
                             debounce=True, style=NUM)),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div(id="sg-fill-out", style={"marginTop": "4px"}),
    ], style=CARD)


def layout():
    return html.Div([
        html.H3("SAT gas"),
        html.P(["Minimum gas onboard (BUKOM ", html.Code("Minimum Gas"),
                ", BSS-402 / IMCA D050) and blowdown mix for saturation operations. "
                "Select a SAT system for its floodable and bell volumes, or override "
                "the volume directly."],
               style={"color": MUTED, "maxWidth": "720px"}),

        html.Div([
            html.Div([html.Div(_job_inputs(), style=CARD), _coefficients_panel()],
                     style={"flex": "1 1 420px", "minWidth": "360px"}),
            html.Div([html.Div(id="sg-mingas-out", style=CARD), _blowdown_panel()],
                     style={"flex": "1 1 420px", "minWidth": "360px"}),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),

        html.Div("Indicative planning only. Figures follow the Boskalis BSS-402 "
                 "(issue 2018.02.14) / IMCA D050 minimum-gas model; the diving "
                 "supervisor and gas man remain responsible for the gas plan.",
                 style={"fontSize": "0.74rem", "color": MUTED, "marginTop": "10px",
                        "paddingTop": "12px", "borderTop": f"1px solid {GRID}"}),
    ], style={"maxWidth": "1000px"})


# --------------------------------------------------------------------------- #
# Seed job inputs from the selected system
# --------------------------------------------------------------------------- #
@callback(
    Output("sg-storage", "value"),
    Output("sg-working", "value"),
    Output("sg-sysvol", "value"),
    Output("sg-bellcfg", "value"),
    Output("sg-divers", "value"),
    Input("sg-system", "value"),
)
def _seed_from_system(sid):
    s = sat_system.get_system(sid) if sid else None
    if not s:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
    return (s.get("default_storage_m"), s.get("default_working_m"),
            sat_system.system_volume(s), s.get("bell_config", "single"),
            s.get("divers", 9))


# --------------------------------------------------------------------------- #
# Minimum gas
# --------------------------------------------------------------------------- #
def _num(v, dp=1, unit=" m\u00b3"):
    try:
        return f"{float(v):,.{dp}f}{unit}"
    except (TypeError, ValueError):
        return "\u2014"


def _mingas_table(res):
    rows = []
    for key, (label, why) in eng.MIX_LABELS.items():
        rows.append(html.Tr([
            html.Td(label, style={"padding": "4px 8px", "fontWeight": 600, "color": INK}),
            html.Td(why, style={"padding": "4px 8px", "color": MUTED, "fontSize": "0.76rem"}),
            html.Td(_num(res["mix"][key]), style={"padding": "4px 8px", "textAlign": "right",
                                                  "fontFamily": "ui-monospace,monospace"}),
        ]))
    rows.append(html.Tr([
        html.Td("Bottom mix total", colSpan=2,
                style={"padding": "6px 8px", "fontWeight": 700, "color": INK,
                       "borderTop": f"1px solid {GRID}"}),
        html.Td(_num(res["mix_total"]), style={"padding": "6px 8px", "textAlign": "right",
                                               "fontWeight": 700, "color": ACCENT,
                                               "fontFamily": "ui-monospace,monospace",
                                               "borderTop": f"1px solid {GRID}"}),
    ]))
    o = res["oxygen"]
    for label, val in [("Oxygen \u00b7 metabolic", o["metabolic"]),
                       ("Oxygen \u00b7 decompression", o["deco"]),
                       ("Oxygen \u00b7 PPO\u2082 build-up", o["ppo2"]),
                       ("Oxygen \u00b7 reserve", o["reserve"])]:
        rows.append(html.Tr([
            html.Td(label, colSpan=2, style={"padding": "4px 8px", "color": MUTED,
                                             "fontSize": "0.78rem"}),
            html.Td(_num(val), style={"padding": "4px 8px", "textAlign": "right",
                                      "fontFamily": "ui-monospace,monospace"}),
        ]))
    rows.append(html.Tr([
        html.Td("Oxygen total", colSpan=2,
                style={"padding": "6px 8px", "fontWeight": 700, "color": INK,
                       "borderTop": f"1px solid {GRID}"}),
        html.Td(_num(o["total"]), style={"padding": "6px 8px", "textAlign": "right",
                                         "fontWeight": 700, "color": ACCENT,
                                         "fontFamily": "ui-monospace,monospace",
                                         "borderTop": f"1px solid {GRID}"}),
    ]))
    return html.Table(html.Tbody(rows), style={"width": "100%", "borderCollapse": "collapse",
                                               "fontSize": "0.85rem"})


@callback(
    Output("sg-mingas-out", "children"),
    Input("sg-storage", "value"),
    Input("sg-working", "value"),
    Input("sg-sysvol", "value"),
    Input("sg-decoh", "value"),
    Input("sg-divers", "value"),
    Input("sg-lockout", "value"),
    Input("sg-bellcfg", "value"),
    Input({"type": "sg-coef", "key": ALL}, "value"),
    State({"type": "sg-coef", "key": ALL}, "id"),
)
def _compute_mingas(storage, working, sysvol, decoh, divers, lockout, bellcfg, coef_vals, coef_ids):
    try:
        storage = float(storage); working = float(working); sysvol = float(sysvol)
        decoh = float(decoh); divers = float(divers); lockout = float(lockout)
    except (TypeError, ValueError):
        return html.Div("Enter storage, working depth, system volume, deco time and divers.",
                        style={"color": MUTED, "fontSize": "0.85rem"})

    # coefficient values from the on-screen fields (locked -> the admin defaults)
    kw = {}
    for _id, v in zip(coef_ids or [], coef_vals or []):
        kwname = KEY_TO_KW.get(_id["key"])
        if kwname is not None:
            try:
                kw[kwname] = float(v)
            except (TypeError, ValueError):
                kw[kwname] = params.get_float(_id["key"])

    bells = 2 if bellcfg == "twin" else 1
    res = eng.min_gas_bukom(storage, working, sysvol, decoh, divers,
                            bells=bells, divers_per_bell=lockout, **kw)
    return html.Div([
        _section("Minimum gas onboard"),
        html.Div(f"Storage {storage:g} m \u00b7 working {working:g} m \u00b7 "
                 f"{sysvol:g} m\u00b3 system \u00b7 {res['inputs']['deco_days']:.2f} deco days "
                 f"\u00b7 {divers:g} divers \u00b7 {bellcfg} bell",
                 style={"fontSize": "0.74rem", "color": MUTED, "marginBottom": "8px"}),
        _mingas_table(res),
    ])


# --------------------------------------------------------------------------- #
# Blowdown mix + two-gas fill
# --------------------------------------------------------------------------- #
@callback(
    Output("sg-blowdown-out", "children"),
    Input("sg-ppo2", "value"),
    Input("sg-chdepth", "value"),
    Input("sg-rich", "value"),
    Input("sg-lean", "value"),
)
def _compute_blowdown(ppo2, depth, rich, lean):
    try:
        ppo2 = float(ppo2); depth = float(depth); rich = float(rich); lean = float(lean)
    except (TypeError, ValueError):
        return None
    m = eng.blowdown_on_rich(ppo2, depth, rich, lean)
    if m is None:
        return html.Div("Rich and lean gases must differ in O\u2082 %.",
                        style={"color": "#b91c1c", "fontSize": "0.82rem"})
    if m < 0:
        return html.Div("No rich-gas leg needed for this PPO\u2082 (result negative) \u2014 "
                        "check the target and gas mixes.",
                        style={"color": AMBER, "fontSize": "0.82rem"})
    return html.Div([
        html.Span("Blow down to ", style={"color": MUTED}),
        html.Strong(f"{m:.1f} m", style={"color": ACCENT}),
        html.Span(f" on the {rich:g}% rich gas, then continue on the {lean:g}% lean gas to depth.",
                  style={"color": MUTED}),
    ], style={"fontSize": "0.9rem"})


@callback(
    Output("sg-fill-out", "children"),
    Input("sg-tgt", "value"),
    Input("sg-fill", "value"),
    Input("sg-rich", "value"),
    Input("sg-lean", "value"),
)
def _compute_fill(tgt, fill, rich, lean):
    try:
        tgt = float(tgt); fill = float(fill); rich = float(rich); lean = float(lean)
    except (TypeError, ValueError):
        return None
    bar_rich, bar_lean = eng.two_gas_fill(fill, lean, rich, tgt)
    if bar_rich is None:
        return html.Div("Rich and lean gases must differ in O\u2082 %.",
                        style={"color": "#b91c1c", "fontSize": "0.82rem"})
    warn = None
    if bar_rich < 0 or bar_lean < 0:
        warn = html.Div("Target O\u2082 is outside the rich/lean range \u2014 not achievable "
                        "with these two gases.", style={"color": AMBER, "fontSize": "0.78rem"})
    return html.Div([
        html.Span(f"Charge {rich:g}% rich to ", style={"color": MUTED}),
        html.Strong(f"{bar_rich:.1f} bar", style={"color": ACCENT}),
        html.Span(f", then top up with {lean:g}% lean to {fill:g} bar "
                  f"({bar_lean:.1f} bar of lean).", style={"color": MUTED}),
        warn,
    ], style={"fontSize": "0.9rem"})


# --------------------------------------------------------------------------- #
# Save coefficients (only reachable when the user may edit params)
# --------------------------------------------------------------------------- #
@callback(
    Output("sg-coef-status", "children"),
    Input("sg-coef-save", "n_clicks"),
    State({"type": "sg-coef", "key": ALL}, "value"),
    State({"type": "sg-coef", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def _save_coefs(_n, values, ids):
    from app import auth
    if not auth.may_edit_params(auth.current_user(), MODULE):
        return html.Span("Not permitted.", style={"color": "#b91c1c"})
    mapping = {i["key"]: v for i, v in zip(ids or [], values or [])}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"})
