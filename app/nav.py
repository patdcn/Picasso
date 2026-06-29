"""
Navigation: the grouped, collapsible sidebar.

HOW TO RENAME / REORDER GROUPS
------------------------------
Everything about the menu structure is controlled by NAV_GROUPS below.
- To rename a group: change the string (e.g. "Motions" -> "Vessel motions").
- To reorder groups: reorder the list.
- A page joins a group via the `category=...` kwarg in its register_page(...) call,
  which must match one of these names. Pages whose category isn't listed fall into
  an "Other" group at the bottom, so nothing ever disappears silently.

The sidebar itself is built from Dash's page registry, so adding a new tool is just
adding a page file — it shows up in its group automatically. No menu to hand-maintain.
"""
from dash import html, dcc
import dash

# Group display order. Rename or reorder freely — this is the single source of truth.
NAV_GROUPS = ["Lifting", "Diving", "Motions", "Structural", "Reference"]


def _grouped_pages():
    """Return {group_name: [page, ...]} for all registered pages except Home."""
    groups = {g: [] for g in NAV_GROUPS}
    for page in dash.page_registry.values():
        if page["path"] in ("/", "/admin", "/request-access"):   # rendered separately
            continue
        cat = page.get("category") or "Other"
        groups.setdefault(cat, []).append(page)
    # sort within each group by an optional `order` kwarg, then by name
    for g in groups:
        groups[g].sort(key=lambda p: (p.get("order", 99), p["name"]))
    return groups


def _link(page, active: bool):
    cls = "nav-link active" if active else "nav-link"
    return dcc.Link(page["name"], href=page["path"], className=cls)


def _visible(page, user):
    """A page is visible if the user is admin or has been granted its module."""
    if user and user.get("is_admin"):
        return True
    if not user:
        return False
    return page["path"] in (user.get("modules") or [])


def build_nav(pathname: str, user=None):
    """Build the sidebar contents for `user`, highlighting the active route."""
    items = [
        dcc.Link(
            [html.Span("⌂", className="nav-home-icon"), html.Span("Home")],
            href="/",
            className="nav-link nav-home" + (" active" if pathname in ("/", None) else ""),
        ),
    ]
    groups = _grouped_pages()
    for group in list(NAV_GROUPS) + [g for g in groups if g not in NAV_GROUPS]:
        pages = [p for p in groups.get(group, []) if _visible(p, user)]
        if not pages:
            continue  # don't show empty groups (or groups with nothing this user can see)
        items.append(html.Div(group, className="nav-group-label"))
        for page in pages:
            items.append(_link(page, active=(pathname == page["path"])))

    # Non-admins get a "Request access" link pinned at the bottom of the menu.
    if user and not user.get("is_admin"):
        items.append(html.Div(style={"height": "14px"}))
        items.append(html.Hr(style={"border": "none", "borderTop": f"1px solid #e5e7eb",
                                     "margin": "4px 8px 6px"}))
        active = (pathname == "/request-access")
        items.append(dcc.Link(
            [html.Span("\u2709", style={"marginRight": "8px"}), html.Span("Request access")],
            href="/request-access",
            className="nav-link active" if active else "nav-link"))
    return items
