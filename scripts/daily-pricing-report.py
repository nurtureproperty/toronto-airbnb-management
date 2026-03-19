"""
Daily Pricing Intelligence Report

Sends a daily email to info@nurtre.io and angelica@nurtre.io with:
1. Occupancy alerts: flags properties below 50% occupancy within their avg lead time
2. Underpricing alerts: warns when too many bookings are far in advance
3. Event/holiday alerts: highlights upcoming events and holidays for price increases
4. Per-property pricing recommendations

Data sources:
  - Hospitable API (properties, calendar, reservations)
  - Canadian holidays + GTA events

Usage:
  python scripts/daily-pricing-report.py              # Send email
  python scripts/daily-pricing-report.py --dry-run    # Print to console only
  python scripts/daily-pricing-report.py --slack       # Also post summary to Slack

Schedule: Daily at 7:00 AM ET via Windows Task Scheduler
"""

import os
import sys
import time
import json
import smtplib
import argparse
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from collections import defaultdict
from statistics import median, mean
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))
LOG_FILE = os.path.join(SCRIPT_DIR, "daily-pricing-report-log.txt")

# API config
TOKEN = os.getenv("HOSPITABLE_API_TOKEN")
BASE = "https://public.api.hospitable.com/v2"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# Email config
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("EMAIL_SMTP_USER")
SMTP_PASS = os.getenv("EMAIL_SMTP_PASSWORD")
EMAIL_TO = ["info@nurtre.io", "angelica@nurtre.io"]

# Slack config
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN") or os.getenv("NURTURE_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_HOSPITABLE_CHANNEL_ID", "")

# Thresholds
OCCUPANCY_THRESHOLD = 0.50  # Alert if below 50%
ADVANCE_BOOKING_THRESHOLD = 0.60  # If 60%+ of lead time window is already booked, may be underpriced
MIN_LEAD_TIME_DAYS = 14  # Fallback if no historical data


# ============================================
# GTA EVENTS & CANADIAN HOLIDAYS
# ============================================
def get_upcoming_events(start_date, days_ahead=60):
    """Return events/holidays within the next N days."""
    end_date = start_date + timedelta(days=days_ahead)
    year = start_date.year

    # Canadian statutory holidays (Ontario)
    holidays = [
        (f"{year}-01-01", "New Year's Day", "high"),
        (f"{year}-02-16", "Family Day (Ontario)", "medium"),
        (f"{year}-03-17", "St. Patrick's Day", "low"),
        (f"{year}-04-18", "Good Friday", "high"),
        (f"{year}-04-20", "Easter Sunday", "high"),
        (f"{year}-05-18", "Victoria Day", "high"),
        (f"{year}-06-21", "National Indigenous Peoples Day", "low"),
        (f"{year}-07-01", "Canada Day", "high"),
        (f"{year}-08-03", "Civic Holiday (Simcoe Day)", "high"),
        (f"{year}-09-07", "Labour Day", "high"),
        (f"{year}-09-30", "National Day for Truth and Reconciliation", "low"),
        (f"{year}-10-12", "Thanksgiving", "high"),
        (f"{year}-10-31", "Halloween", "medium"),
        (f"{year}-11-11", "Remembrance Day", "low"),
        (f"{year}-12-25", "Christmas Day", "high"),
        (f"{year}-12-26", "Boxing Day", "high"),
        (f"{year}-12-31", "New Year's Eve", "high"),
    ]

    # GTA specific events (approximate dates, update yearly)
    gta_events = [
        (f"{year}-02-14", "Valentine's Day Weekend", "medium"),
        (f"{year}-03-14", "March Break Start (Ontario)", "high"),
        (f"{year}-03-21", "March Break End", "high"),
        (f"{year}-04-01", "Toronto Maple Leafs Playoffs (if applicable)", "medium"),
        (f"{year}-05-01", "Toronto housing turnover peak", "medium"),
        (f"{year}-05-24", "Victoria Day Long Weekend", "high"),
        (f"{year}-06-01", "Summer season start", "high"),
        (f"{year}-06-15", "Toronto Jazz Festival (approx)", "medium"),
        (f"{year}-06-20", "FIFA World Cup 2026 (Toronto matches)", "high"),
        (f"{year}-07-01", "Canada Day Long Weekend", "high"),
        (f"{year}-07-10", "Toronto Caribbean Carnival prep", "medium"),
        (f"{year}-07-31", "Toronto Caribbean Carnival (Caribana)", "high"),
        (f"{year}-08-01", "Caribana Weekend", "high"),
        (f"{year}-08-20", "CNE (Canadian National Exhibition) starts", "high"),
        (f"{year}-09-04", "CNE ends / Labour Day", "high"),
        (f"{year}-09-10", "TIFF (Toronto International Film Festival)", "high"),
        (f"{year}-10-31", "Halloween weekend demand", "medium"),
        (f"{year}-11-28", "Black Friday / US Thanksgiving visitors", "medium"),
        (f"{year}-12-20", "Holiday season peak starts", "high"),
    ]

    upcoming = []
    for date_str, name, impact in holidays + gta_events:
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if start_date.date() <= event_date <= end_date.date():
                days_until = (event_date - start_date.date()).days
                upcoming.append({
                    "date": date_str,
                    "name": name,
                    "impact": impact,
                    "days_until": days_until,
                })
        except ValueError:
            continue

    upcoming.sort(key=lambda x: x["days_until"])
    return upcoming


