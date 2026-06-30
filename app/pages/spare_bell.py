"""
Diving — Single bell vs Single-Twin (spare bell) reliability & cost.

Native-Dash port of the single-vs-single-twin HTML calculator. Engine in
app/engines/spare_bell.py; this is the thin UI. Compares a true single bell
(which loses time to breakdown) against a single-twin with a spare bell on
standby, paired by crew size, for both productivity and total project cost.
"""
import dash
from dash import html, dcc, Input, Output, State, callback, clientside_callback

from app.engines.spare_bell import SpareBellInputs, run_comparison
from app import params, auth, reports

PDF_BTN_STYLE = {
    "padding": "8px 14px", "borderRadius": "8px", "border": "none",
    "background": "#0f766e", "color": "#fff", "fontWeight": 600,
    "cursor": "pointer", "fontSize": "0.85rem",
}

dash.register_page(__name__, path="/diving/spare-bell", name="Single vs single-twin",
                   category="Diving", order=2)

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
        locked = not auth.may_edit_params(auth.current_user(), "/diving/spare-bell")
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
    _num("sb-W", "Max out-of-bell time (h)", 6, 0.5, 1, hint="dive window per lockout", disabled=locked),
    _num("sb-C", "Bell changeover (h)", params.get_float("bell_changeover_h"), 0.25, 0, disabled=locked),
    _num("sb-T", "Bell to job transit (min, one way)", params.get_float("bell_transit_min"), 1, 0, disabled=locked),
    _num("sb-B", "Bellsman top-up - S1 only (h)", 1, 0.5, 0, disabled=locked),
    _num("sb-E", "Bellsman reduced work rate", 0.5, 0.05, 0, 1, hint="fraction of a full pair", disabled=locked),
    _num("sb-bd", "Breakdown downtime (h/week)", 10, 1, 0, hint="single bell only - lost to repairs", disabled=locked),
    html.Hr(style={"border": "none", "borderTop": "1px solid #eee", "margin": "12px 0"}),
    _num("sb-R1", "Day rate - single 9-man", params.get_float("day_rate_single_9man"), 1000, 0, disabled=locked),
    _num("sb-R2", "Day rate - single 12-man", params.get_float("day_rate_single_12man"), 1000, 0, disabled=locked),
    _num("sb-R4", "Day rate - single-twin 9-man", params.get_float("day_rate_single_twin_9man"), 1000, 0, disabled=locked),
    _num("sb-R5", "Day rate - single-twin 12-man", params.get_float("day_rate_single_twin_12man"), 1000, 0, disabled=locked),
    _num("sb-dur", "Base-case duration (days)", 50, 1, 1, hint="defines the fixed scope", disabled=locked),
    html.Div([
        html.Label("Display currency", style={"fontSize": "0.8rem", "fontWeight": 600}),
        dcc.RadioItems(id="sb-CUR", value="USD",
                       options=[{"label": " USD ($)", "value": "USD"},
                                {"label": " EUR (\u20ac)", "value": "EUR"}],
                       inputStyle={"marginRight": "4px"},
                       labelStyle={"display": "inline-block", "marginRight": "16px",
                                   "fontSize": "0.9rem", "cursor": "pointer"},
                       style={"marginTop": "4px"}),
        html.Div("Rates are set in USD; switching to EUR converts them at the "
                 "admin exchange rate.",
                 style={"fontSize": "0.68rem", "color": MUTED, "marginTop": "4px"}),
    ]),
], className="assump-panel", style={
    "flex": "0 0 280px", "padding": "16px", "background": "#fafafa",
    "border": "1px solid #e5e7eb", "borderRadius": "12px", "alignSelf": "flex-start",
    "position": "sticky", "top": "72px", "maxHeight": "calc(100vh - 96px)", "overflowY": "auto",
})


def timeline_bar(s, C, Tmin):
    scale = 24.0
    one_way = Tmin / 60.0
    segs = []
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


def _chip(extra=None):
    base = {"fontSize": "0.78rem", "padding": "3px 9px", "borderRadius": "999px",
            "background": "#f3f4f6", "color": INK}
    if extra:
        base.update(extra)
    return base


