"""
Nurture AI Guest Responder

Polls Hospitable for new guest messages, drafts replies using Claude API
with property knowledge, and posts to Slack for approval before sending.

Flow:
  1. Fetch active reservations from Hospitable
  2. Check for new guest messages (vs state file)
  3. For each new message: build context, call Claude, post draft to Slack
  4. Slack button handlers (in content-bot.py) send approved replies

Usage:
  python scripts/guest-responder.py          # Check for new messages
  python scripts/guest-responder.py --reset  # Clear state, reprocess all

Scheduled: Every 5 minutes via Windows Task Scheduler
"""

import os
import sys
import json
import time
import logging
import argparse
import requests
from datetime import datetime, timedelta, timezone
import zoneinfo

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

HOSPITABLE_TOKEN = os.getenv("HOSPITABLE_API_TOKEN")
HOSPITABLE_BASE = "https://public.api.hospitable.com/v2"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
SLACK_HOSPITABLE_CHANNEL_ID = os.getenv("SLACK_HOSPITABLE_CHANNEL_ID", os.getenv("SLACK_CHANNEL_ID"))

TORONTO_TZ = zoneinfo.ZoneInfo("America/Toronto")

KNOWLEDGE_FILE = os.path.join(SCRIPT_DIR, "property-knowledge.json")
STATE_FILE = os.path.join(SCRIPT_DIR, "guest-responder-state.json")

# Known host names (messages from these are ignored)
HOST_NAMES = {
    "Jeffrey Pang", "Ayodeji Awonuga", "Eunicinth Smith",
    "Angelica Liu", "Kemraj Bishundeo", "Fabian Montique",
    "Chibuikem Ofoegbu", "Kausar Fatima", "Martine Aldridge",
}

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
log = logging.getLogger("guest-responder")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

ch = logging.StreamHandler()
ch.setFormatter(fmt)
log.addHandler(ch)

fh = logging.FileHandler(os.path.join(SCRIPT_DIR, "guest-responder-log.txt"), encoding="utf-8")
fh.setFormatter(fmt)
log.addHandler(fh)


# ---------------------------------------------------------------------------
# HOSPITABLE API
# ---------------------------------------------------------------------------
def hosp_get(path, params=None, max_retries=3):
    """GET from Hospitable API with rate limiting and retry on timeout."""
    url = f"{HOSPITABLE_BASE}{path}"
    headers = {"Authorization": f"Bearer {HOSPITABLE_TOKEN}"}
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code == 429:
                log.warning("Hospitable rate limited, waiting 5s...")
                time.sleep(5)
                continue
            if resp.status_code != 200:
                log.error(f"Hospitable API error {resp.status_code} on {path}: {resp.text[:200]}")
                return {}
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            wait = 2 ** attempt
            log.warning(f"Hospitable API timeout on {path} (attempt {attempt + 1}/{max_retries}). Retrying in {wait}s...")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                log.error(f"Hospitable API failed after {max_retries} attempts: {e}")
                return {}
    return {}


