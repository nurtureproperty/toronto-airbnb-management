"""
Pricing Change Log Audit

Reviews the Pricing Dashboard Change Log and measures the impact of each
base price and grade change 7-14 days after it was made. Classifies each
change as Win, Neutral, or Miss, and updates the Change Log tab with the
results. Posts a Friday morning Slack summary for the team.

Logic:
  - For each change where Grade 7d Later is blank AND the change is 7-14 days old:
    - Look up current Grade and Occ at BLT from the Dashboard tab
    - Write those into the audit columns
    - Classify the outcome

Outcome classification:
  - Base Price DROP → Grade improved (less red): WIN
  - Base Price DROP → Grade worsened or unchanged at red: MISS
  - Base Price RAISE → Grade stayed green/good: WIN
  - Base Price RAISE → Grade dropped to red: MISS
  - Grade change from red → green: WIN (regardless of price direction)
  - Grade change from green → red: MISS
  - Anything else: NEUTRAL

Usage:
  python scripts/pricing-change-audit.py              # Normal run
  python scripts/pricing-change-audit.py --dry-run    # Preview only

Scheduled: Friday mornings at 7:15 AM via Windows Task Scheduler
"""

import os
import sys
import logging
import argparse
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

GSHEETS_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
GSHEETS_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
GSHEETS_REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID", "C0AG2CHB55J")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
PRICING_PERF_DB_ID = "33909a91-8762-81f1-ba85-cad5ebf9fefd"

LOG_FILE = os.path.join(SCRIPT_DIR, "pricing-change-audit-log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def get_sheets_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": GSHEETS_CLIENT_ID,
        "client_secret": GSHEETS_CLIENT_SECRET,
        "refresh_token": GSHEETS_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    return r.json()["access_token"]


def sheets_get(range_a1):
    token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{range_a1}"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        log.error(f"Sheets read error: {r.status_code}")
        return []
    return r.json().get("values", [])


def sheets_batch_update(updates):
    if not updates:
        return True
    token = get_sheets_access_token()
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values:batchUpdate"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "valueInputOption": "USER_ENTERED",
            "data": [{"range": rng, "values": vals} for rng, vals in updates],
        },
    )
    if r.status_code != 200:
        log.error(f"Batch update error: {r.status_code} {r.text[:300]}")
        return False
    return True


def parse_percent(s):
    if not s:
        return None
    s = str(s).replace("%", "").strip()
    try:
        return float(s) / 100
    except (ValueError, TypeError):
        return None


def grade_category(grade_text):
    """Reduce grade to a simple category: red, yellow, green, over, archived, unknown."""
    if not grade_text:
        return "unknown"
    g = grade_text.lower()
    if "archived" in g or "⚠️" in grade_text:
        return "archived"
    if "red" in g or "🔴" in grade_text or "needs" in g:
        return "red"
    if "yellow" in g or "🟡" in grade_text or "slightly under" in g:
        return "yellow"
    if "green" in g or "🟢" in grade_text or "good" in g:
        return "green"
    if "over" in g or "⚪" in grade_text or "priced too low" in g:
        return "over"
    return "unknown"