def scenario_card(s, r, cur):
    C, T, bd = r.inputs.C, r.inputs.T, r.inputs.bd
    if s.spare:
        ref = "Scenario 1" if s.crew == 9 else "Scenario 2"
        note = html.Div([
            f"Same diving day as {ref} - {fmt_h(s.on_job_eff)}h on the job - but on the twin vessel "
            "with the second bell on standby. A breakdown means a bell swap, not idle time. That "
            "reliability is what the cost comparison below puts a number on."],
            style={"color": GREEN, "fontSize": "0.82rem", "marginTop": "10px"})
    elif s.shortened:
        note = html.Div(
            f"Each dive is cut to {fmt_h(s.pair_win)}h so {s.runs} runs + changeovers fit the day. "
            f"After {T:.0f}+{T:.0f} min transit each run, {fmt_h(s.on_job_eff)}h is spent on the job "
            "- and the single bell sits idle whenever it breaks down.",
            style={"color": AMBER, "fontSize": "0.82rem", "marginTop": "10px"})
    else:
        note = html.Div(
            f"Two lockouts per run - the pair, then the bellsman - each lose {T:.0f}+{T:.0f} min "
            f"transit. The lone bellsman works at {r.inputs.E}x a pair's rate, giving "
            f"{fmt_h(s.on_job_eff)}h on the job. A breakdown stops the single bell until repaired.",
            style={"color": AMBER, "fontSize": "0.82rem", "marginTop": "10px"})

    chips = [
        html.Span([html.Span(fmt_money(s.rate, cur), className="num"), "/day"], style=_chip()),
        html.Span(["dive window ", html.Span(f"{fmt_h(s.pair_win)}h", className="num")], style=_chip()),
    ]
    if s.breaks:
        chips.append(html.Span(["breakdown ", html.Span(f"{fmt_h(bd)}h/wk", className="num")],
                               style=_chip({"color": AMBER, "background": "#fef3c7"})))
    else:
        chips.append(html.Span("spare bell - no idle time",
                               style=_chip({"color": GREEN, "background": GREEN_SOFT})))

    border = GREEN if s.spare else "#e5e7eb"
    return html.Div([
        html.Span("Single-twin - spare bell" if s.spare else "Single bell", style={
            "fontSize": "0.7rem", "fontWeight": 700, "color": GREEN if s.spare else MUTED,
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
                html.Div("Breakdown downtime", style={"fontSize": "0.72rem", "color": MUTED}),
                html.Div(f"{fmt_h(bd)}h" if s.breaks else "0h", style={
                    "fontSize": "1.5rem", "fontWeight": 700,
                    "color": "#dc2626" if s.breaks else GREEN}),
                html.Div("per week - idle" if s.breaks else "spare bell covers it",
                         style={"fontSize": "0.7rem", "color": MUTED}),
            ]),
        ], style={"display": "flex", "gap": "24px", "marginTop": "12px"}),
        note,
    ], style={
        "flex": "1 1 280px", "padding": "16px", "borderRadius": "12px",
        "border": f"2px solid {border}", "background": "#fff",
        "boxShadow": "0 1px 3px rgba(0,0,0,0.04)"})


