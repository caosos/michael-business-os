"""Customer-facing DealSniffer settings for account-scoped search defaults."""

from __future__ import annotations

import html
from urllib.parse import quote

from . import account_delivery, accounts, market_prefs, market_search, source_onboarding
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def _home() -> dict:
    ui = market_prefs.load().get("ui")
    ui = ui if isinstance(ui, dict) else {}
    home = ui.get("home") if isinstance(ui.get("home"), dict) else {}
    raw_cats = home.get("categories") if isinstance(home.get("categories"), list) else market_search.DEFAULT_CATS
    return {
        "location": str(home.get("zip") or home.get("label") or "")[:60],
        "radius": float(home.get("radius") or market_search.DEFAULT_RADIUS),
        "categories": [c for c in raw_cats if c in market_search.CONTROL_CATS],
    }


def save_preferences(form: dict) -> str:
    location = " ".join(str(form.get("location") or "").split())[:60]
    try:
        radius = float(str(form.get("radius") or ""))
    except ValueError:
        raise InputError("radius must be a number") from None
    if not location:
        raise InputError("city or ZIP is required")
    if not 1 <= radius <= 500:
        raise InputError("radius must be between 1 and 500 miles")
    probe = market_search.parse_query({"base": [location], "radius": [str(radius)]})
    if probe["errors"]:
        raise InputError(probe["errors"][0])
    raw_cats = form.get("cat") if isinstance(form.get("cat"), list) else [form.get("cat")] if form.get("cat") else []
    cats = [c for c in dict.fromkeys(x for raw in raw_cats for x in str(raw).split(",")) if c in market_search.CONTROL_CATS]
    if not cats:
        raise InputError("choose at least one category")
    doc = market_prefs.load()
    ui = doc.get("ui") if isinstance(doc.get("ui"), dict) else {}
    doc["ui"] = {**ui, "home": {"state": "", "zip": location, "label": location,
                                  "radius": radius, "categories": cats}}
    market_prefs._store(doc)
    return "Deal preferences saved."


