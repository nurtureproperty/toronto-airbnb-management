"""
Pricing Dashboard Sync (Google Sheets, header-aware)

Pulls data from Hospitable API for all properties and updates the Nurture
Pricing Dashboard Google Sheet. Uses header-name matching so the user can
rename, reorder, add, or remove columns without breaking the sync.

Columns are split into two categories:
  - Auto columns: written by the script (defined in AUTO_COLUMN_SPECS)
  - Manual columns: never touched (Min Price, BLT Benchmark, Minimum 30d Revenue,
    or any custom column the user adds)

Features:
  - Targeted cell updates (never clears/rewrites whole rows)
  - New Hospitable properties auto-appended
  - Archived Hospitable properties flagged with "⚠️ Archived" grade
  - Per-property commission pulled from Notion Properties DB for Host Payout
  - Change Log tab auto-populated on Base Price, Grade, Recommendation changes

Sheet: https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A

Usage:
  python scripts/update-pricing-dashboard.py             # Normal run
  python scripts/update-pricing-dashboard.py --dry-run   # Preview only

Scheduled: Daily at 7:00 AM via Windows Task Scheduler (NurturePricingDashboardSync)
"""

import os
import sys
import time
import logging
import argparse
import re
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

SHEET_ID = "1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
DASHBOARD_TAB = "Dashboard"
CHANGELOG_TAB = "Change Log"

HOSPITABLE_TOKEN = os.getenv("HOSPITABLE_API_TOKEN")
HOSPITABLE_API = "https://public.api.hospitable.com/v2"
HOSP_HEADERS = {"Authorization": f"Bearer {HOSPITABLE_TOKEN}"}

GSHEETS_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
GSHEETS_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
GSHEETS_REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
PROPERTIES_DB_ID = "2d509a91-8762-8030-bd0b-d64efe777f87"

LOG_FILE = os.path.join(SCRIPT_DIR, "update-pricing-dashboard-log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ================== FORMATTERS ==================

def format_currency(val):
    return f"${val:.2f}" if val is not None else ""


def format_percent(val):
    return f"{val*100:.0f}%" if val is not None else ""


def col_letter(idx):
    """0-indexed column to A1 letter."""
    result = ""
    n = idx
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


# ================== COLUMN SPECS ==================

AUTO_COLUMN_SPECS = [
    ("Property", ["Property"], lambda m: m["name"]),
    ("Homeowner", ["Homeowner"], lambda m: m.get("homeowner", "")),
    ("Hospitable ID", ["Hospitable ID", "ID", "Listing ID"], lambda m: str(m["hospitable_id"])),
    # Base Price — MANUAL (bold column, Nina updates from Airbnb Insights)
    # Nightly rate (last 30 day) — MANUAL (bold column, Nina updates from Airbnb Insights)
    # BLT Short-Term — MANUAL (bold column, Nina updates from Airbnb Insights monthly)
    # Suggested Base — REMOVED (65% of calendar avg was misleading for existing properties)
    # BLT Short-Term removed from auto — now manual column (see comment above)
    # BLT Mid-Term — REMOVED (not useful for weekly pricing decisions)
    ("Target Occ at BLT", ["Target Occ at BLT", "Target Occupancy"], lambda m: format_percent(m.get("target_occ"))),
    ("Occ at BLT (forward)", ["Occ at BLT (forward)", "Occ at BLT"], lambda m: format_percent(m.get("occ_blt"))),
    ("Grade", ["Grade"], lambda m: m.get("grade", "")),
    ("Occ Last 30d", ["Occ Last 30d"], lambda m: format_percent(m.get("occupancy_last_30d"))),
    ("Occ 15d", ["Occ 15d"], lambda m: format_percent(m.get("occupancy_15d"))),
    ("Occ 30d", ["Occ 30d"], lambda m: format_percent(m.get("occupancy_30d"))),
    ("Occ 60d", ["Occ 60d"], lambda m: format_percent(m.get("occupancy_60d"))),
    ("Host Payout Last 30d", ["Host Payout Last 30d", "Revenue Last 30d"], lambda m: format_currency(m.get("revenue_30d"))),
    ("Recommendation", ["Recommendation"], lambda m: m.get("recommendation", "")),
    ("Smart Recommendation", ["Smart Recommendation"], lambda m: m.get("smart_recommendation", "")),
]

BLT_BENCHMARK_ALIASES = ["BLT Benchmark", "BLT Benchmark (days)"]
HOSPITABLE_ID_ALIASES = ["Hospitable ID", "ID", "Listing ID"]
TRACKED_CHANGE_FIELDS = ["Grade", "Recommendation"]


def build_auto_columns_for_headers(headers):
    result = {}
    header_set = set(headers)
    for canonical, aliases, fn in AUTO_COLUMN_SPECS:
        for alias in aliases:
            if alias in header_set:
                result[alias] = fn
                break
    return result


# ================== SHEETS HELPERS ==================

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
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_a1}"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        log.error(f"Sheets read error: {r.status_code} {r.text[:200]}")
        return []
    return r.json().get("values", [])


