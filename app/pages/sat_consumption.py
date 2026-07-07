"""
SAT Diving — saturation gas consumption & cost.

The consumption/procurement companion to the minimum-gas page: initial system
blowdown mix, daily chamber and diver losses, metabolic oxygen (operations and
decompression), sodasorb, bell pressurisation and lockout gas, a reclaim-
adjusted loss per lock/trunk, and the resulting gas cost. Ported from the DCN
Picasso gas workbook and validated against it.

Per-job figures and system volumes are entered here; the rates, efficiencies and
unit costs are tunable parameters, locked for accounts without the edit grant.

INDICATIVE PLANNING ONLY.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, ALL

from app import params
from app.engines import sat_consumption as eng

dash.register_page(__name__, path="/diving/sat-consumption", name="SAT Consumption",
                   category="SAT Diving", order=2)

MODULE = "/diving/sat-consumption"

MUTED = "#64748b"
ACCENT = "#0f766e"
INK = "#0f172a"
GRID = "#e2e8f0"
AMBER = "#b45309"

# coefficient param key -> consumption() keyword argument
KEY_TO_KW = {
    "sat_c_o2_resting": "o2_resting", "sat_c_o2_moderate": "o2_moderate",
    "sat_c_br_working": "br_working", "sat_c_br_bellman": "br_bellman",
    "sat_c_sodasorb_pp_day": "sodasorb_per_person_day",
    "sat_c_loss_chamber": "loss_chamber", "sat_c_loss_diver": "loss_diver",
    "sat_c_reclaim": "reclaim", "sat_c_blowdown_ppo2": "blowdown_ppo2",
    "sat_c_mix_a_o2": "mix_a_o2", "sat_c_mix_b_o2": "mix_b_o2", "sat_c_deco_ppo2": "deco_ppo2",
    "sat_c_cost_heliox": "cost_heliox", "sat_c_cost_o2": "cost_o2",
    "sat_c_cost_sodasorb": "cost_sodasorb",
}
COEF_DEFS = [p for p in params.definitions() if p["key"] in KEY_TO_KW]

NUM = {"width": "110px", "padding": "7px 9px", "borderRadius": "8px",
       "border": "1px solid #d1d5db", "fontFamily": "ui-monospace,monospace"}
CARD = {"background": "#fff", "border": f"1px solid {GRID}", "borderRadius": "12px",
        "padding": "18px", "marginBottom": "16px"}

# per-job / activity / volume inputs: (id, label, default, step, hint)
JOB = [
    ("sc-storage", "Storage depth [m]", 60, 1, None),
    ("sc-working", "Working depth [m]", 70, 1, None),
    ("sc-occupants", "System occupants", 9, 1, None),
    ("sc-workdivers", "Working divers", 2, 1, None),
    ("sc-bellman", "Bellman", 1, 1, None),
    ("sc-runs", "Bell runs per day", 3, 1, None),
    ("sc-lockhours", "Lockout hours per run", 6, 0.5, None),
    ("sc-jobdays", "Job duration [days]", 1, 1, None),
    ("sc-decoh", "Decompression time [h]", 78, 1, "Default: USN-7a estimate"),
]
ACTIVITY = [
    ("sc-medlock", "Medical lock uses / day", 20, 1, None),
    ("sc-entrylock", "Entry lock uses / day", 1, 1, None),
    ("sc-eqlock", "Equipment lock uses / day", 3, 1, None),
    ("sc-wetpot", "Wet-pot depress / day", 0, 1, None),
    ("sc-belldepress", "Bell depress / day", 0.1, 0.1, "1 every 10 days = 0.1"),
]
VOLUMES = [
    ("sc-vsys", "System volume [m\u00b3]", 215.65, 0.1, "Floodable, bells included"),
    ("sc-vbell", "Bell volume [m\u00b3]", 6.49, 0.01, None),
    ("sc-vbelltrunk", "Bell trunk [m\u00b3]", 0.251, 0.01, None),
    ("sc-vwetpot", "Wet-pot [m\u00b3]", 26.0, 0.1, None),
    ("sc-ventry", "Entry lock [m\u00b3]", 7.4, 0.1, None),
    ("sc-vmedlock", "Medical lock [m\u00b3]", 0.035, 0.005, None),
    ("sc-veqlock", "Equipment lock [m\u00b3]", 0.4, 0.1, None),
]

# input id -> consumption() kwarg
INPUT_KW = {
    "sc-storage": "storage_m", "sc-working": "working_m", "sc-occupants": "occupants",
    "sc-workdivers": "working_divers", "sc-bellman": "bellman", "sc-runs": "bell_runs_day",
    "sc-lockhours": "lockout_hours", "sc-jobdays": "job_days", "sc-decoh": "deco_hours",
    "sc-medlock": "medlock_uses", "sc-entrylock": "entrylock_uses", "sc-eqlock": "eqlock_uses",
    "sc-wetpot": "wetpot_depress", "sc-belldepress": "bell_depress",
    "sc-vsys": "v_sys", "sc-vbell": "v_bell", "sc-vbelltrunk": "v_belltrunk",
    "sc-vwetpot": "v_wetpot", "sc-ventry": "v_entry", "sc-vmedlock": "v_medlock",
    "sc-veqlock": "v_eqlock",
}
ALL_INPUT_IDS = [i for (i, *_r) in JOB + ACTIVITY + VOLUMES]


def _section(title):
    return html.Div(title, style={"fontWeight": 700, "fontSize": "0.82rem", "color": MUTED,
                                  "textTransform": "uppercase", "letterSpacing": "0.03em",
                                  "margin": "6px 0 8px"})


def _field(id_, label, default, step, hint):
    return html.Div([
        html.Label(label, style={"fontSize": "0.74rem", "fontWeight": 600, "color": INK,
                                 "display": "block", "marginBottom": "2px"}),
        dcc.Input(id=id_, type="number", value=default, step=step, debounce=True, style=NUM),
        html.Div(hint, style={"fontSize": "0.66rem", "color": MUTED}) if hint else None,
    ], style={"marginBottom": "8px"})


def _grid(fields):
    return html.Div([_field(*f) for f in fields],
                    style={"display": "grid",
                           "gridTemplateColumns": "repeat(auto-fill,minmax(150px,1fr))",
                           "gap": "0 14px"})


def _inputs_card():
    return html.Div([
        _section("Job"), _grid(JOB),
        _section("Lock / bell activity"), _grid(ACTIVITY),
        _section("System volumes"), _grid(VOLUMES),
    ], style=CARD)


def _coefficients_panel():
    try:
        from app import auth
        locked = not auth.may_edit_params(auth.current_user(), MODULE)
    except Exception:
        locked = True
    note = html.Div(
        "Consumption assumptions are set by an administrator and locked for your account.",
        style={"fontSize": "0.72rem", "color": AMBER, "background": "#fffbeb",
               "border": "1px solid #fde68a", "borderRadius": "6px", "padding": "6px 8px",
               "marginBottom": "10px"}) if locked else None
    fields = []
    for p in COEF_DEFS:
        fields.append(html.Div([
            html.Label(p["label"] + (f"  [{p['unit']}]" if p["unit"] else ""),
                       style={"fontSize": "0.7rem", "fontWeight": 600, "color": INK,
                              "display": "block", "marginBottom": "2px"}),
            dcc.Input(id={"type": "sc-coef", "key": p["key"]}, type="number",
                      value=params.get_float(p["key"]), step=p["step"], debounce=True,
                      disabled=locked, style={**NUM, "width": "100%", "boxSizing": "border-box"}),
        ], style={"marginBottom": "8px"}))
    body = [_section("Consumption assumptions"), note,
            html.Div(fields, style={"display": "grid",
                                    "gridTemplateColumns": "repeat(auto-fill,minmax(160px,1fr))",
                                    "gap": "0 14px"})]
    if not locked:
        body += [html.Button("Save as defaults", id="sc-coef-save", n_clicks=0, style={
            "padding": "8px 14px", "borderRadius": "8px", "border": "none",
            "background": ACCENT, "color": "#fff", "fontWeight": 600, "cursor": "pointer",
            "marginTop": "4px"}),
            html.Div(id="sc-coef-status", style={"fontSize": "0.78rem", "marginTop": "6px",
                                                 "minHeight": "1em"})]
    else:
        body += [html.Div(id="sc-coef-status", style={"display": "none"})]
    return html.Div(body, style=CARD)


def layout():
    return html.Div([
        html.H3("SAT gas consumption & cost"),
        html.P("Estimated blowdown mix, daily consumption, decompression oxygen and cost "
               "for a saturation job \u2014 the procurement companion to the minimum-gas page.",
               style={"color": MUTED, "maxWidth": "760px"}),
        html.Div([
            html.Div([_inputs_card(), _coefficients_panel()],
                     style={"flex": "1 1 440px", "minWidth": "380px"}),
            html.Div(id="sc-results", style={"flex": "1 1 420px", "minWidth": "360px"}),
        ], style={"display": "flex", "gap": "18px", "flexWrap": "wrap"}),
        html.Div("Indicative planning only. Ported from the DCN Picasso gas workbook; the "
                 "diving supervisor and gas man remain responsible for the gas plan.",
                 style={"fontSize": "0.74rem", "color": MUTED, "marginTop": "10px",
                        "paddingTop": "12px", "borderTop": f"1px solid {GRID}"}),
    ], style={"maxWidth": "1040px"})


# --------------------------------------------------------------------------- #
# Compute
# --------------------------------------------------------------------------- #
def _m3(v, dp=1):
    try:
        return f"{float(v):,.{dp}f} m\u00b3"
    except (TypeError, ValueError):
        return "\u2014"


def _eur(v):
    try:
        return f"\u20ac{float(v):,.0f}"
    except (TypeError, ValueError):
        return "\u2014"


def _row(label, value, bold=False, sub=False, border=False):
    td = {"padding": "4px 8px"}
    lab = {**td, "color": (INK if bold else MUTED) if sub else INK,
           "fontWeight": 700 if bold else (400 if sub else 600),
           "fontSize": "0.78rem" if sub else "0.85rem"}
    val = {**td, "textAlign": "right", "fontFamily": "ui-monospace,monospace",
           "fontWeight": 700 if bold else 400,
           "color": ACCENT if bold else INK, "fontSize": "0.85rem"}
    if border:
        lab["borderTop"] = f"1px solid {GRID}"; val["borderTop"] = f"1px solid {GRID}"
    return html.Tr([html.Td(label, style=lab), html.Td(value, style=val)])


def _table(rows):
    return html.Table(html.Tbody(rows),
                      style={"width": "100%", "borderCollapse": "collapse", "marginBottom": "4px"})


@callback(
    Output("sc-results", "children"),
    [Input(i, "value") for i in ALL_INPUT_IDS],
    Input({"type": "sc-coef", "key": ALL}, "value"),
    State({"type": "sc-coef", "key": ALL}, "id"),
)
def _compute(*args):
    n = len(ALL_INPUT_IDS)
    job_vals = args[:n]
    coef_vals = args[n]
    coef_ids = args[n + 1]

    kw = {}
    for id_, v in zip(ALL_INPUT_IDS, job_vals):
        try:
            kw[INPUT_KW[id_]] = float(v)
        except (TypeError, ValueError):
            return html.Div("Fill in all job, activity and volume fields.",
                            style=CARD | {"color": MUTED, "fontSize": "0.85rem"})
    for id_, v in zip(coef_ids or [], coef_vals or []):
        kwname = KEY_TO_KW.get(id_["key"])
        if kwname:
            try:
                kw[kwname] = float(v)
            except (TypeError, ValueError):
                kw[kwname] = params.get_float(id_["key"])

    r = eng.consumption(**kw)
    b, d, dec, cost = r["blowdown"], r["daily"], r["deco"], r["cost"]
    a_pct = kw.get("mix_a_o2", 0.20) * 100
    b_pct = kw.get("mix_b_o2", 0.02) * 100
    jobdays = kw.get("job_days", 1)

    blowdown = html.Div([
        _section("Initial system blowdown"),
        _table([
            _row(f"Mix A ({a_pct:g}% O\u2082)", _m3(b["mix_a"])),
            _row(f"Mix B ({b_pct:g}% O\u2082)", _m3(b["mix_b"])),
            _row("Total blowdown", _m3(b["total"]), bold=True, border=True),
        ]),
    ], style=CARD)

    reclaim_rows = [_row(eng.RECLAIM_LABELS[k], _m3(v, 2), sub=True)
                    for k, v in d["reclaim_rows"].items()]
    daily = html.Div([
        _section("Daily consumption"),
        _table([
            _row("Chamber loss (heliox)", _m3(d["chamber_loss"], 2)),
            _row("Metabolic O\u2082 (ops)", _m3(d["o2_ops"], 2)),
            _row("Sodasorb", f"{d['sodasorb']:.1f} units"),
            _row("Bell pressurisation", _m3(d["bell_pressurisation"], 2)),
            _row("Diver lockout gas", _m3(d["lockout_gas"], 1)),
            _row("Lockout loss", _m3(d["lockout_loss"], 2)),
        ]),
        html.Div("Reclaim-adjusted losses", style={"fontSize": "0.72rem", "fontWeight": 700,
                                                   "color": MUTED, "margin": "8px 0 2px"}),
        _table(reclaim_rows + [_row("Reclaim total", _m3(d["reclaim_total"], 2),
                                    bold=True, border=True)]),
    ], style=CARD)

    deco = html.Div([
        _section(f"Decompression oxygen ({r['inputs']['deco_hours']:.0f} h)"),
        _table([
            _row("Chamber (log-O\u2082)", _m3(dec["chamber"])),
            _row("Metabolic", _m3(dec["metabolic"])),
            _row("Total deco O\u2082", _m3(dec["total"]), bold=True, border=True),
        ]),
    ], style=CARD)

    costcard = html.Div([
        _section("Cost"),
        _table([
            _row("Heliox losses", _eur(cost["heliox_losses"])),
            _row("Heliox consumption", _eur(cost["heliox_consumption"])),
            _row("Metabolic O\u2082", _eur(cost["o2_metabolic"])),
            _row("Sodasorb", _eur(cost["sodasorb"])),
            _row("Daily operational", _eur(cost["daily_total"]), bold=True, border=True),
            _row(f"\u00d7 {jobdays:g} days", _eur(cost["daily_total"] * jobdays)),
            _row("One-off blowdown", _eur(cost["blowdown"])),
            _row("Project total (ops + blowdown)", _eur(cost["project_total"]),
                 bold=True, border=True),
        ]),
        html.Div("Project total combines daily operational cost over the job with the "
                 "one-off initial blowdown. Deco O\u2082 shown above is not yet costed in.",
                 style={"fontSize": "0.68rem", "color": MUTED, "marginTop": "4px"}),
    ], style=CARD)

    return [blowdown, daily, deco, costcard]


# --------------------------------------------------------------------------- #
# Save coefficients (only when the user may edit params)
# --------------------------------------------------------------------------- #
@callback(
    Output("sc-coef-status", "children"),
    Input("sc-coef-save", "n_clicks"),
    State({"type": "sc-coef", "key": ALL}, "value"),
    State({"type": "sc-coef", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def _save_coefs(_n, values, ids):
    from app import auth
    if not auth.may_edit_params(auth.current_user(), MODULE):
        return html.Span("Not permitted.", style={"color": "#b91c1c"})
    mapping = {i["key"]: v for i, v in zip(ids or [], values or [])}
    n, msg = params.set_many(mapping)
    return html.Span(msg, style={"color": ACCENT if n else "#b91c1c"})
