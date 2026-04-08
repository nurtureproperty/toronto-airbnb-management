"""Daily email summary of guest bot activity. Reads GUEST_BOT_LOG messages from Slack and emails a digest."""
import sys, os, json, requests, smtplib, re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"c:\Users\jef_p\toronto-airbnb-management\.env")

SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER)
TO_EMAIL = "info@nurtre.io"

LOG_PREFIX = "GUEST_BOT_LOG"

def fetch_slack_messages(hours=24):
    """Fetch messages from Slack channel for the last N hours, filtered by GUEST_BOT_LOG."""
    oldest = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    messages = []
    cursor = None

    while True:
        params = {
            "channel": SLACK_CHANNEL,
            "oldest": str(oldest),
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        r = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
            params=params,
        )
        data = r.json()
        if not data.get("ok"):
            print(f"Slack API error: {data.get('error')}")
            break

        for msg in data.get("messages", []):
            text = msg.get("text", "")
            if LOG_PREFIX in text:
                messages.append(msg)

        if data.get("has_more") and data.get("response_metadata", {}).get("next_cursor"):
            cursor = data["response_metadata"]["next_cursor"]
        else:
            break

    return messages


def parse_log_message(text):
    """Parse a GUEST_BOT_LOG Slack message into structured data."""
    entry = {
        "action": "unknown",
        "time": "",
        "guest": "Unknown",
        "property": "Unknown",
        "confidence": 0,
        "question": "",
        "answer": "",
        "escalated_to": None,
    }

    # Action and time
    action_match = re.search(r"GUEST_BOT_LOG \| ([\d:APM ]+) \| (\w[\w-]+)", text)
    if action_match:
        entry["time"] = action_match.group(1).strip()
        entry["action"] = action_match.group(2).strip().lower()

    # Guest and property
    guest_match = re.search(r"Guest:\s*([^|]+)", text)
    if guest_match:
        entry["guest"] = guest_match.group(1).strip()

    prop_match = re.search(r"Property:\s*([^|]+)", text)
    if prop_match:
        entry["property"] = prop_match.group(1).strip()

    # Confidence
    conf_match = re.search(r"Confidence:\s*[^\d]*(\d+)%", text)
    if conf_match:
        entry["confidence"] = int(conf_match.group(1))

    # Question and answer
    q_match = re.search(r'Q:\s*"([^"]*)"', text)
    if q_match:
        entry["question"] = q_match.group(1)

    a_match = re.search(r'A:\s*"([^"]*)"', text)
    if a_match:
        entry["answer"] = a_match.group(1)

    # Escalation
    esc_match = re.search(r"Escalated to:\s*(\w+)", text)
    if esc_match:
        entry["escalated_to"] = esc_match.group(1)

    return entry