def sheets_batch_update_values(updates):
    if not updates:
        return True
    token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate"
    body = {
        "valueInputOption": "USER_ENTERED",
        "data": [{"range": rng, "values": vals} for rng, vals in updates],
    }
    r = requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=body)
    if r.status_code != 200:
        log.error(f"Batch update error: {r.status_code} {r.text[:400]}")
        return False
    return True


def sheets_append_rows(tab, values):
    token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{tab}!A:ZZ:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"values": values},
    )
    if r.status_code != 200:
        log.error(f"Sheets append error: {r.status_code} {r.text[:300]}")
        return False
    return True


def read_dashboard_with_headers():
    data = sheets_get_values(f"{DASHBOARD_TAB}!A1:ZZ500")
    if not data:
        return [], {}
    headers = data[0]
    id_col = next((a for a in HOSPITABLE_ID_ALIASES if a in headers), None)
    rows_by_id = {}
    for row_idx, row in enumerate(data[1:], start=2):
        padded = row + [""] * (len(headers) - len(row))
        row_dict = dict(zip(headers, padded))
        hid = (row_dict.get(id_col, "") if id_col else "").strip()
        if hid:
            row_dict["_row_number"] = row_idx
            rows_by_id[hid] = row_dict
    return headers, rows_by_id


# ================== HOSPITABLE HELPERS ==================

def hosp_get(path, params=None):
    url = f"{HOSPITABLE_API}{path}"
    r = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if r.status_code != 200:
        log.error(f"Hospitable error {r.status_code} on {path}: {r.text[:200]}")
        return None
    time.sleep(0.15)
    return r.json()


def fetch_all_properties():
    all_props = []
    page = 1
    while True:
        data = hosp_get("/properties", {"page": page, "per_page": 50})
        if not data:
            break
        all_props.extend(data.get("data", []))
        meta = data.get("meta", {})
        if page >= meta.get("last_page", 1):
            break
        page += 1
    return all_props


def fetch_property_calendar(property_id, start_date, end_date):
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
        meta = data.get("meta", {})
        if page >= meta.get("last_page", 1):
            break
        page += 1
    return all_res


# ================== NOTION LOOKUP (owner + commission) ==================

def fetch_property_notion_data():
    """Returns {notion_property_name: {'owner': str, 'commission': float or None}}."""
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
                mapping[pname] = {"owner": owner, "commission": commission}
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return mapping


def _fuzzy_match_notion(prop_name, notion_data):
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


def lookup_homeowner(prop_name, notion_data):
    entry = _fuzzy_match_notion(prop_name, notion_data)
    return (entry or {}).get("owner", "")


def lookup_commission(prop_name, notion_data):
    entry = _fuzzy_match_notion(prop_name, notion_data)
    return (entry or {}).get("commission")


# ================== GRADING ==================

def compute_target_occupancy(blt_days):
    return 0.50


def compute_grade(occ_at_blt, target_occ):
    if occ_at_blt is None or target_occ is None or target_occ == 0:
        return "⚪ No Data", "Insufficient data to grade", None
    diff_pct = (occ_at_blt - target_occ) * 100
    if diff_pct >= 15:
        return "⚪ Priced Too Low", "Raise base +5%: running ahead of target", "+5%"
    if diff_pct > -10:
        return "🟢 Good Occupancy", "On target, no change needed", "0%"
    if diff_pct >= -20:
        return "🟡 Slightly Under", "Lower base 5%: slightly under target", "-5%"
    return "🔴 Needs Optimizing", "Lower base 10% or reoptimize listing", "-10%"


