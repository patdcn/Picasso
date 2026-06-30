"""
Diving — Single vs Twin Bell DSV productivity & cost.

Full native-Dash port of the original HTML calculator. Pure-maths lives in
app/engines/bell.py; this page is the thin UI: inputs -> engine -> rendered
scenario cards, 24h timeline bars, efficiency & cost charts, project projection,
hero stats and verdict.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback, no_update

from app.engines.bell import BellInputs, run_comparison
from app import params, auth, reports

PDF_BTN_STYLE = {
    "padding": "8px 14px", "borderRadius": "8px", "border": "none",
    "background": "#0f766e", "color": "#fff", "fontWeight": 600,
    "cursor": "pointer", "fontSize": "0.85rem",
}

dash.register_page(__name__, path="/diving/bell", name="Single vs twin bell",
                   category="Diving", order=1)

GREEN = "#16a34a"
GREEN_SOFT = "#dcfce7"
AMBER = "#d97706"
TRANSIT = "#64748b"
INK = "#1f2937"
MUTED = "#6b7280"


def fmt_h(h):
    return f"{h:,.1f}"


def fmt_money(v, cur):
    sep = " " if len(cur) > 1 else ""
    return f"{cur}{sep}{round(v):,}"


def fmt_money_m(v, cur):
    sep = " " if len(cur) > 1 else ""
    return f"{cur}{sep}{v/1e6:,.2f}M"


def _num(id_, label, value, step, minv=None, maxv=None, hint="", disabled=False):
    style = {"width": "100%", "padding": "7px 9px", "borderRadius": "8px",
             "border": "1px solid #d1d5db", "fontFamily": "monospace"}
    if disabled:
        style.update({"background": "#f1f5f9", "color": "#64748b", "cursor": "not-allowed"})
    kw = {"type": "number", "value": value, "step": step, "id": id_, "style": style,
          "disabled": disabled}
    if minv is not None:
        kw["min"] = minv
    if maxv is not None:
        kw["max"] = maxv
    return html.Div([
        html.Label(label, style={"fontSize": "0.8rem", "fontWeight": 600, "color": INK}),
        dcc.Input(**kw),
        html.Div(hint, style={"fontSize": "0.7rem", "color": MUTED, "marginTop": "2px"}) if hint else None,
    ], style={"marginBottom": "10px"})


def _controls():
    try:
        locked = not auth.may_edit_params(auth.current_user(), "/diving/bell")
    except Exception:
        locked = True
    note = html.Div(
        "Assumptions are set by an administrator and locked for your account.",
        style={"fontSize": "0.72rem", "color": "#b45309", "background": "#fffbeb",
               "border": "1px solid #fde68a", "borderRadius": "6px",
               "padding": "6px 8px", "marginBottom": "10px"}) if locked else None
    return html.Div([
    html.Div("Assumptions", style={"fontWeight": 700, "fontSize": "0.95rem", "marginBottom": "10px"}),
    note,
    _num("W", "Max out-of-bell time (h)", 6, 0.5, 1, hint="dive window per lockout", disabled=locked),
    _num("C", "Bell changeover (h)", params.get_float("bell_changeover_h"), 0.25, 0, disabled=locked),
    _num("T", "Bell to job transit (min, one way)", params.get_float("bell_transit_min"), 1, 0, disabled=locked),
    _num("B", "Bellsman top-up - S1 only (h)", 1, 0.5, 0, disabled=locked),
    _num("E", "Bellsman reduced work rate", 0.5, 0.05, 0, 1, hint="fraction of a full pair", disabled=locked),
    html.Hr(style={"border": "none", "borderTop": "1px solid #eee", "margin": "12px 0"}),
    _num("R1", "Day rate - single 9-man", params.get_float("day_rate_single_9man"), 1000, 0, disabled=locked),
    _num("R2", "Day rate - single 12-man", params.get_float("day_rate_single_12man"), 1000, 0, disabled=locked),
    _num("R3", "Day rate - twin 12-man", params.get_float("day_rate_twin_12man"), 1000, 0, disabled=locked),
    _num("dur", "Base-case duration (days)", 50, 1, 1, hint="defines the fixed scope", disabled=locked),
    html.Div([
        html.Label("Display currency", style={"fontSize": "0.8rem", "fontWeight": 600}),
        dcc.RadioItems(id="CUR", value="USD",
                       options=[{"label": " USD ($)", "value": "USD"},
                                {"label": " EUR (\u20ac)", "value": "EUR"}],
                       inputStyle={"marginRight": "4px"},
                       labelStyle={"display": "inline-block", "marginRight": "16px",
                                   "fontSize": "0.9rem", "cursor": "pointer"},
                       style={"marginTop": "4px"}),
        html.Div([
            html.Label("USD \u2192 EUR exchange rate",
                       style={"fontSize": "0.75rem", "fontWeight": 600, "color": INK}),
            dcc.Input(id="FX", type="number", value=params.get_float("usd_eur_rate"),
                      step=0.001, min=0, debounce=True,
                      style={"width": "100%", "padding": "6px 9px", "borderRadius": "8px",
                             "border": "1px solid #d1d5db", "fontFamily": "monospace",
                             "boxSizing": "border-box"}),
        ], style={"marginTop": "8px"}),
        html.Div("Defaults to the admin rate; change it here to re-convert if it's "
                 "out of date. Resets to the admin value on reload.",
                 style={"fontSize": "0.68rem", "color": MUTED, "marginTop": "4px"}),
    ]),
    dcc.Store(id="bell-usd-basis", data={
        "R1": params.get_float("day_rate_single_9man"),
        "R2": params.get_float("day_rate_single_12man"),
        "R3": params.get_float("day_rate_twin_12man"),
    }),
], className="assump-panel", style={
    "flex": "0 0 280px", "padding": "16px", "background": "#fafafa",
    "border": "1px solid #e5e7eb", "borderRadius": "12px", "alignSelf": "flex-start",
    "position": "sticky", "top": "72px", "maxHeight": "calc(100vh - 96px)", "overflowY": "auto",
})


def timeline_bar(s, C, Tmin):
    scale = 24.0
    one_way = Tmin / 60.0
    segs = []
    if s.vessel == "twin":
        for _ in range(s.runs):
            segs.append(("work", s.pair_win))
    else:
        for _ in range(s.runs):
            segs.append(("chg", C))
            segs.append(("trans", one_way))
            segs.append(("work", s.pair_job))
            segs.append(("trans", one_way))
            if s.bell_win > 0:
                segs.append(("trans", one_way))
                segs.append(("bell", s.bs_job))
                segs.append(("trans", one_way))
    colors = {"work": GREEN, "bell": "#86efac", "trans": TRANSIT, "chg": AMBER}
    children = [html.Div(style={
        "width": f"{max(0, h)/scale*100}%", "background": colors[t], "height": "100%",
        "borderRight": "1px solid rgba(255,255,255,.5)"}) for t, h in segs if h > 0]
    return html.Div(children, style={
        "display": "flex", "height": "22px", "borderRadius": "6px",
        "overflow": "hidden", "border": "1px solid #e5e7eb", "background": "#f3f4f6"})


def legend():
    items = [("On the job", GREEN), ("Bellsman (half rate)", "#86efac"),
             ("Transit", TRANSIT), ("Changeover", AMBER)]
    return html.Div([
        html.Span([
            html.Span(style={"display": "inline-block", "width": "10px", "height": "10px",
                             "background": c, "borderRadius": "2px", "marginRight": "5px"}),
            lbl,
        ], style={"fontSize": "0.72rem", "color": MUTED, "marginRight": "14px"})
        for lbl, c in items
    ], style={"marginTop": "8px"})


def _chip():
    return {"fontSize": "0.78rem", "padding": "3px 9px", "borderRadius": "999px",
            "background": "#f3f4f6", "color": INK}


def scenario_card(s, r, cur):
    C, T = r.inputs.C, r.inputs.T
    if s.vessel == "twin":
        if s.continuous:
            note = html.Div(
                f"Relief crews hand over on the seabed, so someone is always working - "
                f"transit and changeover never stop the job. A full {fmt_h(s.on_job_eff)}h on the job.",
                style={"color": GREEN, "fontSize": "0.82rem", "marginTop": "10px"})
        else:
            note = html.Div(
                f"Changeover ({fmt_h(C)}h) now exceeds the {fmt_h(r.inputs.W)}h dive window, so the "
                f"relief bell can't reach the job before the working crew leaves. Continuous cover "
                f"breaks down - even the twin drops to {fmt_h(s.on_job_eff)}h on the job.",
                style={"color": AMBER, "fontSize": "0.82rem", "marginTop": "10px"})
    elif s.shortened:
        note = html.Div(
            f"Each dive is cut to {fmt_h(s.pair_win)}h so {s.runs} runs + changeovers fit the day. "
            f"After {T:.0f}+{T:.0f} min transit each run, only {fmt_h(s.on_job_eff)}h is actually "
            f"spent on the job.",
            style={"color": AMBER, "fontSize": "0.82rem", "marginTop": "10px"})
    else:
        note = html.Div(
            f"Two lockouts per run - the pair, then the bellsman - each lose {T:.0f}+{T:.0f} min "
            f"transit. The bellsman works alone at {r.inputs.E}x a pair's rate, so effective time on "
            f"the job is just {fmt_h(s.on_job_eff)}h - the lowest of the three.",
            style={"color": AMBER, "fontSize": "0.82rem", "marginTop": "10px"})

    chips = [
        html.Span([html.Span(fmt_money(s.rate, cur), className="num"), "/day"], style=_chip()),
        html.Span(["dive window ", html.Span(f"{fmt_h(s.pair_win)}h", className="num")], style=_chip()),
    ]
    if s.bell_win > 0:
        chips.append(html.Span(["+ bellsman ", html.Span(f"{fmt_h(s.bell_win)}h", className="num")], style=_chip()))

    border = GREEN if s.win else "#e5e7eb"
    return html.Div([
        html.Span("Twin bell" if s.win else "Single bell", style={
            "fontSize": "0.7rem", "fontWeight": 700, "color": GREEN if s.win else MUTED,
            "textTransform": "uppercase", "letterSpacing": "0.05em"}),
        html.H4(s.name, style={"margin": "4px 0 2px"}),
        html.Div(" \u00b7 ".join(s.cfg), style={"fontSize": "0.8rem", "color": MUTED, "marginBottom": "8px"}),
        html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "gap": "6px", "marginBottom": "10px"}),
        timeline_bar(s, C, T),
        legend(),
        html.Div([
            html.Div([
                html.Div("On the job / day", style={"fontSize": "0.72rem", "color": MUTED}),
                html.Div(f"{fmt_h(s.on_job_eff)}h", style={"fontSize": "1.5rem", "fontWeight": 700, "color": GREEN}),
                html.Div("effective working hours", style={"fontSize": "0.7rem", "color": MUTED}),
            ]),
            html.Div([
                html.Div("Lost to overhead", style={"fontSize": "0.72rem", "color": MUTED}),
                html.Div(f"{fmt_h(s.overhead)}h", style={
                    "fontSize": "1.5rem", "fontWeight": 700,
                    "color": "#dc2626" if s.overhead > 0.05 else GREEN}),
                html.Div("nothing stops the job" if s.vessel == "twin"
                         else ("changeover + transit + half-manning" if s.bell_win > 0 else "changeover + transit"),
                         style={"fontSize": "0.7rem", "color": MUTED}),
            ]),
        ], style={"display": "flex", "gap": "24px", "marginTop": "12px"}),
        note,
    ], style={
        "flex": "1 1 300px", "padding": "16px", "borderRadius": "12px",
        "border": f"2px solid {border}", "background": "#fff",
        "boxShadow": "0 1px 3px rgba(0,0,0,0.04)"})


def bar_chart(rows, title):
    vmax = max((v for _, v, _, _ in rows), default=1) or 1
    bars = []
    for name, v, label, best in rows:
        bars.append(html.Div([
            html.Div(name, style={"flex": "0 0 150px", "fontSize": "0.82rem"}),
            html.Div(html.Div(label, style={
                "width": f"{v/vmax*100}%", "background": GREEN if best else "#cbd5e1",
                "color": "#06231a" if best else INK, "padding": "3px 8px", "borderRadius": "6px",
                "fontSize": "0.78rem", "fontWeight": 600, "whiteSpace": "nowrap", "fontFamily": "monospace",
                "minWidth": "fit-content", "textAlign": "right"}),
                style={"flex": "1 1 auto", "background": "#f3f4f6", "borderRadius": "6px"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "8px"}))
    return html.Div([html.H4(title, style={"margin": "0 0 12px"})] + bars)


def proj_column(p, r, cur):
    base = r.scenarios[0]
    cls_color = GREEN if p.win else (AMBER if p.base else TRANSIT)
    if p.base:
        delta = html.Div("Reference case", style={"fontSize": "0.78rem", "color": MUTED, "marginTop": "8px"})
    else:
        d_cost = base.cost - p.cost
        d_days = base.days - p.days
        cheaper = d_cost >= 0
        delta = html.Div(
            f"{'-' if cheaper else '+'}{fmt_money_m(abs(d_cost), cur)} "
            f"{'cheaper' if cheaper else 'dearer'} \u00b7 {'-' if d_days >= 0 else '+'}{fmt_h(abs(d_days))} days",
            style={"fontSize": "0.8rem", "fontWeight": 600, "marginTop": "8px",
                   "color": GREEN if cheaper else "#dc2626"})

    def line(l, rr, tot=False):
        return html.Div([
            html.Span(l, style={"color": MUTED, "fontSize": "0.8rem"}),
            html.Span(rr, className="num", style={"fontWeight": 700 if tot else 500,
                                                  "fontFamily": "monospace"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "padding": "4px 0", "borderTop": "1px solid #f1f5f9" if tot else "none"})

    return html.Div([
        html.H4([html.Span(style={"display": "inline-block", "width": "9px", "height": "9px",
                                  "borderRadius": "50%", "background": cls_color, "marginRight": "7px"}),
                 f"{p.cfg[0]} \u00b7 {p.divers} diver"], style={"margin": "0 0 2px", "fontSize": "0.95rem"}),
        html.Div(p.role, style={"fontSize": "0.78rem", "color": MUTED, "marginBottom": "8px"}),
        line("Day rate", fmt_money(p.rate, cur)),
        line("On the job / day", f"{fmt_h(p.on_job_eff)}h"),
        line("Days to complete", fmt_h(p.days)),
        line("Project cost", fmt_money_m(p.cost, cur), tot=True),
        delta,
    ], style={"flex": "1 1 220px", "padding": "14px", "borderRadius": "12px",
              "border": f"2px solid {GREEN if p.win else '#e5e7eb'}", "background": "#fff"})


def hero(value, label, sub, color=INK):
    return html.Div([
        html.Div(label, style={"fontSize": "0.72rem", "letterSpacing": "0.08em",
                               "textTransform": "uppercase", "color": MUTED}),
        html.Div(value, style={"fontSize": "2rem", "fontWeight": 700, "color": color, "lineHeight": 1.1}),
        html.Div(sub, style={"fontSize": "0.78rem", "color": MUTED, "marginTop": "2px"}),
    ], style={"flex": "1 1 200px", "padding": "16px", "borderRadius": "12px",
              "border": "1px solid #e5e7eb", "background": "#fff"})


def layout():
    return html.Div([
    reports.print_header(),
    html.Div([
        html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="bell-pdf-btn",
                    n_clicks=0, style=PDF_BTN_STYLE,
                    title="Opens your browser's print dialog \u2014 choose 'Save as PDF'"),
        html.Div(id="bell-print-sink", style={"display": "none"}),
    ], className="no-print",
       style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "2px"}),
    html.H3("Single vs Twin Bell - where the working hours go"),
    html.P("Twin-bell saturation diving keeps a crew continuously on the seabed via relief "
           "handover. This compares it against single-bell at 9 and 12 in saturation, on a "
           "fixed scope, for both productivity and total project cost. Adjust the assumptions "
           "on the left.",
           style={"color": MUTED, "maxWidth": "70ch", "lineHeight": 1.5}),
    html.Div([
        _controls(),
        html.Div(id="bell-output", style={"flex": "1 1 auto", "minWidth": 0}),
    ], className="diving-main",
       style={"display": "flex", "gap": "20px", "alignItems": "flex-start", "marginTop": "16px"}),
    reports.print_footer(),
])


@callback(
    Output("bell-output", "children"),
    Input("W", "value"), Input("C", "value"), Input("T", "value"),
    Input("B", "value"), Input("E", "value"),
    Input("R1", "value"), Input("R2", "value"), Input("R3", "value"),
    Input("dur", "value"), Input("CUR", "value"),
)
def update(W, C, T, B, E, R1, R2, R3, dur, CUR):
    def f(x, d):
        try:
            return float(x)
        except (TypeError, ValueError):
            return d
    # The rate fields already hold the selected currency (converted by the
    # currency toggle), so the engine runs on them directly and money is shown
    # with the matching symbol - no factor applied here.
    cur = "\u20ac" if (CUR or "USD").upper() == "EUR" else "$"
    inp = BellInputs(W=f(W, 6), C=f(C, 1), T=f(T, 15), B=f(B, 1), E=f(E, 0.5),
                     R1=f(R1, 150000), R2=f(R2, 160000), R3=f(R3, 190000),
                     dur=f(dur, 50), currency=cur)
    r = run_comparison(inp)
    base, mid, twin = r.scenarios

    heroes = html.Div([
        hero(f"{fmt_h(twin.on_job_eff)}h", "Twin - on the job / day",
             f"vs {fmt_h(base.on_job_eff)}h on the 9-man base", GREEN),
        hero(fmt_money(twin.cph, cur), "Twin - cost per on-job hour",
             f"{'-' if r.cph_save_pct >= 0 else '+'}{abs(round(r.cph_save_pct))}% vs base {fmt_money(base.cph, cur)}"),
        hero(f"{'' if r.faster_pct >= 0 else '+'}{round(abs(r.faster_pct))}%",
             "Twin - same scope finished", f"{fmt_h(r.days_faster)} days sooner", GREEN),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "20px"})

    cards = html.Div([scenario_card(s, r, cur) for s in r.scenarios],
                     style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "24px"})

    eff_rows = [(s.name, s.on_job_eff, f"{fmt_h(s.on_job_eff)}h", s.win) for s in r.scenarios]
    eff = bar_chart(eff_rows, "Operational efficiency - time on the job per day")

    proj = html.Div([
        html.H4(["Base case - Scenario 1 (single bell, 9 diver) runs for ",
                 html.Span(f"{fmt_h(inp.dur)}", className="num"), " days"],
                style={"margin": "24px 0 12px"}),
        html.Div([proj_column(p, r, cur) for p in r.scenarios],
                 style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
    ])

    cost_min = min(p.cost for p in r.scenarios)
    cost_rows = [(p.name, p.cost, fmt_money_m(p.cost, cur), p.cost == cost_min) for p in r.scenarios]
    cost = html.Div(bar_chart(cost_rows, "Project cost - single vs twin bell"),
                    style={"marginTop": "24px"})

    if r.twin_cheaper:
        lead = html.Span([
            "For the same scope, the twin bell finishes in ", html.B(f"{fmt_h(twin.days)} days"),
            " for ", html.B(fmt_money_m(twin.cost, cur), style={"color": GREEN}),
            " - that's ", html.B(fmt_money_m(r.twin_save, cur)),
            f" less than the {fmt_h(base.days)}-day, {fmt_money_m(base.cost, cur)} base case, "
            f"and {fmt_h(r.days_faster)} days sooner."])
        verdict_txt = "Twin bell - cheapest and fastest for the scope"
        verdict_color = GREEN
    else:
        lead = html.Span([
            "For the same scope, the twin bell finishes ", html.B(f"{fmt_h(r.days_faster)} days sooner"),
            f" ({fmt_h(twin.days)} vs {fmt_h(base.days)} days) but costs ",
            html.B(fmt_money_m(-r.twin_save, cur)),
            " more than the base case - the case rests on schedule value."])
        verdict_txt = "Twin bell - fastest; premium buys the schedule"
        verdict_color = AMBER

    callout = html.Div([
        html.Div(verdict_txt, style={"fontWeight": 700, "color": verdict_color, "marginBottom": "8px"}),
        html.Div(lead, style={"lineHeight": 1.5, "marginBottom": "8px"}),
        html.Div([
            f"Note the 12-man single bell sits in between: a higher day rate ({fmt_money(mid.rate, cur)}) "
            f"buys only a little more time on the job ({fmt_h(mid.on_job_eff)}h vs {fmt_h(base.on_job_eff)}h), "
            f"so its project comes out to {fmt_money_m(mid.cost, cur)} - "
            f"{'more' if mid.cost >= base.cost else 'less'} than the cheaper 9-man base. The twin bell wins "
            f"because it lifts time on the job to a full {fmt_h(twin.on_job_eff)}h, completing the work in "
            f"the fewest vessel days."],
            style={"color": MUTED, "fontSize": "0.85rem", "lineHeight": 1.5}),
    ], style={"marginTop": "24px", "padding": "16px", "borderRadius": "12px",
              "background": GREEN_SOFT if r.twin_cheaper else "#fef3c7",
              "border": f"1px solid {verdict_color}"})

    return [heroes, cards, eff, proj, cost, callout]


def _eff_fx(cur, fxval):
    """Effective multiply factor USD->displayed. 1.0 for USD; for EUR the FX
    field value, falling back to the admin rate if it's blank or non-positive."""
    if (cur or "USD").upper() != "EUR":
        return 1.0
    try:
        v = float(fxval)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return params.get_float("usd_eur_rate", 0.92) or 0.92


