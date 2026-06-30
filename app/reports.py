"""
Print letterhead for the diving comparison pages.

When a diving page is printed (the "Export to PDF" button opens the browser print
dialog), the on-screen chrome is hidden and these two blocks are shown instead: a
header with the DCN logo and company address, and a footer with the copyright
notice and disclaimer. On screen they are hidden via portal.css.
"""
import datetime
import dash
from dash import html

COMPANY_NAME = "DCN Diving B.V."
COMPANY_ADDR = "Van Konijnenburgweg 151 \u00b7 4612 PL Bergen op Zoom \u00b7 Netherlands"
DISCLAIMER = (
    "The figures in this document are calculated from the assumptions shown and are believed to be correct "
    "but are not guaranteed. They are indicative, provided for comparison purposes only, and do not "
    "constitute a binding offer, advice or warranty. DCN Diving B.V. accepts no liability for any decision "
    "or action taken on the basis of this information."
)


def print_header():
    """Letterhead shown at the top of the page when printed / saved as PDF."""
    return html.Div([
        html.Img(src=dash.get_asset_url("dcn_logo.png"), className="print-logo", alt="DCN Diving"),
        html.Div([
            html.Div(COMPANY_NAME, className="print-co-name"),
            html.Div(COMPANY_ADDR, className="print-co-addr"),
        ], className="print-co"),
    ], className="print-header")


def print_footer():
    """Copyright + disclaimer shown at the bottom of the page when printed."""
    year = datetime.date.today().year
    return html.Div([
        html.Div([html.Span("Disclaimer\u2002", className="print-disc-label"), DISCLAIMER],
                 className="print-disclaimer"),
        html.Div(f"\u00a9 {year} {COMPANY_NAME}\u2002\u00b7\u2002All rights reserved.",
                 className="print-copyright"),
    ], className="print-footer")
