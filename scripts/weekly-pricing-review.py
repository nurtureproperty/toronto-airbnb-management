"""
Weekly Pricing Review Task Creator

Every Saturday at 8 AM, creates a new task in the Notion Project List
database with the 34-item pricing review checklist embedded as to_do blocks.
Pulls past 7 days of alerts from the daily pricing report log for context.
Emails info@nurtre.io and angelica@nurtre.io and posts a Slack notification.

Usage:
  python scripts/weekly-pricing-review.py             # Normal run
  python scripts/weekly-pricing-review.py --dry-run   # Preview, no writes

Scheduled: Saturdays at 8:00 AM via Windows Task Scheduler (NurtureWeeklyPricingReview)
"""

import os
import sys
import logging
import argparse
import re
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
PROJECT_LIST_DB_ID = "b24ffa51-4302-4a76-8063-eed4318acff0"
NOTION_API_BASE = "https://api.notion.com/v1"

PRICING_RULES_SHEET_URL = "https://docs.google.com/spreadsheets/d/1cnp7qHzfJ3mScJVpWUUInGWqK_0ZEAtHJFXszoJf-MI/edit"
PRICING_DASHBOARD_URL = "https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A/edit"
HOSPITABLE_INBOX_URL = "https://my.hospitable.com"
CHECKLIST_TEMPLATE_URL = "https://www.notion.so/Weekly-Pricing-Checklist-Template-33909a91876281658937d6928771f214"

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID", "C0AG2CHB55J")

EMAIL_USER = os.getenv("EMAIL_SMTP_USER")
EMAIL_PASS = os.getenv("EMAIL_SMTP_PASSWORD")
EMAIL_RECIPIENTS = ["info@nurtre.io", "angelica@nurtre.io"]

DAILY_PRICING_LOG = os.path.join(SCRIPT_DIR, "daily-pricing-report-log.txt")

LOG_FILE = os.path.join(SCRIPT_DIR, "weekly-pricing-review-log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# Full 34-item checklist pulled from the Notion template
CHECKLIST_ITEMS = [
    # Section: Review At-Risk Properties
    "Open Hospitable and view the calendar",
    "Check the pricing dashboard for at-risk (yellow and red) properties",
    "Compare real occupancy to booking target (green, no color, light red, dark red)",
    "Complete the below tasks for each non-green property",
    # Section: Calendar Gaps and Anomalies
    "Scan next 4 weeks for awkward checkout days (Friday creating hard-to-fill weekend gaps)",
    "Identify orphan nights (1 to 3 night gaps between bookings)",
    "Flag gaps 7+ days out with no bookings (candidates for price drop or minimum stay reduction)",
    "Check if any days are stuck at minimum price and not booking (if yes, reduce minimum 10 to 15% OR reoptimize)",
    # Section: Competitor Check
    "Sample 3 similar listings in the same neighborhood (Airbnb or AirDNA)",
    "Note their nightly rate and compare to yours",
    "Confirm you are priced 20 to 30% higher than similar listings (the goal)",
    "Note any competitor deals or unusual pricing pulling bookings away",
    # Section: Events and Seasonality
    "Check the next 60 days for events, holidays, or long weekends",
    "Confirm premium is applied (TIFF, Taylor Swift, Nuit Blanche, Canadian holidays)",
    "Check for new event announcements since last week (Ticketmaster, city event calendars)",
    "Adjust minimum stay for major events (3 to 5 nights for TIFF, New Year)",
    # Section: Customization Review
    "Adjacent factor is on for every listing",
    "Far-out premium is manually configured (not PriceLabs default)",
    "Gradual discount curve is set at the correct BLT",
    "Orphan night pricing is set (15 to 25% discount)",
    "Day-of-week adjustments are calibrated",
    "Minimum nights are consistent across Airbnb, Hospitable, and PriceLabs",
    # Section: Base Price Adjustment
    "Over-occupied: raise base price by one increment (max +10% per week unless Algorithm Reset)",
    "Green: leave base price unchanged",
    "Light red: lower base price by one increment",
    "Dark red: lower base price by one to two increments OR reoptimize listing",
    # Section: Reviews and Listing Health
    "Check Airbnb Insights for views, wishlist saves, conversion rate per listing",
    "Note any listings with dropping view count (ranking issue, not pricing)",
    "Verify overall rating is at or above 4.95",
    "Check for new reviews under 5 stars that need responses",
    # Section: Logging and Summary
    "Record changes in the Pricing Dashboard",
    "Update Dashboard with new base prices and color codes",
    "Write Slack summary in general channel listing what changed this week",
    "Mark the Notion weekly task as Done",
]


def pull_recent_alerts():
    if not os.path.exists(DAILY_PRICING_LOG):
        return []
    cutoff = datetime.now() - timedelta(days=7)
    alerts = []
    try:
        with open(DAILY_PRICING_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"(\d{4}-\d{2}-\d{2}) [\d:]+ \[(\w+)\] (.*)", line)
                if not m:
                    continue
                try:
                    line_date = datetime.strptime(m.group(1), "%Y-%m-%d")
                except ValueError:
                    continue
                if line_date < cutoff:
                    continue
                level = m.group(2)
                msg = m.group(3)
                if level in ("WARNING", "ERROR") or "alert" in msg.lower() or "below" in msg.lower() or "orphan" in msg.lower():
                    alerts.append(f"{m.group(1)}: {msg}")
    except Exception as e:
        log.error(f"Could not read daily pricing log: {e}")
    return alerts[-20:]


def create_notion_page(title, alerts):
    today = datetime.now().strftime("%Y-%m-%d")

    children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "Weekly Pricing Review"}}]},
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "Spot check pricing across all properties. Aim to finish by 12 PM. Mark each item below as you complete it, then set this task to Done. The team's Saturday morning pricing email (sent at 7 AM) has the full briefing for context."}}
                ]
            },
        },
    ]

    # Past alerts section
    children.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Past 7 Days of Daily Pricing Alerts"}}]},
    })
    if alerts:
        for alert in alerts:
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": alert[:1800]}}]},
            })
    else:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": "No alerts flagged this week."}}]},
        })

    # Checklist
    children.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Checklist"}}]},
    })
    for item in CHECKLIST_ITEMS:
        children.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"type": "text", "text": {"content": item}}],
                "checked": False,
            },
        })

    # Resources
    children.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "Resources"}}]},
    })
    children.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Pricing Dashboard: "}},
                {"type": "text", "text": {"content": "Google Sheet", "link": {"url": PRICING_DASHBOARD_URL}}},
            ]
        },
    })
    children.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Pricing Rules Engine: "}},
                {"type": "text", "text": {"content": "Google Sheet", "link": {"url": PRICING_RULES_SHEET_URL}}},
            ]
        },
    })
    children.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Full Checklist Template: "}},
                {"type": "text", "text": {"content": "Notion", "link": {"url": CHECKLIST_TEMPLATE_URL}}},
            ]
        },
    })
    children.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Hospitable Inbox: "}},
                {"type": "text", "text": {"content": "my.hospitable.com", "link": {"url": HOSPITABLE_INBOX_URL}}},
            ]
        },
    })

    # Create page with up to 100 children, then append the rest
    payload = {
        "parent": {"database_id": PROJECT_LIST_DB_ID},
        "properties": {
            "Project name": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "Not Started"}},
            "Priority": {"select": {"name": "Medium"}},
            "Due By": {"date": {"start": today}},
        },
        "children": children[:100],
    }

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    resp = requests.post(f"{NOTION_API_BASE}/pages", headers=headers, json=payload)
    if resp.status_code != 200:
        log.error(f"Notion create error: {resp.status_code} {resp.text[:500]}")
        return None

    data = resp.json()
    page_id = data["id"]
    page_url = data.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

    # Append remaining children in batches of 100
    remaining = children[100:]
    for i in range(0, len(remaining), 100):
        batch = remaining[i:i+100]
        r = requests.patch(
            f"{NOTION_API_BASE}/blocks/{page_id}/children",
            headers=headers,
            json={"children": batch},
        )
        if r.status_code != 200:
            log.error(f"Batch append error: {r.status_code}")

    log.info(f"Created Notion page: {page_url}")
    return page_url