# ============================================
# HOSPITABLE API HELPERS
# ============================================
def api_get(path, params=None):
    resp = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=30)
    if resp.status_code == 429:
        print("  Rate limited, waiting 5s...")
        time.sleep(5)
        resp = requests.get(f"{BASE}{path}", headers=HEADERS, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"  API error {resp.status_code}: {resp.text[:200]}")
        return {}
    return resp.json()


def api_get_all_pages(path, params=None):
    if params is None:
        params = {}
    all_data = []
    page = 1
    while True:
        params["page"] = page
        params["per_page"] = 100
        data = api_get(path, params)
        items = data.get("data", [])
        all_data.extend(items)
        meta = data.get("meta", {})
        if page >= meta.get("last_page", 1):
            break
        page += 1
        time.sleep(0.3)
    return all_data


def get_properties():
    """Fetch all listed properties."""
    data = api_get("/properties", {"per_page": 50, "include": "listings"})
    properties = []
    for p in data.get("data", []):
        if not p.get("listed"):
            continue
        airbnb_listings = [l for l in p.get("listings", []) if l.get("platform") == "airbnb"]
        display_name = airbnb_listings[0].get("platform_name", p.get("name", "Unknown")) if airbnb_listings else p.get("name", "Unknown")
        properties.append({
            "id": p["id"],
            "name": display_name,
            "short_name": p.get("name", display_name),
            "city": p.get("address", {}).get("city", "Unknown"),
            "bedrooms": p.get("capacity", {}).get("bedrooms", 0),
            "timezone": p.get("timezone", "America/Toronto"),
        })
    return properties


def get_calendar(property_id, start_date, end_date):
    """Fetch calendar data for a property within a date range."""
    data = api_get(f"/properties/{property_id}/calendar", {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
    })
    return data.get("data", {}).get("days", [])