def classify_outcome(field, from_val, to_val, grade_at_change, grade_now, occ_at_change, occ_now):
    """Classify a change as Win / Neutral / Miss."""
    cat_before = grade_category(grade_at_change)
    cat_after = grade_category(grade_now)

    # If we don't have both snapshots, can't classify
    if cat_before == "unknown" or cat_after == "unknown" or cat_after == "archived":
        return "Neutral"

    # Grade field changes: directly classify by improvement
    if field == "Grade":
        # Moving toward green is a win, away is a miss
        rank = {"red": 0, "yellow": 1, "green": 3, "over": 2, "archived": -1, "unknown": -1}
        if rank.get(cat_after, -1) > rank.get(cat_before, -1):
            return "Win"
        if rank.get(cat_after, -1) < rank.get(cat_before, -1):
            return "Miss"
        return "Neutral"

    # Base Price changes: infer direction
    if field == "Base Price":
        def to_num(v):
            try:
                return float(str(v).replace("$", "").replace(",", "").strip())
            except (ValueError, TypeError):
                return None
        old_num = to_num(from_val)
        new_num = to_num(to_val)
        if old_num is None or new_num is None:
            return "Neutral"
        raised = new_num > old_num
        lowered = new_num < old_num

        # Price lowered (trying to fix underperformance)
        if lowered:
            if cat_before == "red" and cat_after in ("yellow", "green"):
                return "Win"
            if cat_before == "yellow" and cat_after == "green":
                return "Win"
            if cat_before == "red" and cat_after == "red":
                return "Miss"  # Price wasn't the answer, should reoptimize
            return "Neutral"

        # Price raised (trying to capture more revenue)
        if raised:
            if cat_before in ("over", "green") and cat_after in ("over", "green"):
                return "Win"  # Successfully captured revenue without dropping
            if cat_before in ("over", "green") and cat_after in ("yellow", "red"):
                return "Miss"  # Raised too aggressively
            return "Neutral"

    return "Neutral"


def fetch_current_dashboard_state():
    """Returns {property_name: {'grade': str, 'occ_blt': str}} from Dashboard tab."""
    data = sheets_get(f"{DASHBOARD_TAB}!A1:V500")
    if not data:
        return {}
    headers = data[0]
    name_idx = headers.index("Property") if "Property" in headers else 0
    grade_idx = headers.index("Grade") if "Grade" in headers else None
    occ_idx = headers.index("Occ at BLT (forward)") if "Occ at BLT (forward)" in headers else None
    if grade_idx is None or occ_idx is None:
        log.error("Dashboard missing required columns")
        return {}
    state = {}
    for row in data[1:]:
        padded = row + [""] * (len(headers) - len(row))
        state[padded[name_idx].strip()] = {
            "grade": padded[grade_idx].strip(),
            "occ_blt": padded[occ_idx].strip(),
        }
    return state


def slack_notify(message):
    if not SLACK_TOKEN:
        return
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "text": message, "unfurl_links": False},
    )


def notion_create_performance_row(week_ending, scope, property_name, wins, neutral, misses, notes=""):
    """Create a row in the Notion Pricing Performance DB."""
    if not NOTION_TOKEN:
        return
    total = wins + neutral + misses
    decisive = wins + misses
    accuracy = (wins / decisive) if decisive > 0 else None
    props = {
        "Week Ending": {"title": [{"text": {"content": week_ending}}]},
        "Property": {"rich_text": [{"text": {"content": property_name}}]},
        "Scope": {"select": {"name": scope}},
        "Wins": {"number": wins},
        "Neutral": {"number": neutral},
        "Misses": {"number": misses},
        "Total Changes": {"number": total},
    }
    if accuracy is not None:
        props["Accuracy %"] = {"number": accuracy}
    if notes:
        props["Notes"] = {"rich_text": [{"text": {"content": notes[:1900]}}]}

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={"parent": {"database_id": PRICING_PERF_DB_ID}, "properties": props},
    )
    if r.status_code != 200:
        log.error(f"Notion perf row error: {r.status_code} {r.text[:200]}")