def bar_chart(rows, title):
    vmax = max((v for _, v, _, _ in rows), default=1) or 1
    bars = []
    for name, v, label, best in rows:
        bars.append(html.Div([
            html.Div(name, style={"flex": "0 0 170px", "fontSize": "0.82rem"}),
            html.Div(html.Div(label, style={
                "width": f"{v/vmax*100}%", "background": GREEN if best else "#cbd5e1",
                "color": "#06231a" if best else INK, "padding": "3px 8px", "borderRadius": "6px",
                "fontSize": "0.78rem", "fontWeight": 600, "whiteSpace": "nowrap", "fontFamily": "monospace",
                "minWidth": "fit-content", "textAlign": "right"}),
                style={"flex": "1 1 auto", "background": "#f3f4f6", "borderRadius": "6px"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "8px"}))
    return html.Div([html.H4(title, style={"margin": "0 0 12px"})] + bars)


def proj_column(row, partner, cur, bd_week):
    is_stwin = row.stwin
    dot = GREEN if is_stwin else AMBER
    if is_stwin:
        d_cost = partner.cost - row.cost
        d_days = partner.days - row.days
        win = d_cost >= 0
        delta = html.Div(
            f"{'-' if win else '+'}{fmt_money_m(abs(d_cost), cur)} {'cheaper' if win else 'dearer'} "
            f"\u00b7 finishes {fmt_h(abs(d_days))} days {'sooner' if d_days >= 0 else 'later'}",
            style={"fontSize": "0.8rem", "fontWeight": 600, "marginTop": "8px",
                   "color": GREEN if win else "#dc2626"})
    else:
        delta = html.Div(f"+{fmt_h(row.idle)} days idle - breakdown downtime",
                         style={"fontSize": "0.8rem", "fontWeight": 600, "marginTop": "8px", "color": "#dc2626"})

    def line(l, rr, tot=False, color=None):
        return html.Div([
            html.Span(l, style={"color": MUTED, "fontSize": "0.8rem"}),
            html.Span(rr, className="num", style={"fontWeight": 700 if tot else 500,
                                                  "fontFamily": "monospace",
                                                  "color": color or INK}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "padding": "4px 0", "borderTop": "1px solid #f1f5f9" if tot else "none"})

    return html.Div([
        html.H4([html.Span(style={"display": "inline-block", "width": "9px", "height": "9px",
                                  "borderRadius": "50%", "background": dot, "marginRight": "7px"}),
                 row.name], style={"margin": "0 0 2px", "fontSize": "0.92rem"}),
        html.Div(row.role, style={"fontSize": "0.78rem", "color": MUTED, "marginBottom": "8px"}),
        line("Day rate", fmt_money(row.rate, cur)),
        line("On the job / day", f"{fmt_h(row.eff)}h"),
        line("Breakdown downtime",
             f"{fmt_h(bd_week)}h/wk" if row.breaks else "none - spare bell",
             color=AMBER if row.breaks else GREEN),
        line("Days to complete", fmt_h(row.days)),
        line("Project cost", fmt_money_m(row.cost, cur), tot=True),
        delta,
    ], style={"flex": "1 1 240px", "padding": "14px", "borderRadius": "12px",
              "border": f"2px solid {GREEN if is_stwin else '#e5e7eb'}", "background": "#fff"})


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
        html.Button([html.Span("\u2913\u2002"), "Export to PDF"], id="sb-pdf-btn",
                    n_clicks=0, style=PDF_BTN_STYLE,
                    title="Opens your browser's print dialog \u2014 choose 'Save as PDF'"),
        html.Div(id="sb-print-sink", style={"display": "none"}),
    ], className="no-print",
       style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "2px"}),
    html.H3("Single bell vs Single-Twin - the value of a spare bell"),
    html.P("A spare bell keeps the job moving when the working bell breaks down. This compares "
           "a true single bell (which sits idle during repairs) against a single-twin with a "
           "second bell on standby, paired by crew size, weighing the day-rate premium against "
           "avoided downtime. Adjust the assumptions on the left.",
           style={"color": MUTED, "maxWidth": "70ch", "lineHeight": 1.5}),
    html.Div([
        _controls(),
        html.Div(id="sb-output", style={"flex": "1 1 auto", "minWidth": 0}),
    ], className="diving-main",
       style={"display": "flex", "gap": "20px", "alignItems": "flex-start", "marginTop": "16px"}),
    reports.print_footer(),
])