def get_reservations(property_ids, start_date, end_date):
    """Fetch reservations for properties within a date range."""
    all_reservations = []
    # API requires properties[] array params
    params_list = []
    for pid in property_ids:
        params_list.append(("properties[]", pid))
    params_list.append(("start_date", start_date.strftime("%Y-%m-%d")))
    params_list.append(("end_date", end_date.strftime("%Y-%m-%d")))
    params_list.append(("per_page", "100"))

    page = 1
    while True:
        page_params = params_list + [("page", str(page))]
        resp = requests.get(f"{BASE}/reservations", headers=HEADERS, params=page_params, timeout=30)
        if resp.status_code == 429:
            time.sleep(5)
            resp = requests.get(f"{BASE}/reservations", headers=HEADERS, params=page_params, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        items = data.get("data", [])
        all_reservations.extend(items)
        meta = data.get("meta", {})
        if page >= meta.get("last_page", 1):
            break
        page += 1
        time.sleep(0.3)

    return all_reservations


def get_reservations_per_property(property_ids, start_date, end_date):
    """Fetch reservations per property so we know which property each belongs to.
    The Hospitable API returns property=None, so we query per property."""
    all_reservations = []
    for pid in property_ids:
        page = 1
        while True:
            resp = requests.get(f"{BASE}/reservations", headers=HEADERS, params={
                "properties[]": pid,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "per_page": 100,
                "page": page,
            }, timeout=30)
            if resp.status_code == 429:
                time.sleep(5)
                continue
            if resp.status_code != 200:
                break
            data = resp.json()
            for r in data.get("data", []):
                r["_property_id"] = pid  # Tag with property ID since API returns None
                all_reservations.append(r)
            meta = data.get("meta", {})
            if page >= meta.get("last_page", 1):
                break
            page += 1
            time.sleep(0.3)
        time.sleep(0.2)
    return all_reservations


# ============================================
# ANALYSIS FUNCTIONS
# ============================================
def calculate_lead_times(reservations):
    """Calculate average lead time per property from historical bookings."""
    lead_times_by_prop = defaultdict(list)

    for res in reservations:
        if res.get("stay_type") == "owner_stay":
            continue

        booking_date = res.get("booking_date")
        arrival_date = res.get("arrival_date") or res.get("check_in")

        if not booking_date or not arrival_date:
            continue

        try:
            booked = datetime.fromisoformat(booking_date.replace("Z", "+00:00")).replace(tzinfo=None)
            arrival = datetime.fromisoformat(arrival_date.replace("Z", "+00:00")).replace(tzinfo=None)
            lt = (arrival - booked).days
            if 0 <= lt <= 365:
                prop_id = res.get("_property_id") or res.get("property", "")
                lead_times_by_prop[prop_id].append(lt)
        except Exception:
            continue

    result = {}
    for prop_id, times in lead_times_by_prop.items():
        if times:
            result[prop_id] = {
                "avg": round(mean(times)),
                "median": round(median(times)),
                "count": len(times),
            }
    return result


def analyze_occupancy(calendar_days, lead_time_days):
    """Check occupancy within the lead time window."""
    today = datetime.now().date()
    window_end = today + timedelta(days=lead_time_days)

    window_days = []
    for day in calendar_days:
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            if today <= day_date <= window_end:
                window_days.append(day)
        except (ValueError, KeyError):
            continue

    if not window_days:
        return None

    total = len(window_days)
    booked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "RESERVED")
    blocked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "BLOCKED")
    available = total - booked - blocked

    occupancy_rate = booked / (total - blocked) if (total - blocked) > 0 else 0

    return {
        "total_days": total,
        "booked": booked,
        "available": available,
        "blocked": blocked,
        "occupancy_rate": occupancy_rate,
        "lead_time_window": lead_time_days,
    }


def analyze_advance_bookings(reservations, property_id, avg_lead_time):
    """Check if too many bookings are far in advance (underpricing signal)."""
    today = datetime.now()
    future_bookings = []

    for res in reservations:
        if (res.get("_property_id") or res.get("property")) != property_id:
            continue
        if res.get("stay_type") == "owner_stay":
            continue

        arrival = res.get("arrival_date") or res.get("check_in")
        if not arrival:
            continue

        try:
            arrival_date = datetime.fromisoformat(arrival.replace("Z", "+00:00")).replace(tzinfo=None)
            if arrival_date > today:
                days_out = (arrival_date - today).days
                future_bookings.append(days_out)
        except Exception:
            continue

    if not future_bookings:
        return None

    # Check what % of bookings are beyond 1.5x the avg lead time (unusually far out)
    far_advance = [d for d in future_bookings if d > avg_lead_time * 1.5]
    far_advance_pct = len(far_advance) / len(future_bookings) if future_bookings else 0

    # Check if occupancy within lead time is very high
    within_lead = [d for d in future_bookings if d <= avg_lead_time]
    within_lead_pct = len(within_lead) / max(avg_lead_time, 1)

    return {
        "total_future": len(future_bookings),
        "far_advance_count": len(far_advance),
        "far_advance_pct": far_advance_pct,
        "within_lead_count": len(within_lead),
        "within_lead_fill_rate": within_lead_pct,
        "farthest_booking_days": max(future_bookings) if future_bookings else 0,
    }


def get_pricing_snapshot(calendar_days, lead_time_days):
    """Get current pricing within the lead time window."""
    today = datetime.now().date()
    window_end = today + timedelta(days=lead_time_days)

    prices = []
    available_prices = []
    for day in calendar_days:
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            if today <= day_date <= window_end and "price" in day:
                price = day["price"]["amount"] / 100
                prices.append(price)
                if day.get("status", {}).get("reason") == "AVAILABLE":
                    available_prices.append({"date": day["date"], "price": price, "day": day.get("day", "")})
        except (ValueError, KeyError):
            continue

    if not prices:
        return None

    return {
        "avg_price": round(mean(prices), 2),
        "min_price": min(prices),
        "max_price": max(prices),
        "available_nights": available_prices,
    }


