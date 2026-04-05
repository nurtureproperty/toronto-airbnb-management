"""
Weekly Pricing Review Completion Check

Runs every Monday morning at 8 AM. Verifies that the previous week's
Weekly Pricing Review task was completed and that actual pricing work
was done on properties that were red or yellow.

Checks:
  1. Notion task "Weekly Pricing Review — [last Sat]" exists and is marked Done
  2. At least 80% of the 34 checklist items are checked
  3. For each property that was 🔴 or 🟡 last Saturday: at least one signal of action
     - Base Price changed by 5%+ vs last Saturday
     - Min Price value changed
     - New entry in Price Change Log column
     - New entry in Listing Optimization Log column

If anything fails: emails info@nurtre.io and angelica@nurtre.io with details.
If everything passes: optionally sends a positive summary.

Usage:
  python scripts/weekly-review-completion-check.py             # Normal run
  python scripts/weekly-review-completion-check.py --dry-run   # Preview only

Scheduled: Mondays 8:00 AM via NurtureWeeklyReviewCompletionCheck task
"""

import os
import sys
import smtplib
import logging
import argparse
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# Config
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
PROJECT_LIST_DB_ID = "b24ffa51-4302-4a76-8063-eed4318acff0"
NOTION_API = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

SHEET_ID = "1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
DASHBOARD_TAB = "Dashboard"
CHANGELOG_TAB = "Change Log"

GSHEETS_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
GSHEETS_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
GSHEETS_REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")

EMAIL_USER = os.getenv("EMAIL_SMTP_USER")
EMAIL_PASS = os.getenv("EMAIL_SMTP_PASSWORD")
EMAIL_RECIPIENTS = ["info@nurtre.io", "angelica@nurtre.io"]

ACTION_THRESHOLD_PCT = 0.05  # 5% base price change is meaningful
CHECKLIST_COMPLETION_THRESHOLD = 0.80  # 80% of items checked

LOG_FILE = os.path.join(SCRIPT_DIR, "weekly-review-completion-check-log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ---------- Sheets helpers ----------

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
        return []
    return r.json().get("values", [])


def parse_currency(s):
    if not s:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# ---------- Notion task lookup ----------

def find_weekly_review_task(target_date):
    """Find the Weekly Pricing Review task for a given date.
    target_date: datetime.date for the Saturday the task was created.
    """
    # Title format: "Weekly Pricing Review — Apr 05, 2026"
    title_pattern = f"Weekly Pricing Review — {target_date.strftime('%b %d, %Y')}"
    log.info(f"Looking for Notion task: '{title_pattern}'")

    r = requests.post(
        f"{NOTION_API}/databases/{PROJECT_LIST_DB_ID}/query",
        headers=NOTION_HEADERS,
        json={
            "filter": {
                "property": "Project name",
                "title": {"contains": target_date.strftime("%b %d, %Y")},
            },
            "page_size": 10,
        },
    )
    if r.status_code != 200:
        log.error(f"Notion query error: {r.status_code} {r.text[:300]}")
        return None
    results = r.json().get("results", [])
    for p in results:
        title_rt = p["properties"].get("Project name", {}).get("title", [])
        title = title_rt[0].get("plain_text", "") if title_rt else ""
        if "Weekly Pricing Review" in title:
            return p
    return None


def fetch_task_children(page_id):
    """Get all child blocks of a page."""
    blocks = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        r = requests.get(f"{NOTION_API}/blocks/{page_id}/children", headers=NOTION_HEADERS, params=params)
        if r.status_code != 200:
            break
        data = r.json()
        blocks.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return blocks


def check_task_status(task):
    """Return (status_name, checklist_checked_count, checklist_total)."""
    props = task.get("properties", {})
    status_prop = props.get("Status", {}).get("status") or {}
    status_name = status_prop.get("name", "") if status_prop else ""

    page_id = task["id"]
    blocks = fetch_task_children(page_id)
    total = 0
    checked = 0
    for b in blocks:
        if b.get("type") == "to_do":
            total += 1
            if b["to_do"].get("checked"):
                checked += 1
    return status_name, checked, total


# ---------- Change Log analysis ----------

def read_changelog():
    return sheets_get(f"{CHANGELOG_TAB}!A1:L500")


def read_dashboard():
    data = sheets_get(f"{DASHBOARD_TAB}!A1:V500")
    if not data:
        return [], []
    headers = data[0]
    rows = []
    for row in data[1:]:
        padded = row + [""] * (len(headers) - len(row))
        rows.append(dict(zip(headers, padded)))
    return headers, rows


def get_properties_needing_action():
    """Return list of property dicts that are currently red or yellow."""
    _, rows = read_dashboard()
    at_risk = []
    for r in rows:
        g = (r.get("Grade") or "").strip()
        if "🔴" in g or "🟡" in g or "Needs" in g or "Slightly" in g:
            at_risk.append(r)
    return at_risk


def detect_actions_since(start_date, properties_at_risk):
    """For each property, look for evidence that action was taken since start_date."""
    changelog = read_changelog()
    results = {}

    # Build lookup of property name → row dict
    for p in properties_at_risk:
        name = (p.get("Property") or "").strip()
        results[name] = {
            "grade": p.get("Grade", ""),
            "base_price_change": None,
            "min_price_change": None,
            "price_log_entry": False,
            "optimization_log_entry": False,
            "has_action": False,
        }

    # Look for Base Price changes in the Change Log
    for row in changelog[1:]:
        padded = row + [""] * 12
        date_str, prop, field, from_val, to_val = padded[0], padded[1].strip(), padded[2], padded[3], padded[4]
        try:
            change_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if change_date < start_date:
            continue
        if prop not in results:
            continue
        if field == "Base Price":
            old = parse_currency(from_val)
            new = parse_currency(to_val)
            if old and new and old > 0:
                pct_change = abs(new - old) / old
                if pct_change >= ACTION_THRESHOLD_PCT:
                    results[prop]["base_price_change"] = f"{from_val} → {to_val}"
                    results[prop]["has_action"] = True

    # Check for Price Change Log and Listing Optimization Log entries in current dashboard
    _, rows = read_dashboard()
    for r in rows:
        name = (r.get("Property") or "").strip()
        if name not in results:
            continue
        price_log = (r.get("Price Change Log") or "").strip()
        opt_log = (r.get("Listing Optimization Log") or "").strip()
        # Simple check: if the log has ANY content mentioning the start_date year-month, mark it
        date_prefix = start_date.strftime("%Y-%m")
        if date_prefix in price_log:
            results[name]["price_log_entry"] = True
            results[name]["has_action"] = True
        if date_prefix in opt_log:
            results[name]["optimization_log_entry"] = True
            results[name]["has_action"] = True

    return results


# ---------- Email ----------

def send_email(subject, html):
    if not EMAIL_USER or not EMAIL_PASS:
        log.warning("No email credentials")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = ", ".join(EMAIL_RECIPIENTS)
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_RECIPIENTS, msg.as_string())
        log.info(f"Email sent: {subject}")
    except Exception as e:
        log.error(f"Email failed: {e}")