@callback(
    Output("sb-output", "children"),
    Input("sb-W", "value"), Input("sb-C", "value"), Input("sb-T", "value"),
    Input("sb-B", "value"), Input("sb-E", "value"), Input("sb-bd", "value"),
    Input("sb-R1", "value"), Input("sb-R2", "value"),
    Input("sb-R4", "value"), Input("sb-R5", "value"),
    Input("sb-dur", "value"), Input("sb-CUR", "value"),
)
def update(W, C, T, B, E, bd, R1, R2, R4, R5, dur, CUR):
    def f(x, d):
        try:
            return float(x)
        except (TypeError, ValueError):
            return d
    # The rate fields already hold the selected currency (converted by the
    # currency toggle), so the engine runs on them directly.
    cur = "\u20ac" if (CUR or "USD").upper() == "EUR" else "$"
    inp = SpareBellInputs(W=f(W, 6), C=f(C, 1), T=f(T, 15), B=f(B, 1), E=f(E, 0.5),
                          bd=f(bd, 10), R1=f(R1, 150000), R2=f(R2, 160000),
                          R4=f(R4, 160000), R5=f(R5, 170000), dur=f(dur, 50), currency=cur)
    r = run_comparison(inp)

    # heroes (reliability)
    def hero_save(save, days):
        if save >= 0:
            return fmt_money_m(save, cur), f"and {fmt_h(days)} days sooner", GREEN
        return f"+{fmt_money_m(-save, cur)}", f"dearer \u00b7 {fmt_h(days)} days sooner", INK

    s9v, s9s, s9c = hero_save(r.save9, r.pairs[0].single.days - r.pairs[0].stwin.days)
    s12v, s12s, s12c = hero_save(r.save12, r.pairs[1].single.days - r.pairs[1].stwin.days)
    heroes = html.Div([
        hero(s9v, "Single-twin saves - 9 diver", s9s, s9c),
        hero(s12v, "Single-twin saves - 12 diver", s12s, s12c),
        hero(f"{fmt_h(r.idle_min)}-{fmt_h(r.idle_max)}d", "Idle days avoided",
             "single bell, lost to breakdown", AMBER),
    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "20px"})

    # scenario cards (4)
    cards = html.Div([scenario_card(s, r, cur) for s in r.scenarios],
                     style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "24px"})

    # efficiency bars
    eff_rows = [(s.name, s.on_job_eff, f"{fmt_h(s.on_job_eff)}h", s.spare) for s in r.scenarios]
    eff = bar_chart(eff_rows, "Operational efficiency - time on the job per day")

    # paired projection
    proj_pairs = []
    for pr in r.pairs:
        proj_pairs.append(html.Div([
            proj_column(pr.single, pr.stwin, cur, inp.bd),
            proj_column(pr.stwin, pr.single, cur, inp.bd),
        ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"}))
    proj = html.Div([
        html.H4(["Base case - Scenario 1 (single bell, 9 diver) runs for ",
                 html.Span(f"{fmt_h(inp.dur)}", className="num"), " days"],
                style={"margin": "24px 0 12px"}),
    ] + proj_pairs)

    # cost bars (all four)
    all_rows = [r.pairs[0].single, r.pairs[0].stwin, r.pairs[1].single, r.pairs[1].stwin]
    cost_max = max(p.cost for p in all_rows)
    cost_rows = [(p.name, p.cost, fmt_money_m(p.cost, cur), p.stwin) for p in all_rows]
    cost = html.Div(bar_chart(cost_rows, "Project cost - single vs single-twin bell"),
                    style={"marginTop": "24px"})

    # callout
    if r.both_win:
        d9 = r.pairs[0].single.days - r.pairs[0].stwin.days
        d12 = r.pairs[1].single.days - r.pairs[1].stwin.days
        lead = html.Span([
            "In ", html.B("both"), " crew sizes the single-twin comes out cheaper: ",
            html.B(fmt_money_m(r.save9, cur), style={"color": GREEN}), " for the 9-diver job and ",
            html.B(fmt_money_m(r.save12, cur), style={"color": GREEN}), " for the 12-diver job - and it "
            f"finishes each one {fmt_h(min(d9, d12))}-{fmt_h(max(d9, d12))} days sooner, because it "
            "never sits idle waiting on a repair."])
        verdict_txt = "Single-twin - cheaper and faster, both crew sizes"
        verdict_color = GREEN
    else:
        lead = html.Span([
            f"At {fmt_h(inp.bd)}h/week of breakdown the single-twin's spare bell saves time on both "
            "jobs, though the day-rate premium means it isn't yet cheaper outright. Raise the "
            "breakdown hours to see where the redundancy pays for itself."])
        verdict_txt = "Single-twin - faster; premium vs breakdown risk"
        verdict_color = AMBER

    callout = html.Div([
        html.Div(verdict_txt, style={"fontWeight": 700, "color": verdict_color, "marginBottom": "8px"}),
        html.Div(lead, style={"lineHeight": 1.5, "marginBottom": "8px"}),
        html.Div([
            f"The single-twin costs only a small premium per day ({fmt_money(inp.R4, cur)} vs "
            f"{fmt_money(inp.R1, cur)} for 9 diver; {fmt_money(inp.R5, cur)} vs {fmt_money(inp.R2, cur)} "
            f"for 12 diver), but a true single bell loses about {fmt_h(inp.bd)}h every week to breakdown "
            f"- roughly {fmt_h(r.pairs[1].single.idle)} idle days over this workload. The spare bell turns "
            "that lost time back into productive days, so the modest premium more than pays for itself."],
            style={"color": MUTED, "fontSize": "0.85rem", "lineHeight": 1.5}),
    ], style={"marginTop": "24px", "padding": "16px", "borderRadius": "12px",
              "background": GREEN_SOFT if r.both_win else "#fef3c7",
              "border": f"1px solid {verdict_color}"})

    return [heroes, cards, eff, proj, cost, callout]


@callback(
    Output("sb-R1", "value"), Output("sb-R2", "value"),
    Output("sb-R4", "value"), Output("sb-R5", "value"),
    Input("sb-CUR", "value"),
    State("sb-R1", "value"), State("sb-R2", "value"),
    State("sb-R4", "value"), State("sb-R5", "value"),
    prevent_initial_call=True,
)
def _convert_rates(cur, r1, r2, r4, r5):
    """Convert the day-rate fields when the currency toggles, using the values
    currently in the fields (the user's edits) as the basis - not the DB
    defaults. A fresh page load re-seeds the fields from the DB in USD."""
    rate = params.get_float("usd_eur_rate", 0.92) or 0.92
    factor = rate if (cur or "USD").upper() == "EUR" else (1.0 / rate)

    def conv(x):
        try:
            return round(float(x) * factor)
        except (TypeError, ValueError):
            return x

    return conv(r1), conv(r2), conv(r4), conv(r5)


clientside_callback(
    "function(n){ if(n){ setTimeout(function(){ window.print(); }, 60); } return window.dash_clientside.no_update; }",
    Output("sb-print-sink", "children"),
    Input("sb-pdf-btn", "n_clicks"),
    prevent_initial_call=True,
)