def build_email_html(entries, date_str):
    """Build HTML email from parsed log entries."""
    auto_replies = [e for e in entries if e["action"] == "auto-reply"]
    escalations = [e for e in entries if e["action"] == "escalated"]

    total = len(entries)
    auto_count = len(auto_replies)
    esc_count = len(escalations)
    avg_confidence = round(sum(e["confidence"] for e in entries) / total) if total else 0

    html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333;">
    <div style="background: #759b8f; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0; font-size: 22px;">Guest Bot Daily Summary</h1>
        <p style="margin: 5px 0 0; opacity: 0.9;">{date_str}</p>
    </div>

    <div style="padding: 20px; background: #f9f9f9;">
        <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
            <tr>
                <td style="text-align: center; padding: 15px; background: white; border-radius: 8px; margin: 5px;">
                    <div style="font-size: 28px; font-weight: bold; color: #759b8f;">{total}</div>
                    <div style="font-size: 12px; color: #666;">Total Messages</div>
                </td>
                <td style="text-align: center; padding: 15px; background: white; border-radius: 8px; margin: 5px;">
                    <div style="font-size: 28px; font-weight: bold; color: #4CAF50;">{auto_count}</div>
                    <div style="font-size: 12px; color: #666;">Auto-Replied</div>
                </td>
                <td style="text-align: center; padding: 15px; background: white; border-radius: 8px; margin: 5px;">
                    <div style="font-size: 28px; font-weight: bold; color: #FF9800;">{esc_count}</div>
                    <div style="font-size: 12px; color: #666;">Escalated</div>
                </td>
                <td style="text-align: center; padding: 15px; background: white; border-radius: 8px; margin: 5px;">
                    <div style="font-size: 28px; font-weight: bold; color: #2196F3;">{avg_confidence}%</div>
                    <div style="font-size: 12px; color: #666;">Avg Confidence</div>
                </td>
            </tr>
        </table>
    """

    if auto_replies:
        html += """
        <h2 style="color: #4CAF50; border-bottom: 2px solid #4CAF50; padding-bottom: 5px;">
            ✅ Auto-Replied ({count})
        </h2>
        <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;">
            <tr style="background: #f0f0f0;">
                <th style="padding: 8px; text-align: left; font-size: 12px;">Time</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Guest</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Property</th>
                <th style="padding: 8px; text-align: center; font-size: 12px;">Conf.</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Question</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Reply</th>
            </tr>
        """.replace("{count}", str(auto_count))

        for e in auto_replies:
            conf_color = "#4CAF50" if e["confidence"] >= 95 else "#FF9800"
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px; font-size: 12px;">{e['time']}</td>
                <td style="padding: 8px; font-size: 12px;">{e['guest']}</td>
                <td style="padding: 8px; font-size: 12px;">{e['property'][:20]}</td>
                <td style="padding: 8px; text-align: center; font-size: 12px; color: {conf_color}; font-weight: bold;">{e['confidence']}%</td>
                <td style="padding: 8px; font-size: 11px; max-width: 150px; overflow: hidden;">{e['question'][:80]}</td>
                <td style="padding: 8px; font-size: 11px; max-width: 150px; overflow: hidden;">{e['answer'][:80]}</td>
            </tr>"""

        html += "</table>"

    if escalations:
        html += """
        <h2 style="color: #FF9800; border-bottom: 2px solid #FF9800; padding-bottom: 5px; margin-top: 25px;">
            ⚠️ Escalated ({count})
        </h2>
        <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;">
            <tr style="background: #fff3e0;">
                <th style="padding: 8px; text-align: left; font-size: 12px;">Time</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Guest</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Property</th>
                <th style="padding: 8px; text-align: center; font-size: 12px;">Conf.</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Question</th>
                <th style="padding: 8px; text-align: left; font-size: 12px;">Assigned To</th>
            </tr>
        """.replace("{count}", str(esc_count))

        for e in escalations:
            html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 8px; font-size: 12px;">{e['time']}</td>
                <td style="padding: 8px; font-size: 12px;">{e['guest']}</td>
                <td style="padding: 8px; font-size: 12px;">{e['property'][:20]}</td>
                <td style="padding: 8px; text-align: center; font-size: 12px; color: #f44336; font-weight: bold;">{e['confidence']}%</td>
                <td style="padding: 8px; font-size: 11px; max-width: 200px;">{e['question'][:100]}</td>
                <td style="padding: 8px; font-size: 12px; font-weight: bold;">{e['escalated_to'] or 'Team'}</td>
            </tr>"""

        html += "</table>"

    if total == 0:
        html += """
        <div style="text-align: center; padding: 40px; color: #999;">
            <p style="font-size: 18px;">No guest messages processed today.</p>
        </div>
        """

    html += """
    </div>
    <div style="padding: 15px; text-align: center; color: #999; font-size: 11px; background: #f0f0f0; border-radius: 0 0 8px 8px;">
        Nurture Guest Bot | Auto-generated daily summary
    </div>
    </body></html>"""

    return html


def send_email(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [TO_EMAIL], msg.as_string())
    print(f"Email sent to {TO_EMAIL}")


def main():
    print("Fetching Slack messages from last 24 hours...")
    messages = fetch_slack_messages(hours=24)
    print(f"Found {len(messages)} GUEST_BOT_LOG messages")

    entries = []
    for msg in messages:
        entry = parse_log_message(msg.get("text", ""))
        entries.append(entry)

    # Sort by time (oldest first)
    entries.reverse()

    date_str = datetime.now().strftime("%A, %B %d, %Y")
    auto_count = sum(1 for e in entries if e["action"] == "auto-reply")
    esc_count = sum(1 for e in entries if e["action"] == "escalated")

    subject = f"Guest Bot Summary — {datetime.now().strftime('%b %d')} — {auto_count} replied, {esc_count} escalated"

    html = build_email_html(entries, date_str)
    send_email(subject, html)
    print("Done!")


if __name__ == "__main__":
    main()
