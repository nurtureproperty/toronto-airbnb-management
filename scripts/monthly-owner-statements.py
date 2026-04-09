"""
Monthly Owner Statements (Draft)

Generates a single email to info@nurtre.io and angelica@nurtre.io containing
draft owner statements for ALL managed properties. The team reviews and
manually forwards to each owner after adding any personal notes.

Data sources:
  - Hospitable API (reservations, financials, reviews, calendar)
  - Notion (commission rates, property details)
  - Pricing Dashboard Google Sheet (change log, 180-day tracker)

Usage:
  python scripts/monthly-owner-statements.py              # Send email
  python scripts/monthly-owner-statements.py --dry-run    # Print to console only

Schedule: Last day of each month at 9:00 AM via Windows Task Scheduler
"""

import os
import sys
import time
import smtplib
import argparse
import requests
import re
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from calendar import monthrange
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# Hospitable
HOSPITABLE_TOKEN = os.getenv("HOSPITABLE_API_TOKEN")
HOSPITABLE_API = "https://public.api.hospitable.com/v2"
HOSP_HEADERS = {"Authorization": f"Bearer {HOSPITABLE_TOKEN}"}

# Google Sheets
GSHEETS_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
GSHEETS_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
GSHEETS_REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")
DASHBOARD_SHEET_ID = "1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"

# Notion
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
PROPERTIES_DB_ID = "2d509a91-8762-8030-bd0b-d64efe777f87"

# Email
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
SMTP_USER = os.getenv("EMAIL_SMTP_USER")
SMTP_PASS = os.getenv("EMAIL_SMTP_PASSWORD")
EMAIL_TO = ["info@nurtre.io", "angelica@nurtre.io"]

# STR limit cities
STR_LIMIT_CITIES = {"toronto", "mississauga", "brampton", "whitby", "oshawa", "milton", "burlington", "vaughan", "oakville"}


# ================== API HELPERS ==================

def hosp_get(path, params=None):
    url = f"{HOSPITABLE_API}{path}"
    r = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if r.status_code != 200:
        print(f"  Hospitable error {r.status_code} on {path}")
        return None
    time.sleep(0.2)
    return r.json()


def fetch_all_properties():
    all_props = []
    page = 1
    while True:
        data = hosp_get("/properties", {"page": page, "per_page": 50})
        if not data:
            break
        all_props.extend(data.get("data", []))
        if page >= data.get("meta", {}).get("last_page", 1):
            break
        page += 1
    return all_props


def fetch_reservations(property_id, start_date, end_date):
    all_res = []
    page = 1
    while True:
        data = hosp_get("/reservations", {
            "properties[]": property_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "include": "financials,guest",
            "per_page": 50,
            "page": page,
        })
        if not data:
            break
        all_res.extend(data.get("data", []))
        if page >= data.get("meta", {}).get("last_page", 1):
            break
        page += 1
    return all_res


def fetch_reviews(property_id, start_date, end_date):
    """Fetch reviews for a property."""
    data = hosp_get(f"/properties/{property_id}/reviews", {
        "per_page": 50,
        "include": "reservation",
    })
    if not data:
        return []
    # Filter to reviews within date range
    reviews = []
    for rev in data.get("data", []):
        created = rev.get("created_at") or rev.get("date") or ""
        if created:
            try:
                rev_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()
                if start_date <= rev_date <= end_date:
                    reviews.append(rev)
            except (ValueError, TypeError):
                pass
    return reviews


def fetch_calendar(property_id, start_date, end_date):
    data = hosp_get(f"/properties/{property_id}/calendar", {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    })
    if not data:
        return []
    inner = data.get("data", {})
    if isinstance(inner, dict):
        return inner.get("days", [])
    return inner if isinstance(inner, list) else []


# ================== NOTION ==================

