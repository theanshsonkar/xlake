"""Neutral structured facts from Unstop public search-result items.

Pure functions shared by the internships adapter and the hackathon normaliser.
Only public listing fields are read; no contact details are ever returned and
no long source text is copied (summaries are built from the facts).
"""
import re

_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
_ICON = {"fa-rupee": "INR", "fa-inr": "INR", "fa-dollar": "USD", "fa-usd": "USD",
         "fa-euro": "EUR", "fa-eur": "EUR", "fa-gbp": "GBP"}


def money(amount, code="INR") -> str:
    sym = _SYMBOL.get(code, code + " ")
    return "{}{:,.0f}".format(sym, amount)


def prizes_breakdown(prizes) -> list:
    """[{rank, amount, currency}] for cash tiers, in listed order."""
    out = []
    for p in prizes if isinstance(prizes, list) else []:
        if not isinstance(p, dict):
            continue
        cash = p.get("cash")
        if not isinstance(cash, (int, float)) or cash <= 0:
            continue
        code = str(p.get("currencyCode") or _ICON.get(str(p.get("currency") or "").lower(), "INR")).upper()
        out.append({"rank": str(p.get("rank") or "").strip() or None,
                    "amount": int(cash) if float(cash).is_integer() else cash,
                    "currency": code})
    return out


def festival_name(item) -> str:
    f = item.get("festival") if isinstance(item, dict) else None
    name = str(f.get("name") or "").strip() if isinstance(f, dict) else ""
    return name[:120]


def public_count(item, key):
    cfg = item.get("opportunity_config") if isinstance(item.get("opportunity_config"), dict) else {}
    shown = {"registerCount": "show_registrations_count", "viewsCount": "show_impressions"}[key]
    value = item.get(key)
    if cfg.get(shown) in (0, False) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _date(v):
    m = re.match(r"\d{4}-\d{2}-\d{2}", str(v or ""))
    return m.group(0) if m else ""


def summary(kind, title, organiser, *, mode="", location="", pay="", deadline="",
            audience="", team="", prize="", skills=None, openings=None) -> str:
    """One or two neutral sentences from facts, at most 300 characters."""
    first = "{} {}".format("Internship" if kind == "internship" else "Hackathon",
                           "at " + organiser if organiser and kind == "internship"
                           else ("hosted by " + organiser if organiser else "")).strip()
    bits = [b for b in (mode, location) if b]
    if bits:
        first += " (" + ", ".join(bits) + ")"
    if pay:
        first += "; " + pay
    if prize:
        first += "; prizes up to " + prize
    if team:
        first += "; team of " + team
    if openings:
        first += "; {} opening{}".format(openings, "" if openings == 1 else "s")
    second = []
    if audience:
        second.append("Open to " + audience)
    if skills:
        second.append("Skills: " + ", ".join(skills[:5]))
    if deadline:
        second.append("Apply by " + deadline)
    text = first + "." + (" " + ". ".join(second) + "." if second else "")
    return text[:300]