def send_email(page_url, alerts):
    if not EMAIL_USER or not EMAIL_PASS:
        return
    today = datetime.now().strftime("%B %d, %Y")
    alerts_html = ""
    if alerts:
        alerts_html = "<ul>" + "".join(f"<li>{a}</li>" for a in alerts) + "</ul>"
    else:
        alerts_html = "<p><em>No alerts flagged this week.</em></p>"

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; max-width: 700px;">
        <h2>Weekly Pricing Review — {today}</h2>
        <p>Your weekly pricing review task has been created in Notion with the full 34-item checklist.</p>
        <p><strong><a href="{page_url}">Open task in Notion and check off each item</a></strong></p>

        <h3>Past 7 Days of Daily Pricing Alerts</h3>
        {alerts_html}

        <h3>Resources</h3>
        <ul>
          <li><a href="{PRICING_DASHBOARD_URL}">Pricing Dashboard</a></li>
          <li><a href="{PRICING_RULES_SHEET_URL}">Pricing Rules Engine</a></li>
          <li><a href="{CHECKLIST_TEMPLATE_URL}">Full Checklist Template</a></li>
        </ul>
      </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Weekly Pricing Review Task Created — {today}"
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


def slack_notify(page_url):
    if not SLACK_TOKEN:
        return
    message = (
        f"📊 *Weekly Pricing Review* task created\n"
        f"Time to spot check pricing across all properties. 34-item checklist waiting.\n"
        f"<{page_url}|Open task in Notion>"
    )
    requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "text": message, "unfurl_links": False},
    )


def main(dry_run=False):
    log.info("=" * 60)
    log.info(f"Weekly pricing review at {datetime.now()}")
    log.info("=" * 60)

    today_label = datetime.now().strftime("%b %d, %Y")
    title = f"Weekly Pricing Review — {today_label}"

    alerts = pull_recent_alerts()
    log.info(f"Found {len(alerts)} alerts from past 7 days")

    if dry_run:
        log.info(f"[DRY RUN] Would create task: {title}")
        log.info(f"[DRY RUN] Would include {len(CHECKLIST_ITEMS)} checklist items")
        log.info(f"[DRY RUN] Would email: {EMAIL_RECIPIENTS}")
        return

    page_url = create_notion_page(title, alerts)
    if not page_url:
        log.error("Failed to create page, aborting")
        return

    send_email(page_url, alerts)
    slack_notify(page_url)
    log.info("Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
