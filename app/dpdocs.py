"""
Picasso DP reference-document library.

The source documents behind the DP portals (Thrustmaster capability studies,
FMEA material, trials, single-line) live on the PRIVATE data volume at
/data/docs/dp/ (override with env DP_DOCS_DIR) — never in the public GitHub
repository. They are served read-only through the /dp-doc/<name> Flask route
(registered in app.main) and listed on the Reference -> Picasso DP page.

KNOWN maps stable document keys to expected filenames so the DP portals can
hyperlink their citations: dpdocs.link(key, text) renders an <a target=_blank>
when the file is present on the volume and a plain span otherwise, so pages
degrade gracefully until a document is uploaded. Upload documents with exactly
the filenames below (Admin -> Data volume files, folder docs/dp), or add
extra PDFs freely — the reference page lists everything in the folder.
"""
import os

from dash import html

DOCS_DIR = os.getenv("DP_DOCS_DIR", "/data/docs/dp")

# key -> (expected filename on the volume, full title for the library page)
KNOWN = {
    "ag2020": (
        "CAA11127104ECA_DP_Capability_Analysis_2020.pdf",
        "Thrustmaster — DP Capability Analysis w/o retractable thruster "
        "(CAA11127104ECA, 2020)"),
    "wcfi2019": (
        "Capability_Plot_Rev16_2019_WCFI.pdf",
        "Thrustmaster — Capability Plots Rev 16 incl. Worst Case of Failure "
        "WCFI (Rev F, Aug 2019)"),
    "ag_plots_note": (
        "GM-PRJ100000-TN-001_Arabian_Gulf_plots.pdf",
        "Global Maritime — PICASSO Arabian Gulf capability plots technical "
        "note (GM-PRJ100000-TN-001)"),
    "fmea_addendum_prs": (
        "GM-PRJ121125-RP-001_DGPS3_RadaScan_FMEA_Addendum.pdf",
        "Global Maritime — DGPS 3 & RadaScan position reference systems DP "
        "FMEA addendum (GM-PRJ121125-RP-001, 2025)"),
    "fmea_main": (
        "GM-PRJ111331-R001_DP_FMEA.pdf",
        "Global Maritime — DSV Picasso DP FMEA (GM-PRJ111331-R001)"),
    "dpom": (
        "GM-PRJ117726-R001_DP_Operations_Manual.pdf",
        "DP Operations Manual (GM-PRJ117726-R001)"),
    "annual_trials": (
        "GM-PRJ123124-RP001_DP_Annual_Trials_2026.pdf",
        "Annual DP trials 2026 (GM-PRJ123124-RP001)"),
    "fmea_addendum_2026": (
        "GM-PRJ123124-RP002_DP_FMEA_Addendum.pdf",
        "DP FMEA addendum — Veripos LD8 / CyScan (GM-PRJ123124-RP002, 2026)"),
    "dpom_addendum_2026": (
        "GM-PRJ123124-RP003_DPOM_Addendum.pdf",
        "DP Operations Manual addendum (GM-PRJ123124-RP003, 2026)"),
    "load_balance": (
        "2245-880-201_El_Load_Balance_Main_AC.pdf",
        "Hareid Group — El. Load Balance Calc. Main AC Sys. 690V/450V/230V "
        "(2245-880-201 Rev 6, 2015)"),
    "single_line": (
        "2245-881-001_Main_Single_Line_AC.pdf",
        "Hareid Group — Main Single Line diagram AC Sys. 690V/450V/230V "
        "(2245-881-001)"),
}

# which study document backs each DP operating mode
MODE_DOC = {"2split": "ag2020", "3split": "wcfi2019"}


def path_for(key):
    fn = KNOWN.get(key, (None,))[0]
    return os.path.join(DOCS_DIR, fn) if fn else None


def exists(key):
    p = path_for(key)
    return bool(p) and os.path.exists(p)


def url_for(key):
    fn = KNOWN.get(key, (None,))[0]
    return f"/dp-doc/{fn}" if fn else None


def link(key, text, style=None):
    """<a> to the document (new tab) when present on the volume, else a plain
    span — the portals never break on a missing upload."""
    if exists(key):
        return html.A(text, href=url_for(key), target="_blank",
                      style={**(style or {}), "textDecoration": "underline"})
    return html.Span(text, style=style)


def mode_link(mode_key, text, style=None):
    return link(MODE_DOC.get(mode_key, ""), text, style=style)


# reference-number patterns used to recognise documents inside citation text
_PATTERNS = {
    "ag2020": r"CAA11127104ECA",
    "wcfi2019": r"\bWCFI\b",
    "ag_plots_note": r"GM-PRJ100000-TN-?001",
    "fmea_main": r"GM-PRJ111331-R-?001",
    "dpom": r"GM-PRJ117726-R-?001",
    "annual_trials": r"GM-PRJ123124-RP-?001\b",
    "fmea_addendum_2026": r"GM-PRJ123124-RP-?002\b",
    "dpom_addendum_2026": r"(GM-PRJ123124-)?RP-?003\b",
    "fmea_addendum_prs": r"GM-PRJ121125-RP-?001",
    "load_balance": r"2245-880-201",
    "single_line": r"2245-881-001",
}


def linkify(text):
    """Turn a citation line into components with hyperlinks to the documents
    it references. One referenced document that is present on the volume ->
    the WHOLE line becomes the link (click the title, opens in a new tab).
    Multiple referenced documents -> each reference token links to its own
    document. References whose file is missing stay plain text."""
    import re
    hits = []
    for key, pat in _PATTERNS.items():
        for m in re.finditer(pat, text):
            hits.append((m.start(), m.end(), key))
    hits.sort()
    # drop overlaps (first match wins) and de-duplicate keys per line
    clean, last_end, seen = [], -1, set()
    for s, e, k in hits:
        if s >= last_end and k not in seen:
            clean.append((s, e, k))
            last_end, seen = e, seen | {k}
    present = [(s, e, k) for (s, e, k) in clean if exists(k)]
    if not present:
        return [text]
    if len(present) == 1:
        return [html.A(text, href=url_for(present[0][2]), target="_blank",
                       style={"textDecoration": "underline"})]
    out, pos = [], 0
    for s, e, k in present:
        if s > pos:
            out.append(text[pos:s])
        out.append(html.A(text[s:e], href=url_for(k), target="_blank",
                          style={"textDecoration": "underline"}))
        pos = e
    if pos < len(text):
        out.append(text[pos:])
    return out


def list_docs():
    """All PDFs in the library folder: [{filename, title, known_key|None}],
    known documents first (KNOWN order), then any extra uploads sorted."""
    if not os.path.isdir(DOCS_DIR):
        return []
    present = {f for f in os.listdir(DOCS_DIR) if f.lower().endswith(".pdf")}
    out, used = [], set()
    for key, (fn, title) in KNOWN.items():
        if fn in present:
            out.append({"filename": fn, "title": title, "known_key": key})
            used.add(fn)
    for fn in sorted(present - used):
        out.append({"filename": fn,
                    "title": fn[:-4].replace("_", " "), "known_key": None})
    return out


def missing_known():
    """Expected documents not (yet) on the volume: [{key, filename, title}]."""
    return [{"key": k, "filename": fn, "title": title}
            for k, (fn, title) in KNOWN.items()
            if not os.path.exists(os.path.join(DOCS_DIR, fn))]