def build_smart_recommendation(m):
    occ_blt = m.get("occ_blt")
    target = m.get("target_occ") or 0.5
    occ15 = m.get("occupancy_15d")
    occ30 = m.get("occupancy_30d")
    occ60 = m.get("occupancy_60d")
    last30 = m.get("occupancy_last_30d")
    blt_short = m.get("blt_short")
    blt_mid = m.get("blt_mid")

    if occ_blt is None:
        return "Need more data: fewer than 5 recent bookings"

    diff = (occ_blt - target) * 100
    parts = []

    if diff >= 15:
        parts.append(f"Raise base +5-10%. Booked {occ_blt*100:.0f}% at BLT vs {target*100:.0f}% target.")
    elif diff >= -10:
        parts.append(f"Hold base. On target at {occ_blt*100:.0f}%.")
    elif diff >= -20:
        parts.append(f"Lower base 5%. {occ_blt*100:.0f}% vs {target*100:.0f}% target.")
    else:
        parts.append(f"Lower 10% or reoptimize. Only {occ_blt*100:.0f}% vs {target*100:.0f}% target.")

    if occ15 is not None and occ30 is not None and occ60 is not None:
        if occ60 > occ30 + 0.05 or occ60 > occ15 + 0.05:
            parts.append("Far-out premium too low, raise 5%.")

    if blt_short and blt_short > 30 and occ15 is not None and occ15 < 0.3:
        parts.append("Short-term BLT > 30d but 15d empty: event-driven, last-minute weak.")

    if blt_mid and blt_mid > 60 and (blt_short is None or blt_short < 20):
        parts.append("Mid-term books 60+ days out, short-term is last-minute.")

    if last30 is not None and occ30 is not None:
        gap = last30 - occ30
        if gap > 0.40:
            parts.append(f"Sharp drop: last 30d {last30*100:.0f}% vs next 30d {occ30*100:.0f}%.")
        elif gap < -0.25:
            parts.append(f"Momentum: next 30d ({occ30*100:.0f}%) stronger than last 30d.")

    if occ_blt is not None and occ_blt == 0 and occ30 == 0:
        parts.append("Zero forward bookings: urgent listing optimization needed.")

    if occ60 is not None and occ60 < 0.10 and occ30 is not None and occ30 > 0.30:
        parts.append("60d calendar mostly empty, far-out price too high.")

    return " ".join(parts)[:400]


# ================== METRIC CALCULATION ==================