@callback(
    Output("bell-usd-basis", "data"),
    Input("R1", "value"), Input("R2", "value"), Input("R3", "value"),
    State("CUR", "value"), State("FX", "value"),
    prevent_initial_call=True,
)
def _basis_from_edits(r1, r2, r3, cur, fxval):
    """Whenever a rate field changes (user edit, or a currency/FX re-convert),
    record the canonical USD basis = displayed value / factor. This is the
    single source of truth the conversions read from, so toggles are exactly
    reversible and FX changes re-convert from the user's own rates."""
    fx = _eff_fx(cur, fxval)

    def usd(x):
        try:
            return float(x) / fx
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    return {"R1": usd(r1), "R2": usd(r2), "R3": usd(r3)}


@callback(
    Output("R1", "value"), Output("R2", "value"), Output("R3", "value"),
    Input("CUR", "value"), Input("FX", "value"),
    State("bell-usd-basis", "data"),
    prevent_initial_call=True,
)
def _apply_currency(cur, fxval, basis):
    """Re-display the rate fields whenever the currency or the exchange rate
    changes: displayed = USD basis * factor. A page reload re-seeds the basis
    (and fields) from the DB in USD, so reload returns to admin values."""
    basis = basis or {}
    fx = _eff_fx(cur, fxval)

    def disp(key):
        v = basis.get(key)
        try:
            return round(float(v) * fx)
        except (TypeError, ValueError):
            return no_update

    return disp("R1"), disp("R2"), disp("R3")


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } return window.dash_clientside.no_update; }",
    Output("bell-print-sink", "children"),
    Input("bell-pdf-btn", "n_clicks"),
    prevent_initial_call=True,
)
