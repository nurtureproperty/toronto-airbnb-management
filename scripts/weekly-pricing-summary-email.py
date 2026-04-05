"""
Weekly Pricing Summary Email

Every Saturday morning, compiles a team summary from the Pricing Dashboard +
Change Log and emails it to info@nurtre.io and angelica@nurtre.io.

Sections:
  1. Grade distribution (🔴 🟡 🟢 ⚪)
  2. Revenue vs minimum (properties below target + total gap)
  3. Changes made this past week (base price changes from Change Log)
  4. Audit results from last Friday (wins / neutral / misses)
  5. Properties needing attention (red + below minimum revenue)

Usage:
  python scripts/weekly-pricing-summary-email.py             # Normal run
  python scripts/weekly-pricing-summary-email.py --dry-run   # Print to console only

Scheduled: Saturdays at 7:00 AM via NurtureWeeklyPricingSummary task
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

SHEET_ID = "1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
DASHBOARD_TAB = "Dashboard"
CHANGELOG_TAB = "Change Log"

GSHEETS_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
GSHEETS_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
GSHEETS_REFRESH_TOKEN = os.getenv("GSHEETS_REFRESH_TOKEN")

EMAIL_USER = os.getenv("EMAIL_SMTP_USER")
EMAIL_PASS = os.getenv("EMAIL_SMTP_PASSWORD")
EMAIL_RECIPIENTS = ["info@nurtre.io", "angelica@nurtre.io"]

LOG_FILE = os.path.join(SCRIPT_DIR, "weekly-pricing-summary-email-log.txt")
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
        return []
    return r.json().get("values", [])


def parse_currency(s):
    if not s:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


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


def read_changelog():
    return sheets_get(f"{CHANGELOG_TAB}!A1:L1000")


def build_summary():
    headers, rows = read_dashboard()
    if not rows:
        return None

    today = date.today()
    week_ago = today - timedelta(days=7)

    # ---- Section 1: Grade distribution ----
    grade_counts = {"🔴 Needs Optimizing": 0, "🟡 Slightly Under": 0, "🟢 Good Occupancy": 0, "⚪ Priced Too Low": 0, "⚠️ Archived": 0, "No Data": 0}
    for r in rows:
        g = (r.get("Grade") or "").strip()
        if not g:
            grade_counts["No Data"] += 1
        elif "🔴" in g or "Needs" in g:
            grade_counts["🔴 Needs Optimizing"] += 1
        elif "🟡" in g or "Slightly" in g:
            grade_counts["🟡 Slightly Under"] += 1
        elif "🟢" in g or "Good" in g:
            grade_counts["🟢 Good Occupancy"] += 1
        elif "⚪" in g or "Priced Too Low" in g or "Over" in g:
            grade_counts["⚪ Priced Too Low"] += 1
        elif "Archived" in g or "⚠️" in g:
            grade_counts["⚠️ Archived"] += 1
        else:
            grade_counts["No Data"] += 1

    # ---- Section 2: Revenue vs Minimum ----
    below_min = []
    total_gap = 0
    for r in rows:
        payout = parse_currency(r.get("Host Payout Last 30d"))
        minimum = parse_currency(r.get("Minimum 30d Revenue"))
        if payout is None or minimum is None or minimum == 0:
            continue
        if payout < minimum:
            gap = minimum - payout
            total_gap += gap
            below_min.append({"property": r.get("Property", ""), "payout": payout, "minimum": minimum, "gap": gap})
    below_min.sort(key=lambda x: x["gap"], reverse=True)

    # ---- Section 3: Changes made this past week ----
    changelog = read_changelog()
    base_price_changes = []
    grade_changes = []
    for row in changelog[1:]:
        padded = row + [""] * 12
        date_str, prop, field, from_val, to_val = padded[0], padded[1], padded[2], padded[3], padded[4]
        try:
            change_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if change_date < week_ago or change_date > today:
            continue
        if field == "Base Price":
            base_price_changes.append({"property": prop, "from": from_val, "to": to_val, "date": date_str})
        elif field == "Grade":
            grade_changes.append({"property": prop, "from": from_val, "to": to_val, "date": date_str})

    # ---- Section 4: Audit results from last Friday ----
    audit_wins = audit_neutral = audit_misses = 0
    for row in changelog[1:]:
        padded = row + [""] * 12
        date_str = padded[0]
        outcome = padded[11] if len(padded) > 11 else ""
        try:
            change_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        # Only count audits of changes from the past 14 days
        if change_date < today - timedelta(days=14):
            continue
        if outcome == "Win":
            audit_wins += 1
        elif outcome == "Miss":
            audit_misses += 1
        elif outcome == "Neutral":
            audit_neutral += 1

    # ---- Section 5: Properties needing attention ----
    red_properties = []
    for r in rows:
        g = (r.get("Grade") or "").strip()
        if "🔴" in g or "Needs" in g:
            red_properties.append({
                "property": r.get("Property", ""),
                "grade": g,
                "occ_blt": r.get("Occ at BLT (forward)", ""),
                "recommendation": r.get("Smart Recommendation", "")[:200],
            })

    return {
        "today": today,
        "week_ago": week_ago,
        "grade_counts": grade_counts,
        "below_min": below_min,
        "total_gap": total_gap,
        "base_price_changes": base_price_changes,
        "grade_changes": grade_changes,
        "audit": {"wins": audit_wins, "neutral": audit_neutral, "misses": audit_misses},
        "red_properties": red_properties,
        "total_properties": len(rows),
    }


def render_html(summary):
    today = summary["today"]
    gc = summary["grade_counts"]

    html = f"""