def main(dry_run=False):
    log.info("=" * 60)
    log.info(f"Pricing Change Log audit at {datetime.now()}")
    log.info("=" * 60)

    rows = sheets_get(f"{CHANGELOG_TAB}!A1:L1000")
    if not rows or len(rows) < 2:
        log.info("No change log entries to audit")
        return

    current_state = fetch_current_dashboard_state()
    log.info(f"Loaded {len(current_state)} current dashboard rows")

    today = date.today()
    updates = []
    audited_count = 0
    wins = 0
    misses = 0
    neutral = 0
    property_stats = {}  # {property_name: {"wins": n, "misses": n, "neutral": n}}

    for i, row in enumerate(rows[1:], start=2):  # sheet rows start at 2
        padded = row + [""] * (12 - len(row))
        (date_str, prop, field, from_val, to_val, reason, by,
         grade_at, occ_at, grade_later, occ_later, outcome) = padded[:12]

        # Skip rows already audited
        if outcome:
            continue

        # Skip rows without a valid date
        try:
            change_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        age_days = (today - change_date).days
        if age_days < 7:
            continue  # Too recent to measure
        if age_days > 30:
            continue  # Too old, don't retroactively audit

        # Only audit changes we can measure meaningfully
        if field not in ("Base Price", "Grade"):
            continue

        # Look up current state for this property
        current = current_state.get(prop.strip())
        if not current:
            log.info(f"  Row {i}: property '{prop}' not in dashboard (archived?)")
            continue

        grade_now = current["grade"]
        occ_now = current["occ_blt"]

        outcome = classify_outcome(field, from_val, to_val, grade_at, grade_now, occ_at, occ_now)

        # Write back to sheet columns J, K, L (Grade 7d Later, Occ BLT 7d Later, Outcome)
        updates.append((f"{CHANGELOG_TAB}!J{i}:L{i}", [[grade_now, occ_now, outcome]]))
        audited_count += 1

        # Tally stats
        if outcome == "Win":
            wins += 1
        elif outcome == "Miss":
            misses += 1
        else:
            neutral += 1

        prop_key = prop.strip()
        if prop_key not in property_stats:
            property_stats[prop_key] = {"wins": 0, "misses": 0, "neutral": 0}
        if outcome == "Win":
            property_stats[prop_key]["wins"] += 1
        elif outcome == "Miss":
            property_stats[prop_key]["misses"] += 1
        else:
            property_stats[prop_key]["neutral"] += 1

        log.info(f"  {prop}: {field} {from_val} → {to_val}, {outcome}")

    if dry_run:
        log.info(f"[DRY RUN] Would audit {audited_count} changes: {wins} wins, {neutral} neutral, {misses} misses")
        return

    if updates:
        sheets_batch_update(updates)
        log.info(f"Updated {len(updates)} change log rows")

    # Write performance rows to Notion (one team total + one per property)
    if audited_count > 0:
        week_ending = today.strftime("%Y-%m-%d")
        # Team total
        notion_create_performance_row(
            week_ending=week_ending,
            scope="Team Total",
            property_name="All Properties",
            wins=wins,
            neutral=neutral,
            misses=misses,
            notes=f"Week of {(today - timedelta(days=7)).strftime('%b %d')} to {today.strftime('%b %d')}",
        )
        # Per property
        for prop_name, stats in property_stats.items():
            notion_create_performance_row(
                week_ending=week_ending,
                scope="Per Property",
                property_name=prop_name,
                wins=stats["wins"],
                neutral=stats["neutral"],
                misses=stats["misses"],
            )
        log.info(f"Wrote {1 + len(property_stats)} rows to Notion Pricing Performance DB")

    # Build Slack summary
    if audited_count > 0:
        summary_lines = [
            "*Pricing Change Log Audit — Weekly Results*",
            f"Audited *{audited_count}* changes from 7-14 days ago",
            f"• :white_check_mark: Wins: *{wins}*",
            f"• :large_yellow_circle: Neutral: *{neutral}*",
            f"• :x: Misses: *{misses}*",
        ]
        if wins + misses > 0:
            accuracy = (wins / (wins + misses)) * 100
            summary_lines.append(f"Accuracy (wins / decisive): *{accuracy:.0f}%*")
        summary_lines.append(f"\nSee Change Log tab for details: https://docs.google.com/spreadsheets/d/{SHEET_ID}")
        slack_notify("\n".join(summary_lines))
        log.info("Slack summary sent")

    log.info(f"Audit complete: {audited_count} rows audited")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