def calculate_metrics(prop, notion_data, blt_benchmark_days=None):
    pid = prop.get("id")
    name = prop.get("name") or prop.get("address", {}).get("display") or f"Property {pid}"
    today = date.today()

    commission = lookup_commission(name, notion_data)
    if commission is None:
        commission = 0.15

    result = {
        "hospitable_id": pid,
        "name": name,
        "homeowner": lookup_homeowner(name, notion_data),
        "commission_rate": commission,
    }

    res_start = today - timedelta(days=180)
    res_end = today + timedelta(days=90)
    reservations = fetch_reservations(pid, res_start, res_end)

    blts_st = []
    blts_mt = []
    revenue_30d = 0

    for r in reservations:
        try:
            ci_str = r.get("check_in") or r.get("arrival_date")
            co_str = r.get("check_out") or r.get("departure_date")
            booked_str = r.get("booking_date") or r.get("reservation_date") or r.get("booked_at") or r.get("created_at")
            if not ci_str or not booked_str:
                continue
            ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
            booked = datetime.fromisoformat(booked_str.replace("Z", "+00:00")).date()

            res_status = (r.get("status") or "").lower()
            is_cancelled = res_status in ("cancelled", "canceled")

            if not is_cancelled and booked >= today - timedelta(days=90):
                lead = (ci - booked).days
                nights = r.get("nights") or 0
                if not nights and co_str:
                    try:
                        co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()
                        nights = (co - ci).days
                    except (ValueError, TypeError):
                        nights = 0
                if 0 <= lead <= 365:
                    if nights >= 28:
                        blts_mt.append(lead)
                    else:
                        blts_st.append(lead)

            window_start = today - timedelta(days=30)
            window_end = today
            if co_str:
                try:
                    co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()
                except (ValueError, TypeError):
                    co = ci + timedelta(days=r.get("nights") or 1)
            else:
                co = ci + timedelta(days=r.get("nights") or 1)

            overlap_start = max(ci, window_start)
            overlap_end = min(co, window_end)
            overlap_nights = (overlap_end - overlap_start).days
            if overlap_nights > 0 and not is_cancelled:
                fin = r.get("financials", {}) or {}
                host = fin.get("host", {}) if isinstance(fin, dict) else {}
                revenue_obj = host.get("revenue", {}) if isinstance(host, dict) else {}
                raw = revenue_obj.get("amount", 0) if isinstance(revenue_obj, dict) else 0
                try:
                    total_rev = float(raw or 0) / 100
                except (ValueError, TypeError):
                    total_rev = 0
                total_nights = (co - ci).days or 1
                client_share = total_rev * (1 - commission)
                revenue_30d += client_share * (overlap_nights / total_nights)
        except Exception as e:
            log.warning(f"Reservation parse error for {name}: {e}")

    result["blt_short"] = round(sum(blts_st) / len(blts_st)) if len(blts_st) >= 5 else None
    result["blt_mid"] = round(sum(blts_mt) / len(blts_mt)) if len(blts_mt) >= 2 else None
    result["revenue_30d"] = revenue_30d

    # Calculate actual booked nightly rate (last 30 days)
    # Uses host.accommodation (gross nightly rate before Airbnb fees/discounts)
    # to match Airbnb Insights benchmark which shows gross accommodation rate
    gross_accom_30d = 0
    booked_nights_30d = 0
    rate_window_start = today - timedelta(days=30)
    rate_window_end = today
    for r in reservations:
        try:
            res_status = (r.get("status") or "").lower()
            if res_status in ("cancelled", "canceled"):
                continue
            ci_str = r.get("check_in") or r.get("arrival_date")
            co_str = r.get("check_out") or r.get("departure_date")
            if not ci_str or not co_str:
                continue
            ci = datetime.fromisoformat(ci_str.replace("Z", "+00:00")).date()
            co = datetime.fromisoformat(co_str.replace("Z", "+00:00")).date()
            overlap_start = max(ci, rate_window_start)
            overlap_end = min(co, rate_window_end)
            overlap_nights = (overlap_end - overlap_start).days
            if overlap_nights <= 0:
                continue
            fin = r.get("financials", {}) or {}
            host = fin.get("host", {}) if isinstance(fin, dict) else {}
            # Use accommodation_breakdown for exact per-night rates when available
            breakdown = host.get("accommodation_breakdown", [])
            if breakdown:
                for day_entry in breakdown:
                    label = day_entry.get("label", "")
                    try:
                        day_date = datetime.fromisoformat(label).date()
                    except (ValueError, TypeError):
                        continue
                    if rate_window_start <= day_date < rate_window_end:
                        amt = day_entry.get("amount", 0)
                        try:
                            gross_accom_30d += float(amt) / 100
                            booked_nights_30d += 1
                        except (ValueError, TypeError):
                            pass
            else:
                # Fallback: use total accommodation / nights
                accom_obj = host.get("accommodation", {}) if isinstance(host, dict) else {}
                raw = accom_obj.get("amount", 0) if isinstance(accom_obj, dict) else 0
                try:
                    total_accom = float(raw or 0) / 100
                except (ValueError, TypeError):
                    total_accom = 0
                total_nights = (co - ci).days or 1
                nightly = total_accom / total_nights
                gross_accom_30d += nightly * overlap_nights
                booked_nights_30d += overlap_nights
        except Exception:
            pass
    result["actual_nightly_rate_30d"] = (gross_accom_30d / booked_nights_30d) if booked_nights_30d > 0 else None

    blt_window = blt_benchmark_days or result["blt_short"] or 15
    cal_end = today + timedelta(days=max(blt_window + 10, 60))
    calendar = fetch_property_calendar(pid, today, cal_end)

    booked_blt = total_blt = 0
    booked_15 = total_15 = 0
    booked_30 = total_30 = 0
    booked_60 = total_60 = 0
    rates_30 = []
    rates_60 = []

    for day in calendar:
        d_str = day.get("date")
        if not d_str:
            continue
        try:
            d = datetime.fromisoformat(d_str).date()
        except ValueError:
            continue

        days_out = (d - today).days
        status = day.get("status", {}) if isinstance(day.get("status"), dict) else {}
        reason = (status.get("reason") or "").upper()
        # Skip owner-blocked days entirely (not available, not a guest booking)
        # Only count RESERVED (guest booked) and AVAILABLE in occupancy calc
        if reason == "BLOCKED":
            continue
        is_booked = reason == "RESERVED"
        price_obj = day.get("price")
        if isinstance(price_obj, dict):
            raw_price = price_obj.get("amount")
            price = raw_price / 100 if raw_price else None
        else:
            price = price_obj

        if days_out < blt_window:
            total_blt += 1
            if is_booked:
                booked_blt += 1
        if days_out < 15:
            total_15 += 1
            if is_booked:
                booked_15 += 1
        if days_out < 30:
            total_30 += 1
            if is_booked:
                booked_30 += 1
            if price is not None:
                try:
                    rates_30.append(float(price))
                except (ValueError, TypeError):
                    pass
        if days_out < 60:
            total_60 += 1
            if is_booked:
                booked_60 += 1
            if price is not None:
                try:
                    rates_60.append(float(price))
                except (ValueError, TypeError):
                    pass

    result["occ_blt"] = (booked_blt / total_blt) if total_blt else None
    result["occupancy_15d"] = (booked_15 / total_15) if total_15 else None
    result["occupancy_30d"] = (booked_30 / total_30) if total_30 else None
    result["occupancy_60d"] = (booked_60 / total_60) if total_60 else None
    result["avg_rate_30d"] = (sum(rates_30) / len(rates_30)) if rates_30 else None
    result["suggested_base"] = result["avg_rate_30d"] * 0.65 if result["avg_rate_30d"] else None
    result["base_price"] = result["avg_rate_30d"]

    hist_start = today - timedelta(days=30)
    hist_cal = fetch_property_calendar(pid, hist_start, today - timedelta(days=1))
    hist_booked = hist_total = 0
    for day in hist_cal:
        st = day.get("status", {}) if isinstance(day.get("status"), dict) else {}
        reason = (st.get("reason") or "").upper()
        if reason == "BLOCKED":
            continue  # Skip owner-blocked days
        if reason == "RESERVED":
            hist_booked += 1
        hist_total += 1
    result["occupancy_last_30d"] = (hist_booked / hist_total) if hist_total else None

    target_occ = compute_target_occupancy(result["blt_short"])
    grade, rec, _ = compute_grade(result["occ_blt"], target_occ)
    result["target_occ"] = target_occ
    result["grade"] = grade
    result["recommendation"] = rec
    result["smart_recommendation"] = build_smart_recommendation(result)

    return result