<html><body style="font-family: Arial, sans-serif; max-width: 720px; color: #333;">
<h2 style="color: #2c7a5b;">Nurture Weekly Pricing Summary — {today.strftime('%B %d, %Y')}</h2>
<p><em>Week of {summary['week_ago'].strftime('%b %d')} to {today.strftime('%b %d')}, {summary['total_properties']} active properties</em></p>

<h3>📊 Grade Distribution</h3>
<table cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
  <tr style="background: #f0f0f0;"><th align="left">Grade</th><th align="right">Count</th></tr>
  <tr><td>🟢 Good Occupancy</td><td align="right"><b>{gc['🟢 Good Occupancy']}</b></td></tr>
  <tr><td>⚪ Priced Too Low</td><td align="right"><b>{gc['⚪ Priced Too Low']}</b></td></tr>
  <tr><td>🟡 Slightly Under</td><td align="right"><b>{gc['🟡 Slightly Under']}</b></td></tr>
  <tr><td>🔴 Needs Optimizing</td><td align="right"><b style="color:#c03;">{gc['🔴 Needs Optimizing']}</b></td></tr>
</table>

<h3>💰 Revenue vs Minimum</h3>
<p><b>{len(summary['below_min'])}</b> properties below their Minimum 30d Revenue target. Total gap: <b style="color:#c03;">${summary['total_gap']:,.0f}</b></p>
"""
    if summary['below_min']:
        html += '<table cellpadding="6" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">'
        html += '<tr style="background: #f0f0f0;"><th align="left">Property</th><th align="right">Payout</th><th align="right">Minimum</th><th align="right">Gap</th></tr>'
        for p in summary['below_min'][:10]:
            html += f'<tr><td>{p["property"]}</td><td align="right">${p["payout"]:,.0f}</td><td align="right">${p["minimum"]:,.0f}</td><td align="right" style="color:#c03;">-${p["gap"]:,.0f}</td></tr>'
        html += '</table>'
        if len(summary['below_min']) > 10:
            html += f'<p><em>+{len(summary["below_min"])-10} more</em></p>'

    html += f"""
<h3>🔧 Changes Made This Week</h3>
<ul>
  <li><b>{len(summary['base_price_changes'])}</b> base price changes</li>
  <li><b>{len(summary['grade_changes'])}</b> grade transitions</li>