def hosp_send_message(reservation_id, body):
    """Send a message to a guest via Hospitable API."""
    url = f"{HOSPITABLE_BASE}/reservations/{reservation_id}/messages"
    headers = {
        "Authorization": f"Bearer {HOSPITABLE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"body": body}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code == 429:
        log.warning("Hospitable rate limited on send, waiting 5s...")
        time.sleep(5)
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code in (200, 201):
        log.info(f"Message sent for reservation {reservation_id}")
        return True
    else:
        log.error(f"Failed to send message: {resp.status_code} {resp.text[:300]}")
        return False


def fetch_properties():
    """Fetch all properties with details from Hospitable."""
    data = hosp_get("/properties", {"per_page": 50, "include": "details,listings"})
    props = {}
    for p in data.get("data", []):
        pid = p["id"]
        airbnb = [l for l in p.get("listings", []) if l.get("platform") == "airbnb"]
        owner = airbnb[0].get("platform_name", "") if airbnb else ""
        addr = p.get("address", {})
        street = addr.get("street") or ""
        city = addr.get("city") or ""
        props[pid] = {
            "id": pid,
            "owner": owner,
            "address": f"{street}, {city}".strip(", "),
            "listed": p.get("listed", False),
        }
    return props


def fetch_active_reservations(prop_ids):
    """Fetch current and upcoming reservations."""
    past = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

    params = [("properties[]", pid) for pid in prop_ids]
    params.extend([
        ("check_in_from", past),
        ("check_out_to", future),
        ("per_page", "50"),
    ])

    data = hosp_get("/reservations", params)
    return data.get("data", [])


def fetch_messages(reservation_id, count=30):
    """Fetch messages for a reservation."""
    data = hosp_get(f"/reservations/{reservation_id}/messages", {"per_page": count})
    return data.get("data", [])


# ---------------------------------------------------------------------------
# STATE MANAGEMENT
# ---------------------------------------------------------------------------
def load_state():
    """Load state file tracking last processed message per reservation."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    """Save state file."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# KNOWLEDGE BASE
# ---------------------------------------------------------------------------
def load_knowledge():
    """Load property knowledge base."""
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    log.warning(f"Knowledge file not found: {KNOWLEDGE_FILE}")
    return {}


def build_property_context(prop_id, knowledge):
    """Build a text context string for Claude from property knowledge."""
    prop = knowledge.get(prop_id, {})
    if not prop:
        return "No property details available."

    parts = []
    if prop.get("address"):
        parts.append(f"Address: {prop['address']}")
    if prop.get("wifi", {}).get("name"):
        parts.append(f"WiFi Network: {prop['wifi']['name']}")
        parts.append(f"WiFi Password: {prop['wifi']['password']}")
    if prop.get("checkin"):
        parts.append(f"Check-in time: {prop['checkin']}")
    if prop.get("checkout"):
        parts.append(f"Check-out time: {prop['checkout']}")
    if prop.get("max_guests"):
        parts.append(f"Max guests: {prop['max_guests']}")
    if prop.get("house_manual"):
        parts.append(f"\nHouse Manual:\n{prop['house_manual']}")
    if prop.get("guest_access"):
        parts.append(f"\nGuest Access:\n{prop['guest_access']}")
    if prop.get("additional_rules"):
        parts.append(f"\nAdditional Rules:\n{prop['additional_rules']}")
    if prop.get("space_overview"):
        parts.append(f"\nSpace Overview:\n{prop['space_overview']}")
    if prop.get("guidebook_text"):
        parts.append(f"\nWelcome Guide:\n{prop['guidebook_text']}")
    if prop.get("knowledge_hub"):
        parts.append(f"\nKnowledge Hub (additional info):\n{prop['knowledge_hub']}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLAUDE API
# ---------------------------------------------------------------------------
def generate_reply(guest_message, property_context, conversation_history,
                   guest_name, host_name, check_in, check_out, property_name):
    """Call Claude API to generate a draft reply."""
    import anthropic

    system_prompt = f"""You are a friendly, professional Airbnb host assistant for Nurture property management.
You are replying to a guest on behalf of the host. Be warm, helpful, and concise.

PROPERTY DETAILS:
{property_context}

RESERVATION:
- Guest: {guest_name}
- Check-in: {check_in}
- Check-out: {check_out}
- Property: {property_name}
- Host name: {host_name}

RULES:
- Be warm, helpful, and concise. Keep replies under 150 words unless the question needs detail.
- NEVER make up information. Only use facts from the property details above.
- If the guest's question is NOT answerable from the property details, set confidence to 0.3 or lower and category to "escalate".
- For maintenance/repair requests, complaints, pricing/refund questions, early check-in/late checkout requests: ALWAYS set category to "escalate" regardless of confidence.
- For simple questions (WiFi, check-in time, parking, house rules, local recs, thank-you replies): set category to "routine".
- Sign off with the host's first name: {host_name}
- Do not use dashes or hyphens in your reply (use commas, periods, or colons instead). Exception: compound words like "check-in".
- Do not mention that you are an AI or assistant.

Respond ONLY in valid JSON with these exact keys:
{{"reply": "your message to the guest", "confidence": 0.0-1.0, "category": "routine or escalate"}}"""

    # Build conversation for context
    conv_text = ""
    if conversation_history:
        conv_text = "\n\nRecent conversation:\n"
        for msg in conversation_history[-6:]:
            sender = msg.get("sender", {}).get("first_name", "Unknown")
            body = msg.get("body", "")[:300]
            conv_text += f"{sender}: {body}\n"

    user_message = f"""{conv_text}

The guest just sent this new message:
{guest_name}: {guest_message}

Draft a reply as {host_name}. Respond in JSON format."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        text = response.content[0].text.strip()

        # Parse JSON from response (handle potential markdown wrapping)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        return {
            "reply": result.get("reply", ""),
            "confidence": float(result.get("confidence", 0.5)),
            "category": result.get("category", "escalate"),
        }
    except json.JSONDecodeError:
        log.error(f"Failed to parse Claude response as JSON: {text[:200]}")
        return {
            "reply": text if text else "I need to check on this for you.",
            "confidence": 0.3,
            "category": "escalate",
        }
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return {
            "reply": "",
            "confidence": 0.0,
            "category": "escalate",
        }


# ---------------------------------------------------------------------------
# SLACK
# ---------------------------------------------------------------------------
def post_to_slack(reservation, guest_msg, draft, property_info, knowledge):
    """Post a guest message + draft reply to Slack for approval."""
    prop_id = reservation.get("property", "")
    prop = knowledge.get(prop_id, {})
    prop_name = prop.get("name") or property_info.get("address", "Unknown property")
    owner = prop.get("owner_name") or property_info.get("owner", "")
    guest_name = guest_msg.get("sender", {}).get("first_name", "Guest")
    guest_full = guest_msg.get("sender", {}).get("full_name", guest_name)
    msg_body = guest_msg.get("body", "")
    check_in = reservation.get("check_in", "")[:10]
    check_out = reservation.get("check_out", "")[:10]

    confidence = draft.get("confidence", 0)
    category = draft.get("category", "escalate")
    draft_reply = draft.get("reply", "")
    reservation_id = reservation.get("id", "")

    # Confidence indicator
    if confidence >= 0.8:
        conf_emoji = ":large_green_circle:"
    elif confidence >= 0.5:
        conf_emoji = ":large_yellow_circle:"
    else:
        conf_emoji = ":red_circle:"

    escalate_flag = " :warning: *Needs your input*" if category == "escalate" else ""

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"New Guest Message{' (escalated)' if category == 'escalate' else ''}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":house: *{prop_name}* ({owner})\n"
                    f":bust_in_silhouette: *{guest_full}* | {check_in} to {check_out}\n\n"
                    f":speech_balloon: *Guest message:*\n>{msg_body[:500]}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":memo: *Draft reply:*\n{draft_reply}\n\n"
                    f"{conf_emoji} Confidence: {int(confidence * 100)}% | "
                    f"Category: {category}{escalate_flag}"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": "guest_response_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Send"},
                    "style": "primary",
                    "action_id": "guest_approve",
                    "value": json.dumps({
                        "reservation_id": reservation_id,
                        "reply": draft_reply,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit & Send"},
                    "action_id": "guest_edit",
                    "value": json.dumps({
                        "reservation_id": reservation_id,
                        "reply": draft_reply,
                        "guest_name": guest_name,
                        "prop_name": prop_name,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Skip"},
                    "action_id": "guest_skip",
                    "value": reservation_id,
                },
            ],
        },
    ]

    fallback = f"New guest message from {guest_full} at {prop_name}: {msg_body[:100]}"

    try:
        from slack_sdk import WebClient
        client = WebClient(token=SLACK_BOT_TOKEN)
        result = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=fallback,
            blocks=blocks,
            unfurl_links=False,
        )
        log.info(f"Posted to Slack: {guest_full} at {prop_name}")
        return True
    except Exception as e:
        log.error(f"Slack post failed: {e}")
        return False


# ---------------------------------------------------------------------------
# OFF-HOURS ALERT
# ---------------------------------------------------------------------------
def is_offhours():
    """Return True if current Toronto time is before 10am or after 7pm weekdays, or any time on weekends."""
    now = datetime.now(TORONTO_TZ)
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    hour = now.hour
    if weekday >= 5:  # Saturday or Sunday
        return True
    return hour < 10 or hour >= 19  # before 10am or 7pm+


def post_urgent_alert(reservation, guest_msg, draft, property_info, knowledge):
    """Post an urgent Slack alert when AI cannot handle a guest message during off-hours."""
    prop_id = reservation.get("property", "")
    prop = knowledge.get(prop_id, {})
    prop_name = prop.get("name") or property_info.get("address", "Unknown property")
    guest_full = guest_msg.get("sender", {}).get("full_name", "Guest")
    msg_body = guest_msg.get("body", "")
    check_in = reservation.get("check_in", "")[:10]
    confidence = draft.get("confidence", 0)
    category = draft.get("category", "escalate")

    reason = "needs your input" if category == "escalate" else f"low confidence ({int(confidence * 100)}%)"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rotating_light: *Guest needs attention* :rotating_light:\n"
                    f":house: *{prop_name}* | check-in {check_in}\n"
                    f":bust_in_silhouette: *{guest_full}* | AI {reason}\n\n"
                    f":speech_balloon: _{msg_body[:300]}_"
                ),
            },
        }
    ]

    try:
        from slack_sdk import WebClient
        client = WebClient(token=SLACK_BOT_TOKEN)
        client.chat_postMessage(
            channel=SLACK_HOSPITABLE_CHANNEL_ID,
            text=f"Guest needs attention: {guest_full} at {prop_name}",
            blocks=blocks,
            unfurl_links=False,
        )
        log.info(f"Urgent off-hours alert sent for {guest_full} at {prop_name}")
    except Exception as e:
        log.error(f"Urgent Slack alert failed: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def get_guest_name_from_messages(messages):
    """Get the guest name from messages (first non-host sender)."""
    for m in messages:
        sender = m.get("sender", {})
        full_name = sender.get("full_name", "")
        if full_name and full_name not in HOST_NAMES:
            return full_name
    return "Guest"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Clear state and reprocess")
    args = parser.parse_args()

    log.info("Guest responder starting...")

    if args.reset and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        log.info("State file cleared")

    state = load_state()
    knowledge = load_knowledge()
    properties = fetch_properties()

    if not properties:
        log.error("No properties found, exiting")
        return

    # Fetch active reservations
    prop_ids = list(properties.keys())
    reservations = fetch_active_reservations(prop_ids)
    log.info(f"Found {len(reservations)} active reservations")

    new_messages_found = 0

    for res in reservations:
        rid = res["id"]
        prop_id = res.get("property", "")
        prop_info = properties.get(prop_id, {})

        time.sleep(0.2)
        messages = fetch_messages(rid)
        if not messages:
            continue

        # Messages are returned newest first
        latest_msg = messages[0]
        latest_msg_id = latest_msg.get("id", "")
        latest_sent_at = latest_msg.get("created_at", "")

        # Check if we've already processed this message
        prev_state = state.get(rid, {})
        if prev_state.get("last_message_id") == latest_msg_id:
            continue

        # Check if latest message is from a guest (not host/bot)
        sender = latest_msg.get("sender", {})
        sender_name = sender.get("full_name", "")
        sender_type = latest_msg.get("sender_type", "")
        msg_source = latest_msg.get("source", "")

        # Use sender_type (most reliable), source field, and host name list
        is_guest_msg = (
            sender_type == "guest"
            and msg_source == "platform"
            and sender_name not in HOST_NAMES
        )

        if not is_guest_msg:
            state[rid] = {
                "last_message_id": latest_msg_id,
                "last_message_at": latest_sent_at,
            }
            continue

        # New guest message found!
        guest_name = sender.get("first_name", "Guest")
        guest_full = sender.get("full_name", guest_name)
        msg_body = latest_msg.get("body", "")

        log.info(f"New message from {guest_full} on reservation {rid}: {msg_body[:80]}")
        new_messages_found += 1

        # Build property context
        prop_knowledge = knowledge.get(prop_id, {})
        property_context = build_property_context(prop_id, knowledge)
        host_name = prop_knowledge.get("host_sign_off", prop_info.get("owner", "").split()[0] if prop_info.get("owner") else "Your Host")
        prop_name = prop_knowledge.get("name") or prop_info.get("address", "")
        check_in = res.get("check_in", "")[:10]
        check_out = res.get("check_out", "")[:10]

        # Get conversation history (reverse to chronological)
        conversation = list(reversed(messages[:10]))

        # Generate draft reply via Claude
        draft = generate_reply(
            guest_message=msg_body,
            property_context=property_context,
            conversation_history=conversation,
            guest_name=guest_name,
            host_name=host_name,
            check_in=check_in,
            check_out=check_out,
            property_name=prop_name,
        )

        log.info(f"  Draft: confidence={draft['confidence']}, category={draft['category']}")
        log.info(f"  Reply: {draft['reply'][:100]}")

        # Post to Slack for approval
        post_to_slack(res, latest_msg, draft, prop_info, knowledge)

        # Off-hours urgent alert when AI needs human input
        if is_offhours() and (draft.get("category") == "escalate" or draft.get("confidence", 1) < 0.6):
            post_urgent_alert(res, latest_msg, draft, prop_info, knowledge)

        # Update state
        state[rid] = {
            "last_message_id": latest_msg_id,
            "last_message_at": latest_sent_at,
        }

    save_state(state)
    log.info(f"Done. {new_messages_found} new guest messages processed.")


if __name__ == "__main__":
    main()