def detect_changes_by_name(old_row_dict, new_values_by_header, property_name):
    """Detect changes in tracked fields and capture grade/occupancy snapshot.

    Returns list of 12-column rows for Change Log tab:
    Date, Property, Field, From, To, Reason, Changed By,
    Grade at Change, Occ BLT at Change, Grade 7d Later, Occ BLT 7d Later, Outcome
    """
    changes = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    # Snapshot the NEW values (what the change is moving TO)
    grade_snapshot = (new_values_by_header.get("Grade") or "").strip()
    occ_snapshot = (new_values_by_header.get("Occ at BLT (forward)") or "").strip()

    for field in TRACKED_CHANGE_FIELDS:
        old_val = (old_row_dict.get(field) or "").strip()
        new_val = (new_values_by_header.get(field) or "").strip()
        if old_val != new_val and (old_val or new_val):
            changes.append([
                today_str,             # Date
                property_name,          # Property
                field,                  # Field
                old_val,                # From
                new_val,                # To
                "Auto-detected",        # Reason
                "System",               # Changed By
                grade_snapshot,         # Grade at Change
                occ_snapshot,           # Occ BLT at Change
                "",                     # Grade 7d Later (filled by audit script)
                "",                     # Occ BLT 7d Later (filled by audit script)
                "",                     # Outcome (filled by audit script)
            ])
    return changes