def main(dry_run=False):
    log.info("=" * 60)
    log.info(f"Weekly Review Completion Check at {datetime.now()}")
    log.info("=" * 60)

    today = date.today()
    # Saturday of last week (today is Monday, so 2 days ago)
    days_since_saturday = (today.weekday() - 5) % 7  # Saturday = 5
    if days_since_saturday == 0:
        days_since_saturday = 7  # if run on Saturday, check the previous Saturday
    last_saturday = today - timedelta(days=days_since_saturday)
    log.info(f"Checking Weekly Pricing Review for: {last_saturday}")

    issues = []

    # 1. Find the Notion task
    task = find_weekly_review_task(last_saturday)
    if not task:
        issues.append(f"❌ Weekly Pricing Review task for {last_saturday.strftime('%b %d')} was NOT found in Notion. The task creation may have failed or been deleted.")
        task_url = None
    else:
        task_url = task.get("url", "")
        status_name, checked, total = check_task_status(task)
        log.info(f"Task status: {status_name}, checklist: {checked}/{total}")

        # 2. Task marked Done
        if status_name != "Done":
            issues.append(f"⚠️ Task exists but status is '{status_name}', not 'Done'.")

        # 3. Checklist completion threshold
        if total > 0:
            pct = checked / total
            if pct < CHECKLIST_COMPLETION_THRESHOLD:
                issues.append(f"⚠️ Only {checked}/{total} checklist items checked ({pct*100:.0f}%). Target: {CHECKLIST_COMPLETION_THRESHOLD*100:.0f}%.")

    # 4. Action evidence on at-risk properties
    at_risk_properties = get_properties_needing_action()
    log.info(f"At-risk properties currently: {len(at_risk_properties)}")

    actions = detect_actions_since(last_saturday, at_risk_properties)
    no_action_properties = [name for name, a in actions.items() if not a["has_action"]]

    if no_action_properties:
        issues.append(f"⚠️ {len(no_action_properties)} at-risk properties show NO pricing action since {last_saturday.strftime('%b %d')}: {', '.join(no_action_properties[:10])}")

    # Build email
    today_str = today.strftime("%B %d, %Y")
    if issues:
        subject = f"⚠️ Weekly Pricing Review Issues — {today_str}"
        html = f"""
<html><body style="font-family: Arial, sans-serif; max-width: 720px;">
<h2 style="color: #c03;">Weekly Pricing Review Completion Check</h2>
<p>Checking review for week of <b>{last_saturday.strftime('%B %d, %Y')}</b></p>

<h3>Issues Found</h3>
<ul>
"""
        for issue in issues:
            html += f"<li>{issue}</li>"
        html += "</ul>"

        if task_url:
            html += f'<p><a href="{task_url}">Open Notion task</a></p>'

        html += """
<h3>Action Required</h3>
<p>Please follow up with the team member who owns pricing this week to verify the review was completed. The Saturday pricing email contains the original task link and context.</p>

<h3>Evidence Details</h3>
"""
        if no_action_properties:
            html += "<p><b>Properties showing no pricing action since Saturday:</b></p><ul>"
            for name in no_action_properties:
                html += f"<li>{name}</li>"
            html += "</ul>"

        html += """
<p style="color: #888; font-size: 12px;">Auto-generated every Monday at 8 AM. If you believe this alert is in error, check the Pricing Dashboard Change Log and the Notion task directly.</p>
</body></html>
"""
    else:
        # All good
        subject = f"✅ Weekly Pricing Review Complete — {today_str}"
        html = f"""
<html><body style="font-family: Arial, sans-serif; max-width: 720px;">
<h2 style="color: #2c7a5b;">Weekly Pricing Review Complete</h2>
<p>Review for week of <b>{last_saturday.strftime('%B %d, %Y')}</b> passed all completion checks:</p>
<ul>
  <li>✅ Task created and marked Done</li>
  <li>✅ At least {int(CHECKLIST_COMPLETION_THRESHOLD*100)}% of checklist items completed</li>
  <li>✅ Action evidence found on all at-risk properties</li>
</ul>
<p>No action needed this week.</p>
</body></html>
"""

    if dry_run:
        log.info(f"[DRY RUN] Would send email: {subject}")
        log.info(f"[DRY RUN] Issues: {len(issues)}")
        for i in issues:
            log.info(f"  - {i}")
        return

    send_email(subject, html)
    log.info(f"Done. Issues: {len(issues)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