# ============================================
# REPORT GENERATION
# ============================================
def generate_report():
    """Generate the full pricing intelligence report."""
    now = datetime.now()
    report_date = now.strftime("%A, %B %d, %Y")

    print(f"Generating pricing report for {report_date}...")

    # 1. Fetch properties
    properties = get_properties()
    print(f"  Found {len(properties)} listed properties")

    if not properties:
        return None, None

    property_ids = [p["id"] for p in properties]

    # 2. Fetch historical reservations per property for lead time calculation (last 6 months)
    print("  Fetching historical reservations per property...")
    historical_res = get_reservations_per_property(property_ids, now - timedelta(days=180), now)
    print(f"  Found {len(historical_res)} historical reservations")

    # 3. Calculate lead times per property
    lead_times = calculate_lead_times(historical_res)

    # 4. Fetch future reservations (next 90 days)
    print("  Fetching future reservations...")
    future_res = get_reservations_per_property(property_ids, now, now + timedelta(days=90))
    print(f"  Found {len(future_res)} future reservations")

    # 5. Fetch calendar for each property (next 90 days)
    print("  Fetching calendars...")
    calendars = {}
    for p in properties:
        cal = get_calendar(p["id"], now, now + timedelta(days=90))
        calendars[p["id"]] = cal
        time.sleep(0.2)

    # 6. Get upcoming events
    events = get_upcoming_events(now, days_ahead=60)

    # 7. Build report sections
    alerts = []          # High priority
    warnings = []        # Medium priority
    insights = []        # Nice to know
    property_details = []

    for p in properties:
        pid = p["id"]
        name = p["short_name"]
        city = p["city"]
        beds = p["bedrooms"]
        lt_data = lead_times.get(pid, {})
        avg_lt = lt_data.get("avg", MIN_LEAD_TIME_DAYS)
        med_lt = lt_data.get("median", MIN_LEAD_TIME_DAYS)
        lt_count = lt_data.get("count", 0)

        cal = calendars.get(pid, [])

        # Occupancy analysis
        occ = analyze_occupancy(cal, avg_lt)

        # Advance booking analysis
        adv = analyze_advance_bookings(future_res, pid, avg_lt)

        # Pricing snapshot
        pricing = get_pricing_snapshot(cal, avg_lt)

        detail = {
            "name": name,
            "city": city,
            "bedrooms": beds,
            "avg_lead_time": avg_lt,
            "median_lead_time": med_lt,
            "booking_count": lt_count,
        }

        if occ:
            detail["occupancy"] = occ
            if occ["occupancy_rate"] < OCCUPANCY_THRESHOLD:
                pct = round(occ["occupancy_rate"] * 100)
                alerts.append(
                    f"🔴 {name} ({city}): Only {pct}% occupied in the next {avg_lt} days "
                    f"({occ['booked']} of {occ['total_days'] - occ['blocked']} available nights booked). "
                    f"Consider dropping prices on the {occ['available']} open nights."
                )

        if adv:
            detail["advance_bookings"] = adv
            if adv["far_advance_pct"] > 0.40 and adv["total_future"] >= 3:
                warnings.append(
                    f"⚠️ {name} ({city}): {adv['far_advance_count']} of {adv['total_future']} upcoming bookings "
                    f"are beyond {round(avg_lt * 1.5)} days out (1.5x your avg lead time of {avg_lt}d). "
                    f"Farthest booking is {adv['farthest_booking_days']} days out. This property may be underpriced."
                )
            if adv.get("within_lead_fill_rate", 0) > ADVANCE_BOOKING_THRESHOLD:
                warnings.append(
                    f"⚠️ {name} ({city}): {round(adv['within_lead_fill_rate'] * 100)}% fill rate within "
                    f"lead time window ({avg_lt} days). Demand is strong. Consider raising base rate."
                )

        if pricing:
            detail["pricing"] = pricing

        property_details.append(detail)

    # Event alerts
    event_alerts = []
    high_impact = [e for e in events if e["impact"] == "high" and e["days_until"] <= 45]
    medium_impact = [e for e in events if e["impact"] == "medium" and e["days_until"] <= 30]

    for e in high_impact:
        event_alerts.append(
            f"📅 {e['name']} ({e['date']}): {e['days_until']} days away. "
            f"HIGH impact on demand. Raise prices if not already adjusted."
        )
    for e in medium_impact:
        event_alerts.append(
            f"📅 {e['name']} ({e['date']}): {e['days_until']} days away. "
            f"MEDIUM impact. Consider a 10-15% bump."
        )

    # Build text report
    text_report = build_text_report(report_date, alerts, warnings, event_alerts, insights, property_details, events)
    html_report = build_html_report(report_date, alerts, warnings, event_alerts, insights, property_details, events)

    return text_report, html_report