# ================== MAIN ==================

def main(dry_run=False):
    log.info("=" * 60)
    log.info(f"Pricing Dashboard sync starting at {datetime.now()}")
    log.info("=" * 60)

    headers, existing_by_id = read_dashboard_with_headers()
    log.info(f"Existing rows: {len(existing_by_id)}")

    if not headers:
        log.error("Dashboard has no headers, aborting")
        return

    header_to_col = {h: col_letter(i) for i, h in enumerate(headers)}
    auto_columns = build_auto_columns_for_headers(headers)
    log.info(f"Auto columns matched: {list(auto_columns.keys())}")

    properties = fetch_all_properties()
    log.info(f"Fetched {len(properties)} properties from Hospitable")
    notion_data = fetch_property_notion_data()
    log.info(f"Loaded {len(notion_data)} Notion property entries")

    updates = []
    new_rows_to_append = []
    all_changes = []
    matched_hids = set()

    for prop in properties:
        name = prop.get("name") or f"Property {prop.get('id')}"

        if prop.get("listed") is False:
            log.info(f"Skipping unlisted: {name}")
            continue
        stripped = (prop.get("name") or "").strip()
        if stripped in ("", "·", "• ", "· ", " ·") and not prop.get("platforms"):
            log.info(f"Skipping placeholder: {name}")
            continue

        log.info(f"Processing: {name}")
        try:
            pid = str(prop.get("id"))
            existing_row = existing_by_id.get(pid)

            benchmark_days = None
            if existing_row:
                for alias in BLT_BENCHMARK_ALIASES:
                    bench_str = (existing_row.get(alias) or "").strip()
                    if bench_str:
                        cleaned = bench_str.replace("%", "").replace("$", "").replace(",", "").strip()
                        try:
                            val = float(cleaned)
                            if "%" in bench_str and val >= 100:
                                val = val / 100
                            benchmark_days = int(val)
                            break
                        except (ValueError, TypeError):
                            pass

            metrics = calculate_metrics(prop, notion_data, blt_benchmark_days=benchmark_days)
            new_values = {h: fn(metrics) for h, fn in auto_columns.items()}

            if existing_row:
                matched_hids.add(pid)
                row_num = existing_row["_row_number"]
                for header, value in new_values.items():
                    col = header_to_col[header]
                    updates.append((f"{DASHBOARD_TAB}!{col}{row_num}", [[value]]))
                all_changes.extend(detect_changes_by_name(existing_row, new_values, metrics["name"]))
            else:
                full_row = [new_values.get(h, "") for h in headers]
                new_rows_to_append.append(full_row)
                log.info(f"  NEW property detected, will append row")

        except Exception as e:
            log.error(f"Error processing {name}: {e}", exc_info=True)

    # Flag archived properties: rows in the sheet NOT matched to any live Hospitable property
    archived_updates = []
    if "Grade" in header_to_col:
        grade_col = header_to_col["Grade"]
        for hid, row in existing_by_id.items():
            if hid in matched_hids:
                continue
            current_grade = (row.get("Grade") or "").strip()
            if "Archived" in current_grade:
                continue
            row_num = row["_row_number"]
            archived_updates.append((f"{DASHBOARD_TAB}!{grade_col}{row_num}", [["⚠️ Archived in Hospitable"]]))
            log.info(f"  ARCHIVED: {row.get('Property', hid)}")

    if dry_run:
        log.info(f"[DRY RUN] Would update {len(updates)} cells, append {len(new_rows_to_append)} new rows, flag {len(archived_updates)} archived, log {len(all_changes)} changes")
        return

    if updates:
        sheets_batch_update_values(updates)
        log.info(f"Updated {len(updates)} cells across {len(matched_hids)} properties")

    if new_rows_to_append:
        sheets_append_rows(DASHBOARD_TAB, new_rows_to_append)
        log.info(f"Appended {len(new_rows_to_append)} new property rows")

    if archived_updates:
        sheets_batch_update_values(archived_updates)
        log.info(f"Flagged {len(archived_updates)} archived properties")

    if all_changes:
        sheets_append_rows(CHANGELOG_TAB, all_changes)
        log.info(f"Logged {len(all_changes)} changes")

    log.info("Sync complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
