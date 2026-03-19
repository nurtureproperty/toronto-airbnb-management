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


def detect_orphan_nights(calendar_days):
    """Detect unbookable gaps between reservations (orphan nights).
    These are gaps shorter than typical minimum stay that can't be booked."""
    today = datetime.now().date()
    orphans = []
    gap_start = None
    gap_days = []

    for day in calendar_days:
        try:
            day_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            if day_date < today:
                continue
            status = day.get("status", {}).get("reason", "")
            if status == "AVAILABLE":
                if gap_start is None:
                    gap_start = day_date
                gap_days.append(day)
            else:
                if gap_start and 1 <= len(gap_days) <= 2:
                    price = gap_days[0].get("price", {}).get("amount", 0) / 100 if gap_days else 0
                    orphans.append({
                        "start": gap_start.strftime("%Y-%m-%d"),
                        "nights": len(gap_days),
                        "current_price": price,
                        "suggested_price": round(price * 1.20, 2),  # 20% orphan premium
                    })
                gap_start = None
                gap_days = []
        except (ValueError, KeyError):
            continue

    return orphans


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

        # Tiered occupancy analysis (BLT strategy: 50% at BLT, 75% at half, 85% at 7d)
        tiered_occ = analyze_tiered_occupancy(cal, avg_lt)

        # Legacy occupancy analysis (for backward compat)
        occ = analyze_occupancy(cal, avg_lt)

        # Advance booking analysis
        adv = analyze_advance_bookings(future_res, pid, avg_lt)

        # Pricing snapshot
        pricing = get_pricing_snapshot(cal, avg_lt)

        # Orphan night detection
        orphans = detect_orphan_nights(cal)

        # Adjacent reservation opportunities
        adjacent = detect_adjacent_opportunities(cal)

        # Base price recommendation
        price_rec = calculate_base_price_recommendation(tiered_occ, pricing["avg_price"] if pricing else 0)

        detail = {
            "_property_id": pid,
            "name": name,
            "city": city,
            "bedrooms": beds,
            "avg_lead_time": avg_lt,
            "median_lead_time": med_lt,
            "booking_count": lt_count,
        }

        if tiered_occ:
            detail["tiered_occupancy"] = tiered_occ

            # Build ONE consolidated alert per property (pick the most urgent tier)
            failing_tiers = [t for t in tiered_occ if t["below_target"]]
            if failing_tiers:
                # Most urgent = smallest window first (7d > half BLT > BLT)
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

        # Build ONE consolidated warning per property
        warning_parts = []
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
            orphan_dates = [o["start"] for o in orphans[:3]]
            insights.append(
                f"💡 {name}: {len(orphans)} orphan gap(s) ({', '.join(orphan_dates)}). "
                f"Drop minimum stay and charge 20% premium to fill."
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

    # Build interactive action URL
    action_items = build_pricing_actions(property_details, calendars)
    action_url = generate_action_url(action_items)
    if action_url:
        print(f"  Action URL generated ({len(action_items)} actions)")
    else:
        print("  No action URL (missing secret or no actions)")

    # Build text report
    text_report = build_text_report(report_date, alerts, warnings, event_alerts, insights, property_details, events, action_url)
    html_report = build_html_report(report_date, alerts, warnings, event_alerts, insights, property_details, events, action_url)

    return text_report, html_report


def build_text_report(date, alerts, warnings, event_alerts, insights, details, events, action_url=None):
    lines = []
    lines.append(f"DAILY PRICING INTELLIGENCE REPORT")
    lines.append(f"{date}")
    lines.append("=" * 60)

    if action_url:
        lines.append(f"\n🎯 APPLY CHANGES: {action_url}")
        lines.append("   ^ Click to review and apply pricing adjustments with one click")

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

    lines.append(f"\n{'=' * 60}")
    lines.append("Generated by Nurture Pricing Bot")
    lines.append(f"Data as of {datetime.now().strftime('%Y-%m-%d %H:%M')} ET")

    return "\n".join(lines)


def build_html_report(date, alerts, warnings, event_alerts, insights, details, events, action_url=None):
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

{section("🔴 Action Required: Low Occupancy", alerts, "#c0392b")}
{section("⚠️ Underpricing Warnings", warnings, "#e67e22")}
{section("📅 Upcoming Events: Price Increase Opportunities", event_alerts, "#2980b9")}
{section("💡 Orphan Nights &amp; Adjacent Discounts", insights, "#8e44ad")}

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


def generate_action_url(action_items):
    """Upload actions to the server and return a short URL."""
    if not PRICING_ACTION_SECRET or not action_items:
        return None

    payload = {
        "date": datetime.now().strftime("%A, %B %d, %Y"),
        "expires": int((datetime.now() + timedelta(hours=48)).timestamp() * 1000),
        "items": action_items,
    }

    try:
        resp = requests.post(
            f"{PRICING_ACTION_BASE_URL}/upload",
            json={"secret": PRICING_ACTION_SECRET, "actions": payload},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            report_id = data.get("id")
            if report_id:
                return f"{PRICING_ACTION_BASE_URL}/{report_id}"
        print(f"  Warning: Failed to upload actions: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"  Warning: Failed to upload actions: {e}")

    return None


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