def build_text_report(date, alerts, warnings, event_alerts, insights, details, events):
    lines = []
    lines.append(f"DAILY PRICING INTELLIGENCE REPORT")
    lines.append(f"{date}")
    lines.append("=" * 60)

    if alerts:
        lines.append("\n🔴 ACTION REQUIRED")
        lines.append("-" * 40)
        for a in alerts:
            lines.append(f"  {a}")

    if warnings:
        lines.append("\n⚠️ UNDERPRICING WARNINGS")
        lines.append("-" * 40)
        for w in warnings:
            lines.append(f"  {w}")

    if event_alerts:
        lines.append("\n📅 UPCOMING EVENTS (price increase opportunities)")
        lines.append("-" * 40)
        for e in event_alerts:
            lines.append(f"  {e}")

    lines.append("\n📊 PROPERTY DETAILS")
    lines.append("-" * 40)
    for d in details:
        lines.append(f"\n  {d['name']} ({d['city']}, {d['bedrooms']}BR)")
        lines.append(f"    Avg lead time: {d['avg_lead_time']}d (median {d['median_lead_time']}d, based on {d['booking_count']} bookings)")

        if "occupancy" in d:
            occ = d["occupancy"]
            pct = round(occ["occupancy_rate"] * 100)
            lines.append(f"    Occupancy (next {occ['lead_time_window']}d): {pct}% ({occ['booked']} booked, {occ['available']} open, {occ['blocked']} blocked)")

        if "advance_bookings" in d:
            adv = d["advance_bookings"]
            lines.append(f"    Future bookings: {adv['total_future']} total, {adv['far_advance_count']} far in advance, farthest {adv['farthest_booking_days']}d out")

        if "pricing" in d:
            pr = d["pricing"]
            lines.append(f"    Current rates: avg ${pr['avg_price']:.0f}, low ${pr['min_price']:.0f}, high ${pr['max_price']:.0f}")
            if pr["available_nights"]:
                lines.append(f"    Open nights with prices:")
                for n in pr["available_nights"][:7]:
                    lines.append(f"      {n['date']} ({n['day'][:3]}): ${n['price']:.0f}")
                if len(pr["available_nights"]) > 7:
                    lines.append(f"      ... and {len(pr['available_nights']) - 7} more")

    if not alerts and not warnings:
        lines.append("\n✅ All properties look healthy. No immediate pricing action needed.")

    lines.append(f"\n{'=' * 60}")
    lines.append("Generated by Nurture Pricing Bot")
    lines.append(f"Data as of {datetime.now().strftime('%Y-%m-%d %H:%M')} ET")

    return "\n".join(lines)


