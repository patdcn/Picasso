"""
Dive-planning day scheduler + Gantt builder (Air MG Diving).

Given a selected dive-table schedule (its bottom time, in-water runtime and any
chamber-deco time come from app.engines.profiles) plus the operational team /
shift / tidal inputs, lay out a working day of subsequent dives and render it as
a phase-coloured Gantt.

Model (v1)
----------
- Dives are driven by the working team, taken in order, `divers_in_water` at a
  time; a two-diver dive puts both divers in the water together.
- Standby is drawn from the shift team: a *dry* standby is held out of the
  rotation (working = per-shift - 1, odd pool -> last dive single-handed); a
  *wet* standby joins the rotation.
- A 12 h day is one shift; a 24 h day is two shifts (day then night) each with
  its own team and standby, so the divers onboard double.
- "Repeat dives per diver" caps how many times each diver may dive (0 = once).
- Tidal: dives are confined to slack windows; only whole dives are scheduled in
  a window (snapping a shorter second dive to a real table row is future work).
- DVIS5 is a per-dive bottom-time limit by depth and is enforced upstream (the
  bottom-time picker greys out over-limit rows); per-diver exposure here is
  informational, not a daily cap.

Bottom time is splash-to-leaving-bottom, so within it: descent (to worksite) +
arrive + work + return, with work = bottom time - descent - arrive - return.
Ascent + in-water stops and chamber time come from the table schedule.
"""
import math
import plotly.graph_objects as go

# phase palette (portal teal for the productive "work" block)
PHASES = ["descent", "arrive", "work", "return", "ascent", "undress", "chamber"]
PHASE_LABEL = {"descent": "Descent", "arrive": "Arrive", "work": "Work",
               "return": "Return", "ascent": "Ascent + stops",
               "undress": "Undress", "chamber": "Chamber deco"}
PHASE_COLOR = {"descent": "#5b8db8", "arrive": "#aec6d8", "work": "#0f766e",
               "return": "#aec6d8", "ascent": "#d98a2b", "undress": "#8a93a0",
               "chamber": "#2f9e6b"}
IN_WATER = ("descent", "arrive", "work", "return", "ascent")

DAY_BG = "#fcf4e6"
NIGHT_BG = "#e9ecf4"
TIDE_BG = "rgba(15,118,110,0.10)"
STANDBY_BG = "#e3e7eb"