</ul>
"""
    if summary['base_price_changes']:
        html += '<p><b>Base price changes:</b></p><ul>'
        for c in summary['base_price_changes'][:10]:
            html += f'<li>{c["property"]}: {c["from"]} → {c["to"]} ({c["date"]})</li>'
        if len(summary['base_price_changes']) > 10:
            html += f'<li><em>+{len(summary["base_price_changes"])-10} more</em></li>'
        html += '</ul>'

    audit = summary['audit']
    total_audited = audit['wins'] + audit['neutral'] + audit['misses']
    html += f"""
<h3>📈 Audit Results (from last Friday)</h3>
"""
    if total_audited > 0:
        decisive = audit['wins'] + audit['misses']
        accuracy = (audit['wins'] / decisive * 100) if decisive > 0 else 0
        html += f"""
<ul>
  <li>✅ Wins: <b>{audit['wins']}</b></li>
  <li>🟡 Neutral: <b>{audit['neutral']}</b></li>
  <li>❌ Misses: <b>{audit['misses']}</b></li>
  <li>Accuracy (wins / decisive): <b>{accuracy:.0f}%</b></li>
</ul>
"""
    else:
        html += '<p><em>No audit results yet. First audit with real data will be next Friday after changes accumulate.</em></p>'

    red = summary['red_properties']
    html += f"""
<h3>⚠️ Properties Needing Attention ({len(red)})</h3>
"""
    if red:
        html += '<table cellpadding="6" cellspacing="0" style="border-collapse: collapse; border: 1px solid #ddd;">'
        html += '<tr style="background: #f0f0f0;"><th align="left">Property</th><th align="right">Occ at BLT</th><th align="left">Smart Rec</th></tr>'
        for p in red:
            html += f'<tr><td>{p["property"]}</td><td align="right">{p["occ_blt"]}</td><td style="font-size: 12px;">{p["recommendation"]}</td></tr>'
        html += '</table>'
    else:
        html += '<p>None. All properties on target or better.</p>'

    html += f"""
<h3>🔗 Quick Links</h3>
<ul>
  <li><a href="https://docs.google.com/spreadsheets/d/{SHEET_ID}">Pricing Dashboard</a></li>
  <li><a href="https://www.notion.so/33909a91876281f1ba85cad5ebf9fefd">Pricing Performance DB</a></li>
  <li><a href="https://docs.google.com/spreadsheets/d/1cnp7qHzfJ3mScJVpWUUInGWqK_0ZEAtHJFXszoJf-MI">Pricing Rules Engine</a></li>
</ul>

<p style="color: #888; font-size: 12px; margin-top: 30px;">Auto-generated every Saturday at 7 AM. Weekly Pricing Review task will be created in Notion at 8 AM with the full checklist.</p>
</body></html>
"""
    return html


def send_email(html, summary):
    if not EMAIL_USER or not EMAIL_PASS:
        log.warning("No email credentials, skipping")
        return
    today = summary["today"]
    red_count = len(summary["red_properties"])
    below_count = len(summary["below_min"])

    subject = f"Nurture Pricing Summary — {today.strftime('%b %d')} — {red_count} red, {below_count} below min"

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
        log.info(f"Email sent to {EMAIL_RECIPIENTS}")
    except Exception as e:
        log.error(f"Email failed: {e}")


def main(dry_run=False):
    log.info("=" * 60)
    log.info(f"Weekly pricing summary email at {datetime.now()}")
    log.info("=" * 60)

    summary = build_summary()
    if not summary:
        log.error("Could not build summary, aborting")
        return

    log.info(f"Grade counts: {summary['grade_counts']}")
    log.info(f"Below minimum: {len(summary['below_min'])} properties, ${summary['total_gap']:,.0f} gap")
    log.info(f"Changes this week: {len(summary['base_price_changes'])} base price, {len(summary['grade_changes'])} grades")

    html = render_html(summary)

    if dry_run:
        log.info("[DRY RUN] Would send email with this HTML:")
        log.info(html[:2000])
        return

    send_email(html, summary)
    log.info("Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