def build_html_report(date, alerts, warnings, event_alerts, insights, details, events):
    """Build a styled HTML email."""

    def section(title, items, color):
        if not items:
            return ""
        html = f'<div style="margin-bottom:20px;"><h3 style="color:{color};margin-bottom:8px;">{title}</h3>'
        for item in items:
            html += f'<p style="margin:4px 0;padding:8px 12px;background:#f8f8f8;border-left:3px solid {color};font-size:14px;">{item}</p>'
        html += '</div>'
        return html

    property_rows = ""
    for d in details:
        occ_pct = round(d["occupancy"]["occupancy_rate"] * 100) if "occupancy" in d else "N/A"
        occ_color = "#c0392b" if isinstance(occ_pct, int) and occ_pct < 50 else "#27ae60" if isinstance(occ_pct, int) else "#666"
        avg_rate = f"${d['pricing']['avg_price']:.0f}" if "pricing" in d else "N/A"
        future = d["advance_bookings"]["total_future"] if "advance_bookings" in d else "N/A"

        property_rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{d['name']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{d['city']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{d['bedrooms']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:{occ_color};font-weight:bold;">{occ_pct}{'%' if isinstance(occ_pct, int) else ''}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{avg_rate}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{d['avg_lead_time']}d</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{future}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f5f5f5;padding:20px;color:#333;">
<div style="max-width:800px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

<div style="background:#759b8f;color:white;padding:24px 30px;">
    <h1 style="margin:0;font-size:22px;">Daily Pricing Intelligence</h1>
    <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{date}</p>
</div>

<div style="padding:24px 30px;">

{section("🔴 Action Required: Low Occupancy", alerts, "#c0392b")}
{section("⚠️ Underpricing Warnings", warnings, "#e67e22")}
{section("📅 Upcoming Events: Price Increase Opportunities", event_alerts, "#2980b9")}

<h3 style="color:#333;margin-top:24px;">📊 Property Overview</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead>
    <tr style="background:#f8f8f8;">
        <th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">Property</th>
        <th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">City</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">BR</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Occupancy</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Avg Rate</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Lead Time</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Bookings</th>
    </tr>
</thead>
<tbody>
{property_rows}
</tbody>
</table>

"""

    # Per-property open nights
    for d in details:
        if "pricing" in d and d["pricing"]["available_nights"]:
            nights = d["pricing"]["available_nights"][:10]
            html += f'<h4 style="margin-top:16px;color:#555;">{d["name"]}: Open Nights</h4>'
            html += '<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            for n in nights:
                html += f'<tr><td style="padding:4px 8px;">{n["date"]}</td><td style="padding:4px 8px;">{n["day"][:3]}</td><td style="padding:4px 8px;font-weight:bold;">${n["price"]:.0f}</td></tr>'
            if len(d["pricing"]["available_nights"]) > 10:
                html += f'<tr><td colspan="3" style="padding:4px 8px;color:#999;">+ {len(d["pricing"]["available_nights"]) - 10} more nights</td></tr>'
            html += '</table>'

    if not alerts and not warnings:
        html += '<p style="padding:16px;background:#d5f5e3;border-radius:6px;color:#1e8449;font-weight:bold;">✅ All properties look healthy. No immediate pricing action needed.</p>'

    html += f"""
</div>

<div style="background:#f8f8f8;padding:16px 30px;font-size:12px;color:#999;border-top:1px solid #eee;">
    Generated by Nurture Pricing Bot | {datetime.now().strftime('%Y-%m-%d %H:%M')} ET
</div>

</div>
</body>
</html>"""

    return html


# ============================================
# EMAIL & SLACK
# ============================================
def send_email(subject, text_body, html_body):
    """Send the report via email."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(EMAIL_TO)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())

    print(f"  Email sent to {', '.join(EMAIL_TO)}")


def post_to_slack(text_report):
    """Post a summary to Slack."""
    if not SLACK_TOKEN or not SLACK_CHANNEL:
        print("  Slack not configured, skipping")
        return

    # Post just the alerts section
    lines = text_report.split("\n")
    summary_lines = []
    in_section = False
    for line in lines:
        if "ACTION REQUIRED" in line or "UNDERPRICING" in line or "UPCOMING EVENTS" in line:
            in_section = True
        elif "PROPERTY DETAILS" in line:
            in_section = False
        if in_section:
            summary_lines.append(line)

    if not summary_lines:
        summary_lines = ["✅ All properties look healthy. No pricing alerts today."]

    summary = "\n".join(summary_lines)
    msg = f"*Daily Pricing Report* ({datetime.now().strftime('%b %d')})\n\n{summary}"

    try:
        resp = requests.post("https://slack.com/api/chat.postMessage", headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json",
        }, json={
            "channel": SLACK_CHANNEL,
            "text": msg,
        })
        if resp.json().get("ok"):
            print("  Slack summary posted")
        else:
            print(f"  Slack error: {resp.json().get('error')}")
    except Exception as e:
        print(f"  Slack error: {e}")


# ============================================
# MAIN
# ============================================
def main():
    parser = argparse.ArgumentParser(description="Daily Pricing Intelligence Report")
    parser.add_argument("--dry-run", action="store_true", help="Print report to console, don't send email")
    parser.add_argument("--slack", action="store_true", help="Also post summary to Slack")
    args = parser.parse_args()

    start = time.time()

    try:
        text_report, html_report = generate_report()

        if not text_report:
            print("No properties found. Check HOSPITABLE_API_TOKEN.")
            return

        if args.dry_run:
            print("\n" + text_report)
        else:
            today_str = datetime.now().strftime("%b %d")
            subject = f"Nurture Pricing Report: {today_str}"
            send_email(subject, text_report, html_report)

            if args.slack:
                post_to_slack(text_report)

        elapsed = time.time() - start
        print(f"\nDone in {elapsed:.1f}s")

        # Log
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Report generated in {elapsed:.1f}s\n")

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

        # Log error
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - ERROR: {e}\n")


if __name__ == "__main__":
    main()