def _fmt(m):
    h = int(m // 60) % 24
    return f"{h:02d}:{int(round(m % 60)):02d}"


def plan_day(cfg):
    """cfg keys: start_min, shift_hours (12/24), tidal_enabled, windows_per_day,
    window_min, divers_per_shift, divers_in_water (1/2), repeats, standby_type
    ('dry'/'wet'), bt, runtime, chamber, descent_min, arrive, ret, undress,
    turnaround. Returns a plan dict."""
    n_shifts = 2 if int(cfg["shift_hours"]) == 24 else 1
    shift_len = 720
    wet = cfg["standby_type"] == "wet"
    span_start = cfg["start_min"]
    span_end = span_start + int(cfg["shift_hours"]) * 60

    bt = float(cfg["bt"])
    runtime = float(cfg["runtime"])                 # in-water, splash -> surface
    chamber = float(cfg.get("chamber") or 0)
    descent = float(cfg["descent_min"])
    arrive, ret = float(cfg["arrive"]), float(cfg["ret"])
    undress, turn = float(cfg["undress"]), float(cfg["turnaround"])
    work = bt - descent - arrive - ret
    ascent = runtime - bt                           # ascent + in-water stops
    gap = undress + turn                            # surface -> next splash

    def segs(splash):
        out, t = [], splash
        for name, dur in (("descent", descent), ("arrive", arrive), ("work", work),
                          ("return", ret), ("ascent", ascent), ("undress", undress),
                          ("chamber", chamber)):
            if dur > 0:
                out.append((name, t, dur))
            # undress starts at surface; chamber follows undress
            t += dur
        return out

    exp, dives, shifts = {}, [], []
    total = cfg["divers_per_shift"] * n_shifts
    for i in range(1, total + 1):
        exp["D" + str(i)] = 0.0

    for s in range(n_shifts):
        s_start = span_start + s * shift_len
        s_end = s_start + shift_len
        base = s * cfg["divers_per_shift"]
        working = cfg["divers_per_shift"] if wet else cfg["divers_per_shift"] - 1
        standby_id = None if wet else "D" + str(base + cfg["divers_per_shift"])
        groups = []
        i = 0
        while i < working:
            g = ["D" + str(base + i + k + 1) for k in range(cfg["divers_in_water"]) if i + k < working]
            groups.append(g)
            i += cfg["divers_in_water"]
        dpr = len(groups)
        max_dives = dpr * (1 + int(cfg["repeats"]))

        # windows for this shift
        if cfg["tidal_enabled"]:
            n, half = int(cfg["windows_per_day"]), cfg["window_min"] / 2.0
            span = span_end - span_start
            gw = []
            for w in range(n):
                c = span_start + span * (w + 0.5) / n
                a, b = max(span_start, c - half), min(span_end, c + half)
                a, b = max(a, s_start), min(b, s_end)
                if b - a > 1:
                    gw.append((a, b))
            windows = gw
        else:
            windows = [(s_start, s_end)]

        gi = made = 0
        for (w0, w1) in windows:
            t = w0
            while made < max_dives and work > 0:
                if t + runtime > w1:        # only whole dives fit a window (v1)
                    break
                grp = groups[gi % dpr] if dpr else []
                if not grp:
                    break
                dives.append({"n": len(dives) + 1, "shift": s, "crew": grp,
                              "splash": t, "surface": t + runtime, "segs": segs(t)})
                for d in grp:
                    exp[d] += runtime
                gi += 1
                made += 1
                t += runtime + gap
            if made >= max_dives:
                break

        shifts.append({"index": s, "start": s_start, "end": s_end, "standby_id": standby_id,
                       "range": (base + 1, base + cfg["divers_per_shift"]),
                       "working": working, "dives_per_round": dpr, "max_dives": max_dives, "made": made})

    team = []
    for i in range(1, total + 1):
        is_sb = (not wet) and (i % cfg["divers_per_shift"] == 0)
        team.append({"id": "D" + str(i), "exp": exp["D" + str(i)], "standby": is_sb,
                     "shift": (i - 1) // cfg["divers_per_shift"]})

    return {
        "dives": dives, "shifts": shifts, "team": team, "n_shifts": n_shifts,
        "wet_standby": wet, "onboard": total, "span": (span_start, span_end),
        "derived": {"descent": descent, "arrive": arrive, "work": work, "return": ret,
                    "ascent": ascent, "undress": undress, "chamber": chamber,
                    "turnaround": turn, "runtime": runtime, "cycle": runtime + gap, "bt": bt},
        "totals": {"n_dives": len(dives), "work": len(dives) * max(0.0, work),
                   "chamber": len(dives) * chamber},
        "flags": {"neg_work": work <= 0,
                  "team_too_small": (cfg["divers_per_shift"] if wet else cfg["divers_per_shift"] - 1) < 1},
    }


def build_gantt_figure(plan, cfg):
    """Dive-centric Gantt: one row per dive (labelled with its diver(s)), phase-
    coloured segments; 24 h shows a day/night background split; a standby lane at
    the bottom; tidal slack windows shaded."""
    span0, span1 = plan["span"]
    dives = plan["dives"]
    rows = [f"Dive {d['n']} · {' & '.join(d['crew'])}" for d in dives] + ["Standby"]
    # y positions: dive 1 at top
    order = list(reversed(rows))

    fig = go.Figure()
    # phase traces (one per phase type so the legend shows each once)
    for ph in PHASES:
        xs, bases, ys, texts = [], [], [], []
        for d in dives:
            label = f"Dive {d['n']} · {' & '.join(d['crew'])}"
            for (name, start, dur) in d["segs"]:
                if name == ph and dur > 0:
                    xs.append(dur); bases.append(start); ys.append(label)
                    texts.append(f"Dive {d['n']} · {' & '.join(d['crew'])}<br>{PHASE_LABEL[ph]}: {dur:.1f} min")
        if xs:
            fig.add_bar(y=ys, x=xs, base=bases, orientation="h", name=PHASE_LABEL[ph],
                        marker=dict(color=PHASE_COLOR[ph], line=dict(width=0)),
                        width=0.62, hovertext=texts, hoverinfo="text", legendgroup=ph)

    # standby lane bar(s)
    sb_x, sb_base, sb_text = [], [], []
    for sh in plan["shifts"]:
        if sh["standby_id"]:
            sb_x.append(sh["end"] - sh["start"]); sb_base.append(sh["start"])
            sb_text.append(f"{sh['standby_id']} dry standby · no dive")
    if sb_x:
        fig.add_bar(y=["Standby"] * len(sb_x), x=sb_x, base=sb_base, orientation="h",
                    name="Standby (no dive)", marker=dict(color=STANDBY_BG, line=dict(width=0)),
                    width=0.5, hovertext=sb_text, hoverinfo="text", showlegend=False)

    shapes, annotations = [], []
    # day / night background (24 h only)
    if plan["n_shifts"] == 2:
        for sh in plan["shifts"]:
            shapes.append(dict(type="rect", xref="x", yref="paper", x0=sh["start"], x1=sh["end"],
                               y0=0, y1=1, fillcolor=DAY_BG if sh["index"] == 0 else NIGHT_BG,
                               line=dict(width=0), layer="below"))
            annotations.append(dict(xref="x", yref="paper", x=(sh["start"] + sh["end"]) / 2, y=1.04,
                                    showarrow=False, font=dict(size=11, color="#6b7280"),
                                    text=f"{'Day' if sh['index'] == 0 else 'Night'} shift · D{sh['range'][0]}–D{sh['range'][1]}"))

    # tidal windows
    if cfg.get("tidal_enabled"):
        # recompute windows purely for shading (mirror plan_day)
        n, half = int(cfg["windows_per_day"]), cfg["window_min"] / 2.0
        span = span1 - span0
        for w in range(n):
            c = span0 + span * (w + 0.5) / n
            a, b = max(span0, c - half), min(span1, c + half)
            shapes.append(dict(type="rect", xref="x", yref="paper", x0=a, x1=b, y0=0, y1=1,
                               fillcolor=TIDE_BG, line=dict(width=0), layer="below"))

    # hour ticks as clock labels
    step = 120 if (span1 - span0) > 800 else 60
    first = int(math.ceil(span0 / step) * step)
    tickvals = list(range(first, int(span1) + 1, step))
    ticktext = [_fmt(v) for v in tickvals]

    fig.update_layout(
        barmode="overlay", bargap=0.25,
        height=max(240, 42 * len(rows) + 90),
        margin=dict(l=8, r=12, t=34, b=8),
        plot_bgcolor="#eff0f2", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif", size=12, color="#1f2937"),
        legend=dict(orientation="h", yanchor="top", y=-0.06, x=0, font=dict(size=11)),
        shapes=shapes, annotations=annotations,
        xaxis=dict(range=[span0, span1], tickvals=tickvals, ticktext=ticktext,
                   showgrid=True, gridcolor="#d1d5db", zeroline=False, fixedrange=True),
        yaxis=dict(categoryorder="array", categoryarray=order, autorange=True,
                   showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(size=11)),
    )
    return fig