def render(csrf: str, google_status: dict) -> str:
    account = accounts.current()
    home = _home()
    cats = "".join(
        f"<label><input type='checkbox' name='cat' value='{e(c)}'{' checked' if c in home['categories'] else ''}> {e(market_search.CAT_LABELS[c])}</label>"
        for c in market_search.CONTROL_CATS
    )
    identity = (f"Signed in as {e(account.display_name or account.email or 'Google user')}" if account.authenticated
                else "Local owner mode on this EliteDesk")
    if account.authenticated:
        oauth = "CONNECTED — identity verified by Google"
        oauth_action = (f"<form method='post' action='/auth/logout'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                        "<button>Sign out</button></form>")
    elif google_status.get("configured"):
        oauth = "AVAILABLE — sign in to create or open your DealSniffer account"
        oauth_action = "<p><a class='button-link' href='/auth/google/start?next=/settings'>Continue with Google</a></p>"
    else:
        oauth = "NOT CONFIGURED — domain, HTTPS, Google client, and consent setup are still required"
        oauth_action = ""
    alerts = account_delivery.status(account.storage_key, "alerts")
    contact = account_delivery.status(account.storage_key, "contact")
    return f"""<style>
.settings{{max-width:880px;margin:auto}}.settings-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}.settings .checks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px}}.settings button{{background:var(--acc);max-width:260px}}@media(max-width:650px){{.settings-grid{{grid-template-columns:1fr}}}}
</style><div class='settings'><style>.source-setup-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}}.source-setup-grid .card{{margin:0}}.source-setup-grid h3{{margin-top:0}}</style><h1>Settings</h1>
<section class='card' id='deal-preferences'><h2>Deal preferences</h2><p class='mut'>These are your starting filters. You can still change filters for any one search.</p>
<form method='post' action='/settings/preferences'><input type='hidden' name='csrf' value='{e(csrf)}'><div class='settings-grid'>
<label>City or ZIP<input name='location' maxlength='60' value='{e(home['location'])}' placeholder='Conway, AR or 72032' required></label>
<label>Default radius (miles)<select name='radius'>{''.join(f"<option value='{n}'{' selected' if home['radius'] == n else ''}>{n}</option>" for n in (10, 25, 30, 50, 100, 250))}</select></label>
<fieldset style='grid-column:1/-1'><legend>What do you want to see?</legend><div class='checks'>{cats}</div></fieldset></div><button>Save my defaults</button></form></section>
<section class='card' id='account-status'><h2>Account</h2><p><b>{identity}</b></p><p>Google sign-in: <b>{oauth}</b></p>{oauth_action}<p class='small mut'>Google sign-in identifies the DealSniffer user only. It never signs in to Facebook, Gmail, or an auction source.</p></section>
<section class='card' id='delivery-status'><h2>Mailbox & notifications</h2>
<p>Vendor alerts: <b>{e(alerts['state'])}</b>{' · ' + e(alerts['address']) if alerts['address'] else ''}<br><span class='small mut'>{e(alerts['detail'])}</span></p>
<p>Buyer/seller contact: <b>{e(contact['state'])}</b>{' · ' + e(contact['address']) if contact['address'] else ''}<br><span class='small mut'>{e(contact['detail'])}</span></p>
<p>Email notifications: <b>NOT ACTIVE</b> until a destination is verified and a real delivery receipt succeeds.</p></section>{source_onboarding.render(account.storage_key)}</div>"""


def public_home(csrf: str, google_status: dict, next_path="/market") -> str:
    """Customer-visible landing page; every capability statement stays bounded."""

    account = accounts.current()
    if account.authenticated:
        action = (f"<a class='button-link' href='{e(accounts.safe_next_path(next_path))}'>Open my Marketplace</a>"
                  f"<form class='inline-form' method='post' action='/auth/logout'><input type='hidden' name='csrf' value='{e(csrf)}'>"
                  "<button>Sign out</button></form>")
        status = f"Signed in as {e(account.display_name or account.email or 'Google user')}."
    elif google_status.get("configured"):
        encoded_next = quote(accounts.safe_next_path(next_path), safe="")
        action = f"<a class='button-link' href='/auth/google/start?next={e(encoded_next)}'>Continue with Google</a>"
        status = "Sign in to keep your location, categories, saved listings, and bid watch separate from every other user."
    else:
        action = "<span class='button-disabled' aria-disabled='true'>Google sign-in is not configured yet</span>"
        status = "The public account service is not connected yet. The local-owner Marketplace remains available on the EliteDesk."
    return f"""<style>
.hero{{max-width:920px;margin:34px auto;padding:26px}}.hero h1{{font-size:clamp(30px,6vw,54px);line-height:1.05;margin:0 0 14px}}.hero .lead{{font-size:19px;max-width:720px}}.public-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;max-width:920px;margin:auto}}.button-link,.button-disabled{{display:inline-block;padding:10px 18px;border-radius:7px;background:var(--acc);color:white;text-decoration:none;font-weight:800}}.button-disabled{{background:var(--mut)}}.inline-form{{display:inline-block;margin-left:10px}}.inline-form button{{background:var(--mut);width:auto}}
</style><section class='hero'><p class='badge'>CONWAY-AREA DEAL DISCOVERY</p><h1>Find resale inventory in one place.</h1>
<p class='lead'>DealSniffer brings public auction and marketplace listings together, then helps you filter by location, category, price, closing time, and resale potential.</p>
<p>{action}</p><p class='small mut'>{status}</p></section><section class='public-grid'>
<article class='card'><h2>Browse your area</h2><p>Set a city or ZIP, radius, categories, and sources. Your settings belong to your DealSniffer account.</p></article>
<article class='card'><h2>Track bids</h2><p>Keep the source, current bid, your maximum, closing time, status, and next action together. DealSniffer does not place bids for you.</p></article>
<article class='card'><h2>Compare the numbers</h2><p>Review buy price, repair allowance, resale estimate, potential profit, distance, and uncertainty before deciding.</p></article></section>"""


def privacy() -> str:
    return """<section class='card legal'><h1>Privacy Policy</h1><p class='small mut'>Effective October 13, 2026</p>
<h2>Information DealSniffer uses</h2><p>If you sign in with Google, DealSniffer receives your Google account identifier, name, and verified email address. It also stores the DealSniffer preferences and records you choose to create, such as location, search filters, saved listings, bid-watch entries, and selling-intake submissions.</p>
<h2>What Google sign-in does not authorize</h2><p>Sign-in requests only <code>openid email profile</code>. DealSniffer does not request Gmail access, a Facebook password, an auction-site password, or permission to act inside those accounts.</p>
<h2>Listing data</h2><p>DealSniffer may display public listing information supplied by auction sources, marketplaces, and authorized data providers such as Bright Data. Original sources control their own listings and may change or remove them.</p>
<h2>Use and sharing</h2><p>Account information is used to provide and maintain DealSniffer. DealSniffer does not sell your personal information. Information may be processed by service providers needed to operate the website, authentication, hosting, data retrieval, or notifications.</p>
<h2>Retention and requests</h2><p>Information is retained while needed to provide the service and maintain required records. To request access, correction, or deletion, contact <a href='mailto:dealsniffer@gmail.com'>dealsniffer@gmail.com</a>.</p>
<h2>Security and changes</h2><p>DealSniffer uses account separation and signed sessions. This policy may be updated as connected services are added; the effective date above will change when it is updated.</p></section>"""


def terms() -> str:
    return """<section class='card legal'><h1>Terms of Service</h1><p class='small mut'>Effective October 13, 2026</p>
<h2>What DealSniffer provides</h2><p>DealSniffer is a research, organization, and decision-support service for listings offered by independent sellers, marketplaces, and auction providers. DealSniffer is not the seller, auctioneer, payment processor, or owner of those listings.</p>
<h2>Your decisions and source terms</h2><p>You are responsible for verifying price, condition, ownership, location, closing time, fees, and source rules before acting. Source links and displayed details may become stale. Your activity on another service remains subject to that service's terms.</p>
<h2>No automatic transactions</h2><p>DealSniffer does not bid, buy, pay, contact a seller, or publish a selling-intake submission without a separate authorized action. A saved listing, bid-watch entry, estimate, or suggestion is not a completed transaction or guarantee.</p>
<h2>Accounts</h2><p>You must use an account you are authorized to use and keep access to it secure. DealSniffer may suspend access needed to protect the service or other users.</p>
<h2>Estimates</h2><p>Repair costs, resale values, profit, turnover, distance, and rankings are estimates with uncertainty. They are not warranties.</p>
<h2>Contact</h2><p>Questions about these terms may be sent to <a href='mailto:dealsniffer@gmail.com'>dealsniffer@gmail.com</a>.</p></section>"""


def auth_problem(message: str, configured=True) -> str:
    action = "<p><a href='/auth/google/start'>Try Google sign-in again</a></p>" if configured else ""
    return f"<section class='card'><h1>Google sign-in unavailable</h1><p>{e(message)}</p>{action}<p><a href='/home'>Back to DealSniffer</a></p></section>"
