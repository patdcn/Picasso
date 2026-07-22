"""
DCN Calculation Module - pricing engine.

Element-based calculation on the four IBIS / Business Central elements:
labor, subcontracting, materials, equipment - so a future BC export maps
one-to-one. Internal/external is a line-level ownership refinement WITHIN
labor and equipment, aggregated as splits alongside the element totals.

Rules
-----
- Line cost (USD) = qty x duration x unit rate x fx(currency -> USD).
  Unit rate = explicit override, else the embedded snapshot rate; for
  personnel the office/yard/offshore rate chosen by the line's rate_basis.
- A block has UNIT element subtotals (its own lines + structural package
  children + referenced blocks x their ref qty). Referencing a block
  multiplies ALL of its element subtotals - "3 days x sub calc" scales the
  whole sub calc by 3, per element, exactly as IBIS elementen behave.
- Structural aggregation ('package' children roll into their parent) never
  includes 'block'-kind children: building blocks contribute ONLY through
  refs, so parking them anywhere in the tree can never double-count.
- Levies apply to the two labor elements per line origin (local/expat pct
  from the markups snapshot).
- The sell waterfall applies, in order: overhead -> risk -> profit -> margin,
  each on the cumulative subtotal (cost + levies + previous markups). The
  order lives in WATERFALL below - one place to change if the commercial
  policy differs.

All figures come from the revision's EMBEDDED snapshot only - the engine
never reads the library, by design.
"""
from app.calcmod.db import ELEMENTS, LABOR_ELEMENTS, SPLIT_ELEMENTS

WATERFALL = ("overhead_pct", "risk_pct", "profit_pct", "margin_pct")


def line_cost_usd(line, snap):
    """(cost_usd, levy_usd) for one line."""
    item = snap["items"].get(line["snap_item_id"]) if line.get("snap_item_id") else None
    if line.get("unit_rate_override") is not None:
        rate, currency = float(line["unit_rate_override"]), "USD"
    elif item:
        if item["lib"] == "personnel":
            basis = line.get("rate_basis") or "offshore"
            rate = item.get(f"{basis}_rate") if basis in ("office", "yard", "offshore") \
                else item.get("offshore_rate")
        else:
            rate = item.get("rate")
        rate = float(rate or 0.0)
        currency = item.get("currency") or "USD"
    else:
        rate, currency = 0.0, "USD"
    fx = 1.0 if currency == "USD" else float(snap["fx"].get(currency) or 0.0)
    cost = float(line["qty"]) * float(line["duration"]) * rate * fx
    levy = 0.0
    if line["element"] in LABOR_ELEMENTS:
        mk = snap.get("markups") or {}
        pct = mk.get("levy_expat_pct" if line.get("origin") == "expat" else "levy_local_pct") or 0.0
        levy = cost * float(pct)
    return cost, levy


def _zero():
    return {e: 0.0 for e in ELEMENTS}


def compute(tree, snap):
    """Compute the whole revision.

    Returns {
      'blocks': {block_id: {'elements': {...}, 'levies': float, 'cost': float,
                            'sell': float, 'waterfall': [(label, amount)]}},
      'master_id': int or None
    }
    Cycle-safe: repo.add_ref refuses cycles, and the memoised walk guards
    again here so a corrupt file can never hang the portal.
    """
    blocks = {b["id"]: b for b in tree["blocks"]}
    lines_by_block = {}
    for ln in tree["lines"]:
        lines_by_block.setdefault(ln["block_id"], []).append(ln)
    refs_by_host = {}
    for r in tree["refs"]:
        refs_by_host.setdefault(r["host_block_id"], []).append(r)
    pkg_children = {}
    for b in tree["blocks"]:
        if b["parent_id"] and b["kind"] == "package":
            pkg_children.setdefault(b["parent_id"], []).append(b["id"])

    memo, visiting = {}, set()

    def _zsplit():
        return {e: {"internal": 0.0, "external": 0.0} for e in SPLIT_ELEMENTS}

    def unit(bid):
        if bid in memo:
            return memo[bid]
        if bid in visiting:                    # cycle guard (shouldn't happen)
            return _zero(), 0.0, _zsplit()
        visiting.add(bid)
        el, levies, sp = _zero(), 0.0, _zsplit()
        for ln in lines_by_block.get(bid, []):
            cost, levy = line_cost_usd(ln, snap)
            el[ln["element"]] += cost
            levies += levy
            if ln["element"] in SPLIT_ELEMENTS:
                own = ln.get("ownership") or "internal"
                sp[ln["element"]][own] += cost
        for kid in pkg_children.get(bid, []):
            kel, klev, ksp = unit(kid)
            for e in ELEMENTS:
                el[e] += kel[e]
            for e in SPLIT_ELEMENTS:
                for o in ("internal", "external"):
                    sp[e][o] += ksp[e][o]
            levies += klev
        for rf in refs_by_host.get(bid, []):
            rel, rlev, rsp = unit(rf["ref_block_id"])
            q = float(rf["qty"])
            for e in ELEMENTS:
                el[e] += rel[e] * q
            for e in SPLIT_ELEMENTS:
                for o in ("internal", "external"):
                    sp[e][o] += rsp[e][o] * q
            levies += rlev * q
        visiting.discard(bid)
        memo[bid] = (el, levies, sp)
        return memo[bid]

    mk = snap.get("markups") or {}
    out, master_id = {}, None
    for bid, b in blocks.items():
        el, levies, sp = unit(bid)
        cost = sum(el.values())
        running = cost + levies
        wf = [("Levies", levies)]
        for key in WATERFALL:
            amt = running * float(mk.get(key) or 0.0)
            wf.append((key.replace("_pct", "").capitalize(), amt))
            running += amt
        out[bid] = {"elements": el, "splits": sp, "levies": levies, "cost": cost,
                    "sell": running, "waterfall": wf}
        if b["kind"] == "master":
            master_id = bid
    return {"blocks": out, "master_id": master_id}


def element_report(tree, snap):
    """Element subtotals of the master rollup - the IBIS-style elementen view."""
    res = compute(tree, snap)
    if res["master_id"] is None:
        return _zero()
    return res["blocks"][res["master_id"]]["elements"]
