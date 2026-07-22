"""
Administration hub (admins only; gated by the before_request guard).

A landing page of link-cards; each opens a dedicated page:
  - Users & access      -> /admin/users   (add users, grant tool access, requests)
  - Cost & timing        -> /admin/params  (shared assumptions for the bell tools)
  - Data volume files    -> /admin/files   (stage table data on the /data volume)
  - Activity log         -> /admin/activity
"""
import dash
from dash import html

from app import auth
from app.adminui import hub_card, is_admin, denied, MUTED

dash.register_page(__name__, path="/admin", name="Admin")  # no category -> not in nav groups


def layout():
    if not is_admin():
        return denied()
    n = auth.count_pending_requests()
    pending = f"  \u00b7  {n} pending request{'s' if n != 1 else ''}" if n else ""
    return html.Div([
        html.H3("Administration"),
        html.P("Manage users and tool access, set the shared cost & timing assumptions, and "
               "stage table data on the data volume. Each area opens on its own page.",
               style={"color": MUTED, "maxWidth": "640px"}),

        hub_card("Users & access" + pending,
                 "Add users, grant access to individual tools, toggle administrator, and review "
                 "pending tool-access requests.",
                 "/admin/users", "Open users & access"),

        hub_card("Cost & timing assumptions",
                 "Shared assumptions grouped by category: bell day rates & timing, dive planning, and dive & saturation gas constants.",
                 "/admin/params", "Open cost & timing assumptions"),

        hub_card("SAT systems",
                 ["Define saturation spreads used by the ", html.Code("SAT gas"),
                  " calculator \u2014 build the floodable volume from named components "
                  "(chambers, TUP, bell, HRL\u2026), set bell volume, single/twin "
                  "configuration and default depths."],
                 "/admin/sat-system", "Open SAT systems"),

        hub_card("Fuel consumption",
                 "DG specific fuel oil consumption curve (SFOC anchors, electrical "
                 "basis) and fuel density \u2014 drives the expected-consumption "
                 "estimate on the DP Environment Planner.",
                 "/admin/fuel", "Open fuel consumption"),

        hub_card("DP power consumers",
                 "Named non-thruster consumers (cranes, SAT spread, ROV, hotel load) "
                 "with planning kW and bus assignment \u2014 selectable on the DP "
                 "Capability & Ops Check page to prefill the per-bus auxiliary load.",
                 "/admin/dp-consumers", "Open DP power consumers"),

        hub_card("Data volume files",
                 ["Browse and manage the persistent ", html.Code("/data"),
                  " volume \u2014 upload (drag & drop), create folders, move, rename and delete. "
                  "Stage table data such as ", html.Code("tools/dcd/dcd_tables.json"),
                  " without going through the public repo."],
                 "/admin/files", "Open data volume explorer"),

        hub_card("Calculation module",
                 "Division grants (edit/read, library admin), the library check-in "
                 "queue, versioned rate sets with FX and markups, and calc.db / "
                 ".qcalc backups.",
                 "/admin/calc", "Open calculation module"),

        hub_card("Activity log",
                 "Sign-ins and tool usage across users \u2014 who accessed which tool and when.",
                 "/admin/activity", "Open activity log"),
    ], style={"maxWidth": "680px"})
