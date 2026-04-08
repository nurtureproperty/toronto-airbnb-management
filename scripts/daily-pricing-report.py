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
import hmac
import hashlib
import base64
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

# Interactive pricing actions
PRICING_ACTION_SECRET = os.getenv("PRICING_ACTION_SECRET", "")
PRICING_ACTION_BASE_URL = "https://ghl-claude-server.vercel.app/pricing-actions"

# Thresholds (based on Danny Rusteen's BLT strategy)
# At BLT: 50% occupied. At half BLT: 75%. Within 7 days: 85-100%.
OCCUPANCY_THRESHOLD = 0.50  # Alert if below 50% at BLT
HALF_BLT_THRESHOLD = 0.75  # Alert if below 75% at half BLT
WEEK_THRESHOLD = 0.85  # Alert if below 85% within 7 days
ADVANCE_BOOKING_THRESHOLD = 0.60  # If 60%+ of lead time window is already booked, may be underpriced
MIN_LEAD_TIME_DAYS = 14  # Fallback if no historical data
BASE_PRICE_ADJUSTMENT = 0.05  # Adjust base price 5% per week based on occupancy


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

    # Confirmed 2026 events by city (researched Mar 19, 2026)
    # Format: (date, name, impact, cities) — cities is a list of which property cities are affected
    # "all" means all properties, otherwise list specific cities
    confirmed_events = [
        # Toronto concerts & sports
        (f"{year}-03-29", "Cardi B at Scotiabank Arena (Day 1)", "medium", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-03-30", "Cardi B (Day 2) + Blue Jays Home Opener", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-04-06", "Blue Jays vs LA Dodgers (3-game series starts)", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-04-16", "Florence + The Machine at Scotiabank Arena", "medium", ["Toronto"]),
        (f"{year}-05-09", "Karan Aujla at Scotiabank + TFC vs Inter Miami (Messi)", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-05-24", "Khalid at RBC Amphitheatre (Victoria Day weekend)", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-05-31", "Diljit Dosanjh at Rogers Centre (45K+ stadium show)", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-06-05", "Don Toliver at Scotiabank + CFL Stampeders Opener", "medium", ["Toronto", "Calgary"]),
        (f"{year}-06-08", "Blue Jays vs Phillies (3-game, pre-FIFA)", "medium", ["Toronto"]),
        (f"{year}-06-12", "FIFA World Cup: Canada match + Jays vs Yankees", "critical", ["Toronto", "Whitby", "Brampton", "Midland"]),
        (f"{year}-06-14", "Jays vs Yankees Game 3 + MGK at RBC", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-06-17", "FIFA World Cup: Ghana vs Panama", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-06-19", "Joji at Scotiabank Arena", "medium", ["Toronto"]),
        (f"{year}-06-25", "Pride Toronto Weekend starts", "high", ["Toronto"]),
        (f"{year}-06-28", "Pride Toronto Parade Day", "high", ["Toronto"]),
        (f"{year}-07-01", "Canada Day Long Weekend", "high", ["Toronto", "Whitby", "Brampton", "Midland"]),
        (f"{year}-07-03", "Calgary Stampede starts (10 days)", "critical", ["Calgary"]),
        (f"{year}-07-12", "Calgary Stampede ends", "critical", ["Calgary"]),
        (f"{year}-07-31", "Caribana / Caribbean Carnival", "high", ["Toronto", "Whitby", "Brampton"]),
        (f"{year}-08-20", "CNE starts (3 weeks)", "high", ["Toronto"]),
        (f"{year}-09-04", "TIFF (Toronto International Film Festival)", "high", ["Toronto"]),
        # Cottage country / Mont-Tremblant
        (f"{year}-05-08", "BLOOMAFEST Tremblant", "medium", ["Mont-Tremblant"]),
        (f"{year}-06-13", "Butter Tart Festival Midland (Ontario Top 100)", "medium", ["Midland"]),
        (f"{year}-06-21", "IRONMAN 70.3 Mont-Tremblant", "high", ["Mont-Tremblant"]),
        # Calgary
        (f"{year}-05-01", "Calgary International Beerfest", "medium", ["Calgary"]),
        # Medical / Convention (Toronto)
        (f"{year}-04-22", "ISHLT Medical Conference at MTCC (4 days)", "medium", ["Toronto"]),
        # General seasonal
        (f"{year}-02-14", "Valentine's Day Weekend", "medium", ["Toronto"]),
        (f"{year}-03-14", "March Break Start (Ontario)", "high", ["Toronto", "Whitby", "Brampton", "Midland", "Mont-Tremblant"]),
        (f"{year}-06-01", "Summer season start", "high", ["Toronto", "Whitby", "Brampton", "Midland", "Mont-Tremblant", "Calgary"]),
        (f"{year}-11-28", "Black Friday / US Thanksgiving visitors", "medium", ["Toronto"]),
        (f"{year}-12-20", "Holiday season peak starts", "high", ["Toronto", "Whitby", "Brampton", "Calgary"]),
    ]

    # Legacy general events (apply to all)
    gta_events = []
    for date_str, name, impact, cities in confirmed_events:
        gta_events.append((date_str, name, impact, cities))

    upcoming = []

    # Add holidays (apply to all cities)
    for date_str, name, impact in holidays:
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if start_date.date() <= event_date <= end_date.date():
                days_until = (event_date - start_date.date()).days
                upcoming.append({
                    "date": date_str,
                    "name": name,
                    "impact": impact,
                    "days_until": days_until,
                    "cities": ["all"],
                })
        except ValueError:
            continue

    # Add city-specific confirmed events
    for date_str, name, impact, cities in gta_events:
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if start_date.date() <= event_date <= end_date.date():
                days_until = (event_date - start_date.date()).days
                upcoming.append({
                    "date": date_str,
                    "name": name,
                    "impact": impact,
                    "days_until": days_until,
                    "cities": cities,
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


def detect_midterm_stays(reservations, property_id):
    """Detect active or upcoming mid-term stays (28+ nights) for a property.
    Mid-term stays are intentionally lower-priced and shouldn't trigger underpricing warnings."""
    today = datetime.now()
    midterm = []
    str_count = 0

    for res in reservations:
        if (res.get("_property_id") or res.get("property")) != property_id:
            continue
        if res.get("stay_type") == "owner_stay":
            continue

        nights = res.get("nights", 0)
        arrival = res.get("arrival_date") or res.get("check_in")
        departure = res.get("departure_date") or res.get("check_out")

        if not arrival or not departure:
            continue

        try:
            arr_dt = datetime.fromisoformat(arrival.replace("Z", "+00:00")).replace(tzinfo=None)
            dep_dt = datetime.fromisoformat(departure.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue

        # Active or future reservation
        if dep_dt < today:
            continue

        if nights >= 28:
            midterm.append({
                "arrival": arr_dt.strftime("%Y-%m-%d"),
                "departure": dep_dt.strftime("%Y-%m-%d"),
                "nights": nights,
                "active": arr_dt <= today < dep_dt,
            })
        else:
            str_count += 1

    return {
        "has_midterm": len(midterm) > 0,
        "active_midterm": any(m["active"] for m in midterm),
        "midterm_stays": midterm,
        "str_booking_count": str_count,
    }


def detect_orphan_nights(calendar_days, default_min_stay=2):
    """Detect unbookable gaps between two reservations (orphan nights).
    Only flags gaps that are shorter than the property's normal minimum stay
    AND are sandwiched between two RESERVED dates (not open stretches)."""
    today = datetime.now().date()

    # Parse all days into a structured list
    parsed = []
    for day in calendar_days:
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            parsed.append({
                "date": day_date,
                "date_str": day["date"],
                "day_name": day.get("day", "")[:3],
                "status": day.get("status", {}).get("reason", ""),
                "price_cents": day.get("price", {}).get("amount", 0),
                "min_stay": day.get("min_stay", default_min_stay),
            })
        except (ValueError, KeyError):
            continue

    parsed.sort(key=lambda x: x["date"])

    orphans = []
    i = 0
    while i < len(parsed):
        d = parsed[i]
        if d["date"] < today or d["status"] != "AVAILABLE":
            i += 1
            continue

        # Found start of a potential gap — collect consecutive available days
        gap = [d]
        j = i + 1
        while j < len(parsed) and parsed[j]["status"] == "AVAILABLE":
            gap.append(parsed[j])
            j += 1

        # Check: is there a RESERVED day before AND after this gap?
        has_reservation_before = i > 0 and parsed[i - 1]["status"] == "RESERVED"
        has_reservation_after = j < len(parsed) and parsed[j]["status"] == "RESERVED"

        # Only an orphan if sandwiched between reservations AND gap is shorter than min_stay
        if has_reservation_before and has_reservation_after and len(gap) < gap[0]["min_stay"]:
            checkout_date = parsed[i - 1]["date_str"]
            checkin_date = parsed[j]["date_str"]
            orphans.append({
                "dates": [g["date_str"] for g in gap],
                "day_names": [g["day_name"] for g in gap],
                "start": gap[0]["date_str"],
                "nights": len(gap),
                "current_min_stay": gap[0]["min_stay"],
                "current_price": gap[0]["price_cents"] / 100,
                "suggested_price": round(gap[0]["price_cents"] * 1.20 / 100, 2),
                "price_cents_per_date": [(g["date_str"], g["price_cents"]) for g in gap],
                "checkout_before": checkout_date,
                "checkin_after": checkin_date,
            })

        i = j  # Skip past the gap

    return orphans


def auto_apply_orphan_min_stay(property_id, orphans, token=None):
    """Auto-apply min_stay=1 on orphan night dates via Hospitable calendar PUT.
    Returns list of results for reporting."""
    if not orphans:
        return []

    results = []
    for orph in orphans:
        cal_dates = [{"date": d, "min_stay": 1} for d in orph["dates"]]

        try:
            resp = requests.put(
                f"{BASE}/properties/{property_id}/calendar",
                headers=HEADERS,
                json={"dates": cal_dates},
                timeout=15,
            )
            if resp.status_code in (200, 202):
                results.append({
                    "dates": orph["dates"],
                    "nights": orph["nights"],
                    "old_min_stay": orph["current_min_stay"],
                    "ok": True,
                })
            else:
                results.append({
                    "dates": orph["dates"],
                    "nights": orph["nights"],
                    "ok": False,
                    "error": f"API {resp.status_code}: {resp.text[:100]}",
                })
        except Exception as e:
            results.append({
                "dates": orph["dates"],
                "nights": orph["nights"],
                "ok": False,
                "error": str(e),
            })
        time.sleep(0.3)

    return results


def detect_adjacent_opportunities(calendar_days):
    """Find nights adjacent to reservations that could benefit from a discount.
    Lower prices 1-2 nights before/after bookings since demand drops for those specific dates."""
    today = datetime.now().date()
    opportunities = []

    days_list = []
    for day in calendar_days:
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            if day_date >= today:
                days_list.append({
                    "date": day_date,
                    "status": day.get("status", {}).get("reason", ""),
                    "price": day.get("price", {}).get("amount", 0) / 100,
                    "day_name": day.get("day", ""),
                })
        except (ValueError, KeyError):
            continue

    days_list.sort(key=lambda x: x["date"])

    for i, d in enumerate(days_list):
        if d["status"] != "AVAILABLE":
            continue

        # Check if adjacent to a reservation
        prev_booked = i > 0 and days_list[i - 1]["status"] == "RESERVED"
        next_booked = i < len(days_list) - 1 and days_list[i + 1]["status"] == "RESERVED"

        if prev_booked or next_booked:
            position = "checkout day" if prev_booked else "day before check-in"
            opportunities.append({
                "date": d["date"].strftime("%Y-%m-%d"),
                "day_name": d["day_name"][:3],
                "current_price": d["price"],
                "suggested_price": round(d["price"] * 0.85, 2),  # 15% adjacent discount
                "position": position,
            })

    return opportunities


def analyze_tiered_occupancy(calendar_days, avg_lead_time):
    """Analyze occupancy at three tiers: BLT, half BLT, and 7 days.
    Based on Danny Rusteen's strategy: 50% at BLT, 75% at half BLT, 85% within a week."""
    today = datetime.now().date()

    tiers = [
        {"name": "7 days", "days": 7, "target": WEEK_THRESHOLD},
        {"name": f"half BLT ({max(1, avg_lead_time // 2)}d)", "days": max(1, avg_lead_time // 2), "target": HALF_BLT_THRESHOLD},
        {"name": f"BLT ({avg_lead_time}d)", "days": avg_lead_time, "target": OCCUPANCY_THRESHOLD},
    ]

    results = []
    for tier in tiers:
        window_end = today + timedelta(days=tier["days"])
        window_days = []
        for day in calendar_days:
            try:
                day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
                if today <= day_date <= window_end:
                    window_days.append(day)
            except (ValueError, KeyError):
                continue

        if not window_days:
            continue

        total = len(window_days)
        booked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "RESERVED")
        blocked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "BLOCKED")
        bookable = total - blocked
        occ_rate = booked / bookable if bookable > 0 else 0

        results.append({
            "tier": tier["name"],
            "days": tier["days"],
            "target": tier["target"],
            "actual": occ_rate,
            "booked": booked,
            "bookable": bookable,
            "below_target": occ_rate < tier["target"],
        })

    return results


def analyze_occupancy_trend(calendar_days):
    """Check if occupancy trend is correct: 15-day > 30-day > 60-day.
    If 60-day is higher than 30-day, far-out premium needs to be raised.
    Based on Danny Rusteen's strategy."""
    today = datetime.now().date()

    windows = [
        {"name": "15-day", "days": 15},
        {"name": "30-day", "days": 30},
        {"name": "60-day", "days": 60},
    ]

    rates = {}
    for w in windows:
        window_end = today + timedelta(days=w["days"])
        window_days = []
        for day in calendar_days:
            try:
                day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
                if today <= day_date <= window_end:
                    window_days.append(day)
            except (ValueError, KeyError):
                continue

        if not window_days:
            continue

        total = len(window_days)
        booked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "RESERVED")
        blocked = sum(1 for d in window_days if d.get("status", {}).get("reason") == "BLOCKED")
        bookable = total - blocked
        rates[w["name"]] = round(booked / bookable * 100, 1) if bookable > 0 else 0

    if len(rates) < 3:
        return None

    # Check if trend is correct: 15 > 30 > 60
    correct_trend = rates["15-day"] >= rates["30-day"] >= rates["60-day"]
    inverted_far_out = rates["60-day"] > rates["30-day"]

    return {
        "rates": rates,
        "correct_trend": correct_trend,
        "inverted_far_out": inverted_far_out,
    }


def get_color_code(occupancy_pct, target=50):
    """Return color code based on Danny Rusteen's system.
    GREEN: 40-60% at BLT (on target)
    NO COLOR: above 60% (over-occupied)
    LIGHT RED: 20-40% (slightly under)
    DARK RED: 0-20% (significantly under)
    """
    occ = occupancy_pct * 100 if occupancy_pct <= 1 else occupancy_pct
    if occ >= 60:
        return "OVER"
    elif occ >= 40:
        return "GREEN"
    elif occ >= 20:
        return "LIGHT_RED"
    else:
        return "DARK_RED"


def calculate_base_price_recommendation(tiered_occupancy, current_avg_price):
    """Recommend base price adjustment based on occupancy vs targets.
    Rule: adjust 5% per week based on BLT occupancy."""
    if not tiered_occupancy:
        return None

    blt_tier = next((t for t in tiered_occupancy if "BLT" in t["tier"]), None)
    if not blt_tier:
        return None

    diff = blt_tier["actual"] - blt_tier["target"]

    if diff < -0.20:
        return {"action": "DROP", "pct": 10, "reason": f"Occupancy {round(blt_tier['actual']*100)}% is way below {round(blt_tier['target']*100)}% target at BLT"}
    elif diff < -0.10:
        return {"action": "DROP", "pct": 5, "reason": f"Occupancy {round(blt_tier['actual']*100)}% is below {round(blt_tier['target']*100)}% target at BLT"}
    elif diff > 0.20:
        return {"action": "RAISE", "pct": 10, "reason": f"Occupancy {round(blt_tier['actual']*100)}% is well above {round(blt_tier['target']*100)}% target at BLT. You may be underpriced"}
    elif diff > 0.10:
        return {"action": "RAISE", "pct": 5, "reason": f"Occupancy {round(blt_tier['actual']*100)}% is above {round(blt_tier['target']*100)}% target. Consider raising rates"}
    else:
        return {"action": "HOLD", "pct": 0, "reason": f"Occupancy {round(blt_tier['actual']*100)}% is on target at BLT ({round(blt_tier['target']*100)}%)"}


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
        return None, None, []

    property_ids = [p["id"] for p in properties]

    # 2. Fetch historical reservations per property for lead time calculation (last 6 months)
    print("  Fetching historical reservations per property...")
    historical_res = get_reservations_per_property(property_ids, now - timedelta(days=180), now)
    print(f"  Found {len(historical_res)} historical reservations")

    # 3. Calculate lead times per property
    lead_times = calculate_lead_times(historical_res)

    # 4. Fetch future reservations (include 60 days back to catch active mid-term stays)
    print("  Fetching current and future reservations...")
    future_res = get_reservations_per_property(property_ids, now - timedelta(days=60), now + timedelta(days=90))
    print(f"  Found {len(future_res)} current/future reservations")

    # 5. Fetch calendar for each property (next 90 days)
    print("  Fetching calendars...")
    calendars = {}
    for p in properties:
        cal = get_calendar(p["id"], now, now + timedelta(days=90))
        calendars[p["id"]] = cal
        time.sleep(0.2)

    # 6. Get upcoming events
    events = get_upcoming_events(now, days_ahead=90)

    # 7. Build report sections
    alerts = []          # High priority
    warnings = []        # Medium priority
    insights = []        # Nice to know
    orphan_actions = []  # Auto-applied orphan min_stay changes
    property_details = []
    dry_run = "--dry-run" in sys.argv

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

        # Mid-term stay detection
        midterm_info = detect_midterm_stays(future_res, pid)

        # Tiered occupancy analysis (BLT strategy: 50% at BLT, 75% at half, 85% at 7d)
        tiered_occ = analyze_tiered_occupancy(cal, avg_lt)

        # Legacy occupancy analysis (for backward compat)
        occ = analyze_occupancy(cal, avg_lt)

        # Advance booking analysis
        adv = analyze_advance_bookings(future_res, pid, avg_lt)

        # Pricing snapshot
        pricing = get_pricing_snapshot(cal, avg_lt)

        # Occupancy trend check (15 > 30 > 60 day rule)
        trend = analyze_occupancy_trend(cal)

        # Color code based on BLT occupancy
        blt_occ_rate = None
        blt_color = None
        if tiered_occ:
            blt_tier = next((t for t in tiered_occ if "BLT" in t["tier"]), None)
            if blt_tier:
                blt_occ_rate = round(blt_tier["actual"] * 100, 1)
                blt_color = get_color_code(blt_tier["actual"])

        # Orphan night detection
        orphans = detect_orphan_nights(cal)

        # Adjacent reservation opportunities
        adjacent = detect_adjacent_opportunities(cal)

        # Base price recommendation (skip RAISE if mid-term is filling the calendar)
        price_rec = calculate_base_price_recommendation(tiered_occ, pricing["avg_price"] if pricing else 0)

        # Add dollar amount to recommendation
        if price_rec and pricing and price_rec["action"] != "HOLD":
            avg_price = pricing["avg_price"]
            dollar_change = round(avg_price * price_rec["pct"] / 100)
            if price_rec["action"] == "DROP":
                price_rec["dollar"] = f"~${dollar_change} (from ${avg_price:.0f} to ${avg_price - dollar_change:.0f})"
            elif price_rec["action"] == "RAISE":
                price_rec["dollar"] = f"~${dollar_change} (from ${avg_price:.0f} to ${avg_price + dollar_change:.0f})"

        # If property has active mid-term stay and is fully booked, don't recommend RAISE
        if midterm_info["active_midterm"] and price_rec and price_rec["action"] == "RAISE":
            price_rec = {"action": "HOLD", "pct": 0, "reason": f"Mid-term rental active. Occupancy is high due to 30+ day booking, not STR demand. Review STR rates separately when mid-term ends"}

        detail = {
            "_property_id": pid,
            "name": name,
            "city": city,
            "bedrooms": beds,
            "avg_lead_time": avg_lt,
            "median_lead_time": med_lt,
            "booking_count": lt_count,
        }

        if trend:
            detail["occupancy_trend"] = trend
            # Alert on inverted trend (60-day higher than 30-day)
            if trend["inverted_far_out"] and not midterm_info["active_midterm"]:
                rates = trend["rates"]
                alerts.append(
                    f"📈 {name} ({city}): Inverted occupancy trend! "
                    f"60-day ({rates['60-day']}%) is higher than 30-day ({rates['30-day']}%). "
                    f"Far-out premium is too low. Raise it in PriceLabs immediately."
                )
            elif not trend["correct_trend"] and not midterm_info["active_midterm"]:
                rates = trend["rates"]
                warnings.append(
                    f"⚠️ {name} ({city}): Occupancy trend is off. "
                    f"15d: {rates['15-day']}%, 30d: {rates['30-day']}%, 60d: {rates['60-day']}%. "
                    f"Expected: 15d > 30d > 60d. Review far-out premium or customizations."
                )

        if blt_color:
            detail["blt_color"] = blt_color
            detail["blt_occupancy_pct"] = blt_occ_rate

        if price_rec and price_rec.get("dollar"):
            detail["price_dollar_rec"] = price_rec["dollar"]

        if midterm_info["has_midterm"]:
            detail["midterm"] = midterm_info

        if tiered_occ:
            detail["tiered_occupancy"] = tiered_occ

            # Skip low occupancy alerts if mid-term is active (calendar looks full)
            if not midterm_info["active_midterm"]:
                # Build ONE consolidated alert per property (pick the most urgent tier)
                failing_tiers = [t for t in tiered_occ if t["below_target"]]
                if failing_tiers:
                    most_urgent = failing_tiers[0]
                    parts = []
                    for t in failing_tiers:
                        parts.append(f"{round(t['actual']*100)}% at {t['tier']} (target {round(t['target']*100)}%)")
                    summary = ", ".join(parts)
                    total_open = most_urgent["bookable"] - most_urgent["booked"]

                    if most_urgent["days"] <= 7:
                        alerts.append(
                            f"🔴 {name} ({city}): {summary}. "
                            f"{total_open} open nights within a week. Drop prices 15-20% on remaining dates."
                        )
                    else:
                        alerts.append(
                            f"🔴 {name} ({city}): {summary}. "
                            f"Drop base price 5% this week."
                        )

        if occ:
            detail["occupancy"] = occ

        if adv:
            detail["advance_bookings"] = adv

        # Build ONE consolidated warning per property (skip if mid-term is inflating occupancy)
        warning_parts = []
        if not midterm_info["active_midterm"]:
            if adv and adv["far_advance_pct"] > 0.40 and adv["total_future"] >= 3:
                warning_parts.append(
                    f"{adv['far_advance_count']} of {adv['total_future']} bookings are beyond "
                    f"{round(avg_lt * 1.5)}d out (1.5x BLT of {avg_lt}d), farthest {adv['farthest_booking_days']}d"
                )
            if adv and adv.get("within_lead_fill_rate", 0) > ADVANCE_BOOKING_THRESHOLD:
                warning_parts.append(
                    f"{round(adv['within_lead_fill_rate'] * 100)}% fill rate within BLT window"
            )
        if price_rec and price_rec["action"] == "RAISE" and price_rec["pct"] >= 10:
            warning_parts.append(price_rec["reason"])

        if warning_parts:
            warnings.append(f"⚠️ {name} ({city}): {'. '.join(warning_parts)}. Raise base rate 5-10%.")

        # Build ONE consolidated insight per property for orphans + adjacent
        if orphans:
            detail["orphans"] = orphans

            # Auto-apply min_stay=1 on orphan dates (low risk, just opens bookability)
            if not dry_run:
                apply_results = auto_apply_orphan_min_stay(pid, orphans)
                for orph, result in zip(orphans, apply_results):
                    date_list = ", ".join(f"{d} ({dn})" for d, dn in zip(orph["dates"], orph["day_names"]))
                    if result["ok"]:
                        orphan_actions.append(
                            f"✅ {name} ({city}): Dropped min_stay from {orph['current_min_stay']} to 1 on {date_list}. "
                            f"{orph['nights']}-night gap between checkout {orph['checkout_before']} and check-in {orph['checkin_after']}."
                        )
                    else:
                        orphan_actions.append(
                            f"❌ {name} ({city}): Failed to update {date_list}. Error: {result.get('error', 'unknown')}"
                        )
            else:
                for orph in orphans:
                    date_list = ", ".join(f"{d} ({dn})" for d, dn in zip(orph["dates"], orph["day_names"]))
                    orphan_actions.append(
                        f"🔧 {name} ({city}): Would drop min_stay from {orph['current_min_stay']} to 1 on {date_list}. "
                        f"{orph['nights']}-night gap between checkout {orph['checkout_before']} and check-in {orph['checkin_after']}. [DRY RUN]"
                    )

            # Price bump goes to interactive page (not auto-applied)
            orphan_dates = [o["start"] for o in orphans[:3]]
            insights.append(
                f"💡 {name}: {len(orphans)} orphan gap(s) opened. Consider 20% price bump on those dates."
            )

        if adjacent and len(adjacent) <= 5:
            detail["adjacent"] = adjacent
            adj_dates = [f"{a['date']} ({a['day_name']})" for a in adjacent[:3]]
            insights.append(
                f"💡 {name}: {len(adjacent)} night(s) adjacent to reservations ({', '.join(adj_dates)}). "
                f"Consider 15% discount to fill."
            )

        if price_rec:
            detail["price_recommendation"] = price_rec
            detail["price_rec"] = price_rec

        if pricing:
            detail["pricing"] = pricing
            detail["_pricing_snapshot"] = pricing

        property_details.append(detail)

    # Event alerts
    event_alerts = []
    critical_impact = [e for e in events if e["impact"] == "critical" and e["days_until"] <= 90]
    high_impact = [e for e in events if e["impact"] == "high" and e["days_until"] <= 45]
    medium_impact = [e for e in events if e["impact"] == "medium" and e["days_until"] <= 30]

    for e in critical_impact:
        cities = ", ".join(e.get("cities", ["all"]))
        event_alerts.append(
            f"🔥 {e['name']} ({e['date']}): {e['days_until']} days away. "
            f"CRITICAL demand. Raise prices 50-100%. Affects: {cities}"
        )
    for e in high_impact:
        cities = ", ".join(e.get("cities", ["all"]))
        event_alerts.append(
            f"📅 {e['name']} ({e['date']}): {e['days_until']} days away. "
            f"HIGH impact. Raise prices 20-30%. Affects: {cities}"
        )
    for e in medium_impact:
        cities = ", ".join(e.get("cities", ["all"]))
        event_alerts.append(
            f"📅 {e['name']} ({e['date']}): {e['days_until']} days away. "
            f"MEDIUM impact. Raise 10-15%. Affects: {cities}"
        )

    # ---- 180-Day STR Night Tracker ----
    # Cities with 180-night STR limits (entire-home only, under 28 days)
    STR_LIMIT_CITIES = {"toronto", "mississauga", "brampton", "whitby", "oshawa", "milton", "burlington", "vaughan", "oakville"}
    str_tracker = []
    year_start = date(now.year, 1, 1)
    year_end = date(now.year, 12, 31)

    for p in properties:
        city_lower = p["city"].lower().strip()
        if city_lower not in STR_LIMIT_CITIES:
            continue
        pid = p["id"]
        # Count STR nights (under 28 days) from Jan 1 to today
        prop_res = [r for r in historical_res + future_res if r.get("_property_id") == pid]
        # Deduplicate by reservation ID
        seen_ids = set()
        unique_res = []
        for r in prop_res:
            rid = r.get("id") or r.get("code")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                unique_res.append(r)

        str_nights_used = 0
        str_nights_upcoming = 0
        for r in unique_res:
            status = (r.get("status") or r.get("reservation_status") or "").lower()
            if status in ("cancelled", "canceled", "denied"):
                continue
            if r.get("owner_stay"):
                continue
            nights = r.get("nights") or 0
            if nights >= 28:
                continue  # Mid-term, doesn't count toward 180
            ci_str = r.get("check_in") or r.get("arrival_date")
            co_str = r.get("check_out") or r.get("departure_date")
            if not ci_str or not co_str:
                continue
            try:
                ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
                co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                continue
            # Count nights that fall in this calendar year
            overlap_start = max(ci, year_start)
            overlap_end = min(co, year_end)
            overlap = (overlap_end - overlap_start).days
            if overlap <= 0:
                continue
            # Split into past (used) and future (upcoming)
            today_date = now.date()
            past_end = min(co, today_date)
            past_start = max(ci, year_start)
            past_nights = max(0, (past_end - past_start).days)
            future_start = max(ci, today_date)
            future_end = min(co, year_end)
            future_nights = max(0, (future_end - future_start).days)
            str_nights_used += past_nights
            str_nights_upcoming += future_nights

        remaining = 180 - str_nights_used - str_nights_upcoming
        if remaining < 0:
            status_text = "⛔ OVER LIMIT"
            status_color = "#c0392b"
        elif remaining <= 20:
            status_text = "🔴 Switch to Mid-term Now"
            status_color = "#c0392b"
        elif remaining <= 50:
            status_text = "🟡 Getting Close"
            status_color = "#e67e22"
        else:
            status_text = "🟢 On Track"
            status_color = "#27ae60"

        str_tracker.append({
            "name": p["short_name"],
            "city": p["city"],
            "used": str_nights_used,
            "upcoming": str_nights_upcoming,
            "total_committed": str_nights_used + str_nights_upcoming,
            "remaining": max(0, remaining),
            "status": status_text,
            "status_color": status_color,
        })

        # Alert if approaching limit
        if remaining <= 20 and remaining >= 0:
            alerts.append(
                f"⛔ {p['short_name']} ({p['city']}): Only {remaining} STR nights remaining out of 180. "
                f"Used {str_nights_used}, upcoming {str_nights_upcoming}. Switch to 28+ day minimum immediately."
            )
        elif remaining < 0:
            alerts.append(
                f"🚨 {p['short_name']} ({p['city']}): OVER the 180-night STR limit! "
                f"{str_nights_used + str_nights_upcoming} nights committed. Reduce bookings or extend stays to 28+ days."
            )

    # Build interactive action URL
    action_items = build_pricing_actions(property_details, calendars)
    action_url = generate_action_url(action_items)
    if action_url:
        print(f"  Action URL generated ({len(action_items)} actions)")
    else:
        print("  No action URL (missing secret or no actions)")

    # Build text report
    text_report = build_text_report(report_date, alerts, warnings, event_alerts, insights, property_details, events, action_url, orphan_actions, str_tracker)
    html_report = build_html_report(report_date, alerts, warnings, event_alerts, insights, property_details, events, action_url, orphan_actions, str_tracker)

    return text_report, html_report, property_details


def build_text_report(date, alerts, warnings, event_alerts, insights, details, events, action_url=None, orphan_actions=None, str_tracker=None):
    lines = []
    lines.append(f"DAILY PRICING INTELLIGENCE REPORT")
    lines.append(f"{date}")
    lines.append("=" * 60)

    if action_url:
        lines.append(f"\n🎯 APPLY CHANGES: {action_url}")
        lines.append("   ^ Click to review and apply pricing adjustments with one click")

    if orphan_actions:
        lines.append("\n🔧 ORPHAN NIGHT OVERRIDES (auto-applied)")
        lines.append("-" * 40)
        for a in orphan_actions:
            lines.append(f"  {a}")

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

    if insights:
        lines.append("\n💡 ORPHAN NIGHTS & ADJACENT DISCOUNTS")
        lines.append("-" * 40)
        for i in insights:
            lines.append(f"  {i}")

    lines.append("\n📊 PROPERTY DETAILS")
    lines.append("-" * 40)
    for d in details:
        lines.append(f"\n  {d['name']} ({d['city']}, {d['bedrooms']}BR)")
        lines.append(f"    Avg lead time: {d['avg_lead_time']}d (median {d['median_lead_time']}d, based on {d['booking_count']} bookings)")

        if "midterm" in d and d["midterm"]["has_midterm"]:
            mt = d["midterm"]
            for stay in mt["midterm_stays"]:
                status = "ACTIVE NOW" if stay["active"] else "upcoming"
                lines.append(f"    🏠 Mid-term rental ({stay['nights']}n, {stay['arrival']} to {stay['departure']}) [{status}]")

        # Tiered occupancy (BLT strategy)
        if "tiered_occupancy" in d:
            lines.append(f"    Occupancy targets (BLT strategy):")
            for tier in d["tiered_occupancy"]:
                actual = round(tier["actual"] * 100)
                target = round(tier["target"] * 100)
                status = "✅" if not tier["below_target"] else "❌"
                lines.append(f"      {status} {tier['tier']}: {actual}% (target: {target}%) [{tier['booked']}/{tier['bookable']} nights]")

        # Price recommendation
        if "price_recommendation" in d:
            rec = d["price_recommendation"]
            icon = "📈" if rec["action"] == "RAISE" else "📉" if rec["action"] == "DROP" else "➡️"
            lines.append(f"    {icon} Recommendation: {rec['action']} {rec['pct']}%. {rec['reason']}")

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

        if "orphans" in d:
            lines.append(f"    Orphan nights: {len(d['orphans'])} gap(s) detected. Raise price 20% and drop minimum stay.")

        if "adjacent" in d:
            lines.append(f"    Adjacent opportunities: {len(d['adjacent'])} nights next to reservations could use 15% discount.")

    if not alerts and not warnings:
        lines.append("\n✅ All properties look healthy. No immediate pricing action needed.")

    if str_tracker:
        lines.append(f"\n{'=' * 60}")
        lines.append("📋 180-DAY STR NIGHT TRACKER")
        lines.append("-" * 40)
        lines.append(f"{'Property':<30} {'Used':>5} {'Upcoming':>8} {'Total':>7} {'Left':>5}  Status")
        for t in str_tracker:
            lines.append(f"{t['name']:<30} {t['used']:>5} {t['upcoming']:>8} {t['total_committed']:>5}/180 {t['remaining']:>5}  {t['status']}")

    lines.append(f"\n{'=' * 60}")
    lines.append("Generated by Nurture Pricing Bot")
    lines.append(f"Data as of {datetime.now().strftime('%Y-%m-%d %H:%M')} ET")

    return "\n".join(lines)


def build_html_report(date, alerts, warnings, event_alerts, insights, details, events, action_url=None, orphan_actions=None, str_tracker=None):
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

        # Price recommendation badge
        rec_badge = ""
        if "price_recommendation" in d:
            rec = d["price_recommendation"]
            if rec["action"] == "DROP":
                rec_badge = f'<span style="background:#c0392b;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">DROP {rec["pct"]}%</span>'
            elif rec["action"] == "RAISE":
                rec_badge = f'<span style="background:#27ae60;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">RAISE {rec["pct"]}%</span>'
            else:
                rec_badge = f'<span style="background:#7f8c8d;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">HOLD</span>'

        property_rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{d['name']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{d['city']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{d['bedrooms']}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:{occ_color};font-weight:bold;">{occ_pct}{'%' if isinstance(occ_pct, int) else ''}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{avg_rate}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{d['avg_lead_time']}d</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{future}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{rec_badge}</td>
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

{"" if not action_url else f'''<div style="text-align:center;margin-bottom:24px;padding:20px;background:#f0faf6;border-radius:8px;border:2px solid #759b8f;">
    <p style="margin:0 0 12px;font-size:16px;font-weight:bold;color:#333;">Ready to apply these changes?</p>
    <a href="{action_url}" style="display:inline-block;padding:14px 40px;background:#759b8f;color:white;text-decoration:none;border-radius:6px;font-size:16px;font-weight:bold;">Review &amp; Apply Pricing Changes</a>
    <p style="margin:10px 0 0;font-size:12px;color:#999;">Select which adjustments to apply. Changes update Hospitable immediately.</p>
</div>'''}

{section("🔧 Orphan Night Overrides (auto-applied)", orphan_actions or [], "#16a085")}
{section("🔴 Action Required: Low Occupancy", alerts, "#c0392b")}
{section("⚠️ Underpricing Warnings", warnings, "#e67e22")}
{section("📅 Upcoming Events: Price Increase Opportunities", event_alerts, "#2980b9")}
{section("💡 Orphan Nights &amp; Adjacent Discounts", insights, "#8e44ad")}

"""

    # 180-Day STR Tracker table
    if str_tracker:
        html += """<h3 style="color:#333;margin-top:24px;">📋 180-Day STR Night Tracker</h3>
<p style="font-size:12px;color:#999;margin-top:-8px;margin-bottom:8px;">Toronto, Mississauga, Brampton, and other 180-night limit cities. Only counts stays under 28 nights.</p>
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead>
    <tr style="background:#f8f8f8;">
        <th style="padding:8px;text-align:left;border-bottom:2px solid #ddd;">Property</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">City</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Used</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Upcoming</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Total</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Remaining</th>
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Status</th>
    </tr>
</thead>
<tbody>"""
        for t in str_tracker:
            html += f"""
    <tr>
        <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{t['name']}</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{t['city']}</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{t['used']}</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{t['upcoming']}</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;font-weight:bold;">{t['total_committed']}/180</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;font-weight:bold;">{t['remaining']}</td>
        <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;color:{t['status_color']};font-weight:bold;">{t['status']}</td>
    </tr>"""
        html += "</tbody></table>"

    html += """

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
        <th style="padding:8px;text-align:center;border-bottom:2px solid #ddd;">Action</th>
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
def build_pricing_actions(property_details, calendars=None):
    """Build the signed action payload for the interactive pricing page."""
    items = []
    today = datetime.now().date()

    for d in property_details:
        pid = d.get("_property_id", "")
        name = d["name"]
        city = d["city"]

        # Price drop recommendations (from tiered occupancy)
        if "price_recommendation" in d and d["price_recommendation"]["action"] == "DROP":
            rec = d["price_recommendation"]
            pct = rec["pct"]
            if "pricing" in d and d["pricing"]["available_nights"]:
                dates = []
                for n in d["pricing"]["available_nights"]:
                    current_cents = int(n["price"] * 100)
                    new_cents = int(current_cents * (1 - pct / 100))
                    dates.append({"date": n["date"], "current_price": current_cents, "new_price": new_cents})
                if dates:
                    items.append({
                        "group": "Price Drops",
                        "property": name,
                        "property_id": pid,
                        "city": city,
                        "description": f"Drop {pct}% on {len(dates)} open night(s). {rec['reason']}",
                        "dates": dates,
                        "recommended": True,
                    })

        # Price increase recommendations — look at ALL available nights (next 90 days)
        if "price_recommendation" in d and d["price_recommendation"]["action"] == "RAISE":
            rec = d["price_recommendation"]
            pct = rec["pct"]
            dates = []

            # First try available nights from pricing snapshot (within BLT)
            if "pricing" in d and d["pricing"]["available_nights"]:
                for n in d["pricing"]["available_nights"]:
                    current_cents = int(n["price"] * 100)
                    new_cents = int(current_cents * (1 + pct / 100))
                    dates.append({"date": n["date"], "current_price": current_cents, "new_price": new_cents})

            # If no dates in BLT (100% booked), pull from full calendar
            if not dates and calendars and pid in calendars:
                for day in calendars[pid]:
                    try:
                        day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
                        if day_date < today:
                            continue
                        if day.get("status", {}).get("reason") == "AVAILABLE" and "price" in day:
                            current_cents = day["price"]["amount"]
                            new_cents = int(current_cents * (1 + pct / 100))
                            dates.append({"date": day["date"], "current_price": current_cents, "new_price": new_cents})
                    except (ValueError, KeyError):
                        continue

            if dates:
                items.append({
                    "group": "Price Increases",
                    "property": name,
                    "property_id": pid,
                    "city": city,
                    "description": f"Raise {pct}% on {len(dates)} open night(s). {rec['reason']}",
                    "dates": dates[:30],  # Cap at 30 dates to keep URL reasonable
                    "recommended": False,
                })

        # Orphan night premiums
        if "orphans" in d:
            for orph in d["orphans"]:
                current_cents = int(orph["current_price"] * 100)
                new_cents = int(orph["suggested_price"] * 100)
                items.append({
                    "group": "Orphan Night Premiums",
                    "property": name,
                    "property_id": pid,
                    "city": city,
                    "description": f"{orph['nights']}-night gap. Charge 20% premium to fill.",
                    "dates": [{"date": orph["start"], "current_price": current_cents, "new_price": new_cents}],
                    "recommended": True,
                })

        # Adjacent discounts
        if "adjacent" in d:
            for adj in d["adjacent"][:3]:
                current_cents = int(adj["current_price"] * 100)
                new_cents = int(adj["suggested_price"] * 100)
                items.append({
                    "group": "Adjacent Discounts",
                    "property": name,
                    "property_id": pid,
                    "city": city,
                    "description": f"{adj['position']} on {adj['day_name']}. 15% discount to fill.",
                    "dates": [{"date": adj["date"], "current_price": current_cents, "new_price": new_cents}],
                    "recommended": True,
                })

    return items


PRICING_RULES_SHEET_ID = "1cnp7qHzfJ3mScJVpWUUInGWqK_0ZEAtHJFXszoJf-MI"
PENDING_ACTIONS_TAB = "Pending Actions"

def _get_gsheets_client():
    """Get an authorized gspread client."""
    import gspread
    from google.oauth2.credentials import Credentials

    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.getenv("GSHEETS_REFRESH_TOKEN")

    if not refresh_token or not client_id:
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def generate_action_url(action_items):
    """Write actions to Google Sheets and return a URL to the action page."""
    if not action_items:
        return None

    report_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_date = datetime.now().strftime("%A, %B %d, %Y")
    expires = (datetime.now() + timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")

    try:
        gc = _get_gsheets_client()
        if not gc:
            print("  Warning: Google Sheets not configured, skipping action URL")
            return None

        spreadsheet = gc.open_by_key(PRICING_RULES_SHEET_ID)
        ws = spreadsheet.worksheet(PENDING_ACTIONS_TAB)

        # Clear previous actions and write new ones
        ws.clear()

        # Header row
        header = ["Report ID", "Report Date", "Expires", "Index", "Group", "Property", "Property ID", "City", "Description", "Recommended", "Dates JSON"]
        rows = [header]

        for idx, item in enumerate(action_items):
            dates_json = json.dumps(item.get("dates", []))
            rows.append([
                report_id,
                report_date,
                expires,
                str(idx),
                item.get("group", ""),
                item.get("property", ""),
                item.get("property_id", ""),
                item.get("city", ""),
                item.get("description", ""),
                "TRUE" if item.get("recommended") else "FALSE",
                dates_json,
            ])

        ws.update(rows, "A1")
        print(f"  Actions written to Google Sheets ({len(action_items)} rows)")

        # Return URL with report ID (server reads from Sheets)
        return f"{PRICING_ACTION_BASE_URL}/{report_id}"

    except Exception as e:
        print(f"  Warning: Failed to write actions to Sheets: {e}")
        return None


WEEKLY_TRACKING_TAB = "Weekly Tracking"

def update_weekly_tracking(property_details):
    """On Wednesdays, append a row per property to the Weekly Tracking sheet.
    Tracks: date, property name, BLT occupancy %, color code, base price, recommendation.
    This builds the historical tracking Danny Rusteen recommends."""
    today = datetime.now()
    if today.weekday() != 2:  # 2 = Wednesday
        return

    try:
        gc = _get_gsheets_client()
        if not gc:
            print("  Google Sheets not configured, skipping weekly tracking")
            return

        spreadsheet = gc.open_by_key(PRICING_RULES_SHEET_ID)

        # Create sheet if it doesn't exist
        try:
            ws = spreadsheet.worksheet(WEEKLY_TRACKING_TAB)
        except Exception:
            ws = spreadsheet.add_worksheet(title=WEEKLY_TRACKING_TAB, rows=500, cols=10)
            ws.update("A1:H1", [["Date", "Property", "City", "BLT (days)", "Occupancy at BLT", "Color Code", "Avg Price", "Recommendation"]])

        date_str = today.strftime("%Y-%m-%d")
        rows = []
        for d in property_details:
            color = d.get("blt_color", "")
            blt_occ = d.get("blt_occupancy_pct", "")
            avg_price = ""
            rec = ""
            if d.get("occupancy") and d["occupancy"].get("occupancy_rate") is not None:
                pass  # blt_occ already set above
            if "tiered_occupancy" in d:
                pricing_snap = d.get("_pricing_snapshot")
                if pricing_snap:
                    avg_price = f"${pricing_snap['avg_price']:.0f}"
            if "price_rec" in d:
                pr = d["price_rec"]
                rec = f"{pr['action']} {pr['pct']}%"
                if pr.get("dollar"):
                    rec += f" ({pr['dollar']})"

            rows.append([
                date_str,
                d.get("name", ""),
                d.get("city", ""),
                str(d.get("avg_lead_time", "")),
                f"{blt_occ}%" if blt_occ else "",
                color,
                avg_price,
                rec,
            ])

        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            print(f"  Weekly tracking: {len(rows)} rows added to '{WEEKLY_TRACKING_TAB}' sheet")

    except Exception as e:
        print(f"  Warning: Failed to update weekly tracking: {e}")


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
        text_report, html_report, property_details = generate_report()

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

        # Weekly tracking (only runs on Wednesdays)
        if property_details:
            update_weekly_tracking(property_details)

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