def fetch_property_notion_data():
    if not NOTION_TOKEN:
        return {}
    mapping = {}
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(
            f"https://api.notion.com/v1/databases/{PROPERTIES_DB_ID}/query",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if r.status_code != 200:
            return mapping
        data = r.json()
        for row in data.get("results", []):
            props = row.get("properties", {})
            title_rt = props.get("Property", {}).get("title", [])
            owner_rt = props.get("Homeowner name", {}).get("rich_text", [])
            split_rt = props.get("split", {}).get("rich_text", [])
            pname = title_rt[0].get("plain_text", "").strip() if title_rt else ""
            owner = owner_rt[0].get("plain_text", "").strip() if owner_rt else ""
            split_str = split_rt[0].get("plain_text", "").strip() if split_rt else ""
            commission = None
            if split_str:
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", split_str)
                if m:
                    commission = float(m.group(1)) / 100
            if pname:
                mapping[pname] = {"owner": owner, "commission": commission, "split_str": split_str}
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return mapping


def fuzzy_match_notion(prop_name, notion_data):
    if not prop_name or not notion_data:
        return None
    name_lower = prop_name.lower()
    for notion_name, entry in notion_data.items():
        notion_lower = notion_name.lower()
        if notion_lower in name_lower or name_lower in notion_lower:
            return entry
        notion_tokens = set(notion_lower.split())
        name_tokens = set(name_lower.split())
        if len(notion_tokens & name_tokens) >= 2:
            return entry
    return None


# ================== GOOGLE SHEETS ==================

def get_sheets_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GSHEETS_CLIENT_ID,
        "client_secret": GSHEETS_CLIENT_SECRET,
        "refresh_token": GSHEETS_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    return r.json()["access_token"]


def sheets_get_values(range_a1):
    token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{DASHBOARD_SHEET_ID}/values/{range_a1}"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return []
    return r.json().get("values", [])


def get_pricing_changes(property_name, month_start, month_end):
    """Get pricing changes from the Change Log for this property this month."""
    data = sheets_get_values("Change Log!A:F")
    changes = []
    for row in data[1:]:  # skip header
        if len(row) < 5:
            continue
        row_date = row[0]
        row_prop = row[1] if len(row) > 1 else ""
        row_field = row[2] if len(row) > 2 else ""
        row_from = row[3] if len(row) > 3 else ""
        row_to = row[4] if len(row) > 4 else ""
        if property_name.lower() in row_prop.lower() or row_prop.lower() in property_name.lower():
            changes.append({"field": row_field, "from": row_from, "to": row_to})
    return changes


def get_str_tracker_data():
    """Get 180-day STR tracker data."""
    data = sheets_get_values("180-Day STR Tracker!A:H")
    tracker = {}
    for row in data[1:]:
        if len(row) >= 7:
            name = row[0]
            tracker[name] = {
                "city": row[1] if len(row) > 1 else "",
                "used": row[2] if len(row) > 2 else "0",
                "upcoming": row[3] if len(row) > 3 else "0",
                "total": row[4] if len(row) > 4 else "0",
                "remaining": row[5] if len(row) > 5 else "180",
                "status": row[6] if len(row) > 6 else "",
            }
    return tracker


# ================== STATEMENT BUILDER ==================

def build_property_statement(prop, reservations, reviews, calendar, notion_entry, pricing_changes, str_data, month_start, month_end):
    """Build one property's owner statement as HTML."""
    name = prop.get("name", "Unknown Property")
    owner = (notion_entry or {}).get("owner", "Property Owner")
    commission_rate = (notion_entry or {}).get("commission") or 0.15
    split_str = (notion_entry or {}).get("split_str", "15%")
    city = (prop.get("address", {}).get("city") or "").strip()
    month_name = month_start.strftime("%B %Y")

    # Filter reservations to this month (active, not cancelled)
    month_res = []
    for r in reservations:
        status = (r.get("status") or "").lower()
        if status in ("cancelled", "canceled", "denied"):
            continue
        ci_str = r.get("check_in") or r.get("arrival_date")
        co_str = r.get("check_out") or r.get("departure_date")
        if not ci_str or not co_str:
            continue
        try:
            ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
            co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        # Include if any nights overlap with this month
        overlap_start = max(ci, month_start)
        overlap_end = min(co, month_end + timedelta(days=1))
        if (overlap_end - overlap_start).days > 0:
            month_res.append(r)

    # Calculate revenue
    total_host_revenue = 0
    total_nights_booked = 0
    total_cleaning_fees = 0
    booking_details = []

    for r in month_res:
        ci_str = r.get("check_in") or r.get("arrival_date")
        co_str = r.get("check_out") or r.get("departure_date")
        ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
        co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()

        fin = r.get("financials", {})
        host = fin.get("host") or {}
        revenue_obj = host.get("revenue") or {}
        raw_revenue = revenue_obj.get("amount", 0)
        try:
            total_rev = float(raw_revenue or 0) / 100
        except (ValueError, TypeError):
            total_rev = 0

        # Get cleaning fee
        guest_fees = host.get("guest_fees") or []
        cleaning = 0
        for fee in guest_fees:
            if "clean" in (fee.get("label") or "").lower():
                cleaning = float(fee.get("amount", 0)) / 100

        # Calculate overlap nights in this month
        overlap_start = max(ci, month_start)
        overlap_end = min(co, month_end + timedelta(days=1))
        overlap_nights = (overlap_end - overlap_start).days
        total_nights_all = (co - ci).days or 1

        # Prorate revenue to this month
        month_revenue = total_rev * (overlap_nights / total_nights_all)
        month_cleaning = cleaning * (overlap_nights / total_nights_all)

        total_host_revenue += month_revenue
        total_nights_booked += overlap_nights
        total_cleaning_fees += month_cleaning

        # Guest name
        guest = r.get("guests", [{}])
        if isinstance(guest, list) and guest:
            guest_name = guest[0].get("name") or guest[0].get("first_name", "Guest")
        elif isinstance(guest, dict):
            guest_name = guest.get("name") or guest.get("first_name", "Guest")
        else:
            guest_name = "Guest"

        booking_details.append({
            "guest": guest_name,
            "check_in": ci.strftime("%b %d"),
            "check_out": co.strftime("%b %d"),
            "nights": overlap_nights,
            "revenue": month_revenue,
        })

    # Commission calculation
    management_fee = total_host_revenue * commission_rate
    owner_payout = total_host_revenue - management_fee

    # Occupancy
    days_in_month = (month_end - month_start).days + 1
    occupancy_pct = round((total_nights_booked / days_in_month) * 100) if days_in_month > 0 else 0
    avg_nightly = round(total_host_revenue / total_nights_booked, 2) if total_nights_booked > 0 else 0

    # Reviews
    review_html = ""
    if reviews:
        for rev in reviews[:5]:
            rating = rev.get("rating", 5)
            stars = "★" * int(rating) + "☆" * (5 - int(rating))
            body = (rev.get("body") or rev.get("public_review") or "")[:150]
            reviewer = rev.get("reviewer", {}).get("name", "Guest") if isinstance(rev.get("reviewer"), dict) else "Guest"
            if body:
                review_html += f'<p style="margin:4px 0;font-size:13px;"><span style="color:#d4a373;">{stars}</span> "{body}" <em style="color:#999;">&mdash; {reviewer}</em></p>'

    # What we did this month
    actions = []
    actions.append(f"{len(month_res)} guest check-in(s) coordinated")
    actions.append(f"{len(month_res)} post-clean inspection(s) completed")
    if pricing_changes:
        actions.append(f"Dynamic pricing adjusted {len(pricing_changes)}x")
    if reviews:
        five_star = sum(1 for rev in reviews if (rev.get("rating") or 5) >= 5)
        if five_star:
            actions.append(f"{five_star} five-star review(s) received")
    actions.append("Guest communication handled 24/7")

    # STR tracker
    str_html = ""
    if city.lower() in STR_LIMIT_CITIES and str_data:
        # Find matching property in tracker
        for tracker_name, tdata in str_data.items():
            if name.lower() in tracker_name.lower() or tracker_name.lower() in name.lower():
                str_html = f"""
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">STR Nights Used (YTD)</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{tdata['used']} used, {tdata['upcoming']} upcoming</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">180-Night Limit Remaining</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;font-weight:bold;color:{'#c0392b' if int(tdata.get('remaining', 180)) < 30 else '#27ae60'};">{tdata['remaining']} nights</td>
                </tr>"""
                break

    # Future bookings (next month)
    next_month_start = month_end + timedelta(days=1)
    next_month_end = date(next_month_start.year, next_month_start.month, monthrange(next_month_start.year, next_month_start.month)[1])
    future_count = 0
    future_revenue = 0
    for r in reservations:
        status = (r.get("status") or "").lower()
        if status in ("cancelled", "canceled", "denied"):
            continue
        ci_str = r.get("check_in") or r.get("arrival_date")
        if not ci_str:
            continue
        try:
            ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        if next_month_start <= ci <= next_month_end:
            future_count += 1

    # Build the HTML for this property
    html = f"""
    <div style="background:white;border:1px solid #e0e0e0;border-radius:8px;margin-bottom:30px;overflow:hidden;">
        <div style="background:#759b8f;padding:16px 24px;color:white;">
            <h2 style="margin:0;font-size:18px;">{name}</h2>
            <p style="margin:4px 0 0;opacity:0.9;font-size:13px;">Owner: {owner} | {month_name} | Commission: {split_str}</p>
        </div>
        <div style="padding:20px 24px;">

            <h3 style="color:#5a7d73;font-size:15px;margin:0 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">Revenue Summary</h3>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;">Gross Host Revenue</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;font-weight:bold;">${total_host_revenue:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;">Management Fee ({split_str})</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;color:#c0392b;">-${management_fee:,.2f}</td>
                </tr>
                <tr style="background:#f0faf6;">
                    <td style="padding:10px 8px;font-weight:bold;font-size:15px;">Owner Payout</td>
                    <td style="padding:10px 8px;text-align:right;font-weight:bold;font-size:15px;color:#27ae60;">${owner_payout:,.2f}</td>
                </tr>
            </table>

            <h3 style="color:#5a7d73;font-size:15px;margin:20px 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">Occupancy</h3>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;">Nights Booked</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{total_nights_booked} / {days_in_month} ({occupancy_pct}%)</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;">Average Nightly Rate</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">${avg_nightly:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding:8px;border-bottom:1px solid #eee;">Total Bookings</td>
                    <td style="padding:8px;border-bottom:1px solid #eee;text-align:right;">{len(month_res)} reservation(s)</td>
                </tr>
                {str_html}
            </table>"""

    # Booking details
    if booking_details:
        html += """
            <h3 style="color:#5a7d73;font-size:15px;margin:20px 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">Booking Details</h3>
            <table style="width:100%;border-collapse:collapse;font-size:13px;">
                <tr style="background:#f8f8f8;">
                    <th style="padding:6px 8px;text-align:left;">Guest</th>
                    <th style="padding:6px 8px;text-align:center;">Check-in</th>
                    <th style="padding:6px 8px;text-align:center;">Check-out</th>
                    <th style="padding:6px 8px;text-align:center;">Nights</th>
                    <th style="padding:6px 8px;text-align:right;">Revenue</th>
                </tr>"""
        for b in booking_details:
            html += f"""
                <tr>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;">{b['guest']}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">{b['check_in']}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">{b['check_out']}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:center;">{b['nights']}</td>
                    <td style="padding:6px 8px;border-bottom:1px solid #eee;text-align:right;">${b['revenue']:,.2f}</td>
                </tr>"""
        html += "</table>"

    # What we did
    html += """
            <h3 style="color:#5a7d73;font-size:15px;margin:20px 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">What We Did This Month</h3>
            <ul style="margin:0;padding-left:20px;font-size:14px;">"""
    for action in actions:
        html += f'<li style="margin:4px 0;color:#444;">{action}</li>'
    html += "</ul>"

    # Reviews
    if review_html:
        html += f"""
            <h3 style="color:#5a7d73;font-size:15px;margin:20px 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">Guest Reviews This Month</h3>
            {review_html}"""

    # Next month outlook
    if future_count > 0:
        html += f"""
            <h3 style="color:#5a7d73;font-size:15px;margin:20px 0 12px;border-bottom:2px solid #759b8f;padding-bottom:6px;">Next Month Outlook</h3>
            <p style="font-size:14px;color:#444;">{future_count} booking(s) already confirmed for {next_month_start.strftime('%B')}.</p>"""

    html += """
        </div>
    </div>"""

    return html, owner_payout, total_host_revenue, management_fee


# ================== MAIN ==================

def main(dry_run=False):
    now = datetime.now()
    # Use current month (the statement is for the current month, sent on last day)
    month_start = date(now.year, now.month, 1)
    month_end = date(now.year, now.month, monthrange(now.year, now.month)[1])
    month_name = month_start.strftime("%B %Y")

    print(f"Generating owner statements for {month_name}...")

    # Fetch all data
    properties = fetch_all_properties()
    print(f"  Found {len(properties)} properties")

    notion_data = fetch_property_notion_data()
    print(f"  Loaded {len(notion_data)} Notion entries")

    str_tracker = get_str_tracker_data()
    print(f"  Loaded {len(str_tracker)} STR tracker entries")

    # Build statements
    all_statements_html = ""
    total_portfolio_revenue = 0
    total_portfolio_commission = 0
    total_portfolio_payout = 0
    property_count = 0

    for prop in properties:
        if not prop.get("listed"):
            continue
        raw_name = (prop.get("name") or "").strip()
        if raw_name in ("", "·", "• ", "· ", " ·"):
            continue

        pid = prop.get("id")
        name = raw_name
        notion_entry = fuzzy_match_notion(name, notion_data)

        # Skip 0% commission properties (owner's own property)
        if notion_entry and notion_entry.get("commission") == 0:
            print(f"  Skipping {name} (0% commission, owner property)")
            continue

        print(f"  Processing: {name}")

        # Fetch reservations (wide window to catch overlapping stays)
        reservations = fetch_reservations(pid, month_start - timedelta(days=60), month_end + timedelta(days=60))

        # Fetch reviews
        reviews = fetch_reviews(pid, month_start, month_end)

        # Fetch calendar
        calendar = fetch_calendar(pid, month_start, month_end)

        # Get pricing changes
        pricing_changes = get_pricing_changes(name, month_start, month_end)

        # Build statement
        stmt_html, payout, revenue, commission = build_property_statement(
            prop, reservations, reviews, calendar, notion_entry, pricing_changes, str_tracker, month_start, month_end
        )

        all_statements_html += stmt_html
        total_portfolio_revenue += revenue
        total_portfolio_commission += commission
        total_portfolio_payout += payout
        property_count += 1

    # Build the full email
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f5f5f5;padding:20px;color:#333;">
<div style="max-width:800px;margin:0 auto;">

<div style="background:#759b8f;color:white;padding:24px 30px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:22px;">Monthly Owner Statements (DRAFT)</h1>
    <p style="margin:4px 0 0;opacity:0.9;font-size:14px;">{month_name} | {property_count} Properties</p>
</div>

<div style="background:#fff8e1;padding:16px 24px;border-left:4px solid #d4a373;margin-bottom:24px;">
    <p style="margin:0;font-size:14px;"><strong>This is a draft for internal review.</strong> Review each statement, add any personal notes or maintenance updates, then forward to each owner individually.</p>
</div>

<div style="background:white;border:1px solid #e0e0e0;border-radius:8px;padding:20px 24px;margin-bottom:24px;">
    <h3 style="color:#5a7d73;margin:0 0 12px;">Portfolio Summary</h3>
    <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr>
            <td style="padding:8px;">Total Properties</td>
            <td style="padding:8px;text-align:right;font-weight:bold;">{property_count}</td>
        </tr>
        <tr>
            <td style="padding:8px;">Total Host Revenue</td>
            <td style="padding:8px;text-align:right;font-weight:bold;">${total_portfolio_revenue:,.2f}</td>
        </tr>
        <tr>
            <td style="padding:8px;">Total Management Fees</td>
            <td style="padding:8px;text-align:right;font-weight:bold;color:#27ae60;">${total_portfolio_commission:,.2f}</td>
        </tr>
        <tr>
            <td style="padding:8px;">Total Owner Payouts</td>
            <td style="padding:8px;text-align:right;font-weight:bold;">${total_portfolio_payout:,.2f}</td>
        </tr>
    </table>
</div>

{all_statements_html}

<div style="padding:16px;text-align:center;font-size:12px;color:#999;">
    Generated by Nurture Owner Statement Bot | {datetime.now().strftime('%Y-%m-%d %H:%M')} ET
</div>

</div>
</body>
</html>"""

    # Text version
    text = f"Monthly Owner Statements (DRAFT) - {month_name}\n"
    text += f"{property_count} properties | Revenue: ${total_portfolio_revenue:,.2f} | Commission: ${total_portfolio_commission:,.2f}\n"
    text += "See HTML version for full details."

    if dry_run:
        print(f"\n[DRY RUN] Would send email with {property_count} property statements")
        print(f"  Portfolio revenue: ${total_portfolio_revenue:,.2f}")
        print(f"  Portfolio commission: ${total_portfolio_commission:,.2f}")
        print(f"  Portfolio payouts: ${total_portfolio_payout:,.2f}")
        # Write HTML to file for preview
        preview_path = os.path.join(SCRIPT_DIR, "owner-statement-preview.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Preview saved to {preview_path}")
        return

    # Send email
    subject = f"DRAFT: Monthly Owner Statements - {month_name}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(EMAIL_TO)
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())

    print(f"  Email sent to {', '.join(EMAIL_TO)}")
    print(f"  {property_count} property statements")
    print(f"  Portfolio commission: ${total_portfolio_commission:,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
