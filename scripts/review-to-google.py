"""
Nurture: 5-Star Review → Google Review Request

Polls Hospitable for new reviews across all properties. When a 5-star
review is found, searches GHL for the guest contact (already created by
the Hospitable reservation webhook) by property address, and sends an
SMS asking for a Google review.

Flow:
  1. Fetch reviews from all properties (since last check)
  2. Filter for 5-star reviews not yet processed
  3. For each: search GHL contacts by property address → most recent match
  4. Send SMS to that contact
  5. Post confirmation to Slack

Usage:
  python scripts/review-to-google.py             # Run check
  python scripts/review-to-google.py --dry-run    # Preview only, no SMS sent
  python scripts/review-to-google.py --reset      # Clear state, reprocess all

Scheduled: Every 30 minutes via Windows Task Scheduler
"""

import os
import sys
import json
import time
import logging
import argparse
import requests
import hashlib
from datetime import datetime, timedelta, timezone

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
HOSP_HEADERS = {"Authorization": f"Bearer {HOSPITABLE_TOKEN}", "Accept": "application/json"}

GHL_API_BASE = "https://services.leadconnectorhq.com"
GHL_API_TOKEN = os.getenv("GHL_API_TOKEN")
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")

STATE_FILE = os.path.join(SCRIPT_DIR, "review-to-google-state.json")

# Tag added to GHL contacts to trigger the review request workflow
GHL_REVIEW_TAG = "5-star-reviewer"

# Known host names (skip reviews from hosts)
HOST_NAMES = {
    "Jeffrey Pang", "Ayodeji Awonuga", "Eunicinth Smith",
    "Angelica Liu", "Kemraj Bishundeo", "Fabian Montique",
    "Chibuikem Ofoegbu", "Kausar Fatima", "Martine Aldridge",
}

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
log = logging.getLogger("review-to-google")
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

ch = logging.StreamHandler()
ch.setFormatter(fmt)
log.addHandler(ch)

fh = logging.FileHandler(os.path.join(SCRIPT_DIR, "review-to-google-log.txt"), encoding="utf-8")
fh.setFormatter(fmt)
log.addHandler(fh)

# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------
LOCK_FILE = os.path.join(SCRIPT_DIR, "review-to-google.lock")


def acquire_lock():
    """Prevent concurrent runs."""
    if os.path.exists(LOCK_FILE):
        try:
            lock_age = time.time() - os.path.getmtime(LOCK_FILE)
            if lock_age < 300:  # 5 min
                log.warning("Another instance is running (lock file exists). Exiting.")
                sys.exit(0)
            else:
                log.warning("Stale lock file found, removing.")
                os.remove(LOCK_FILE)
        except Exception:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass


def review_fingerprint(property_id, review):
    """Create a stable fingerprint for a review based on content, not API ID."""
    raw = f"{property_id}|{review.get('reviewed_at', '')}|{review.get('public', {}).get('rating', '')}|{review.get('public', {}).get('review', '')[:100]}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_review_ids": [], "processed_fingerprints": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# HOSPITABLE API
# ---------------------------------------------------------------------------
def hosp_get(path, params=None):
    url = f"{HOSPITABLE_BASE}{path}"
    resp = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if resp.status_code == 429:
        log.warning("Hospitable rate limited, waiting 5s...")
        time.sleep(5)
        resp = requests.get(url, headers=HOSP_HEADERS, params=params, timeout=30)
    if resp.status_code != 200:
        log.error(f"Hospitable API error {resp.status_code} on {path}: {resp.text[:200]}")
        return {}
    return resp.json()


def fetch_all_properties():
    """Fetch all property IDs and names."""
    data = hosp_get("/properties", {"per_page": 50, "include": "details,listings"})
    props = {}
    for p in data.get("data", []):
        pid = p["id"]
        name = p.get("name", "Unknown")
        airbnb = [l for l in p.get("listings", []) if l.get("platform") == "airbnb"]
        owner = airbnb[0].get("platform_name", "") if airbnb else ""
        props[pid] = {"name": name, "owner": owner}
    return props


def fetch_reviews(property_id, per_page=10):
    """Fetch recent reviews for a property."""
    data = hosp_get(f"/properties/{property_id}/reviews", {"per_page": per_page})
    return data.get("data", [])


# ---------------------------------------------------------------------------
# GHL API
# ---------------------------------------------------------------------------
def ghl_headers():
    return {
        "Authorization": f"Bearer {GHL_API_TOKEN}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }


def ghl_find_guest_by_property(property_name):
    """Search GHL for the most recent guest contact at a property.

    Guests are created in GHL by the Hospitable reservation webhook with
    'guest' in their name and the property address on the contact.
    """
    resp = requests.get(
        f"{GHL_API_BASE}/contacts/",
        headers=ghl_headers(),
        params={"locationId": GHL_LOCATION_ID, "query": property_name, "limit": 20},
        timeout=15,
    )
    if resp.status_code != 200:
        log.error(f"GHL contact search failed: {resp.status_code} {resp.text[:200]}")
        return None

    contacts = resp.json().get("contacts", [])
    if not contacts:
        return None

    # Sort by dateUpdated descending to get the most recent guest
    contacts.sort(
        key=lambda c: c.get("dateUpdated", c.get("dateAdded", "")),
        reverse=True,
    )

    # Only match contacts with "guest" in the name (how guests are labeled in GHL)
    for contact in contacts:
        full_name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip().lower()
        if "guest" in full_name and full_name not in {n.lower() for n in HOST_NAMES}:
            return contact

    return None


def ghl_add_tag(contact_id, tag):
    """Add a tag to a GHL contact to trigger a workflow."""
    # First get existing tags
    resp = requests.get(
        f"{GHL_API_BASE}/contacts/{contact_id}",
        headers=ghl_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        log.error(f"GHL get contact failed: {resp.status_code} {resp.text[:200]}")
        return False

    existing_tags = resp.json().get("contact", {}).get("tags", [])
    if tag in existing_tags:
        log.info(f"Contact {contact_id} already has tag '{tag}'")
        return True

    # Add the new tag
    resp = requests.put(
        f"{GHL_API_BASE}/contacts/{contact_id}",
        headers=ghl_headers(),
        json={"tags": existing_tags + [tag]},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        log.info(f"Added tag '{tag}' to contact {contact_id}")
        return True
    else:
        log.error(f"GHL add tag failed: {resp.status_code} {resp.text[:200]}")
        return False


# ---------------------------------------------------------------------------
# SLACK NOTIFICATION
# ---------------------------------------------------------------------------
def slack_notify(message):
    """Post a message to Slack."""
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL:
        log.warning("Slack not configured, skipping notification")
        return

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": SLACK_CHANNEL, "text": message},
        timeout=10,
    )
    if not resp.json().get("ok"):
        log.error(f"Slack notification failed: {resp.json().get('error')}")


# ---------------------------------------------------------------------------
# MAIN LOGIC
# ---------------------------------------------------------------------------
def process_reviews(dry_run=False):
    acquire_lock()
    try:
        _process_reviews_inner(dry_run)
    finally:
        release_lock()


def _process_reviews_inner(dry_run=False):
    state = load_state()
    processed = set(state.get("processed_review_ids", []))
    processed_fps = set(state.get("processed_fingerprints", []))
    properties = fetch_all_properties()

    if not properties:
        log.error("No properties found in Hospitable")
        return

    log.info(f"Checking reviews across {len(properties)} properties...")

    new_five_stars = []

    for pid, pinfo in properties.items():
        reviews = fetch_reviews(pid)
        time.sleep(0.2)  # Rate limiting

        for review in reviews:
            rid = review.get("id")
            fp = review_fingerprint(pid, review)

            # Skip if already processed by ID or fingerprint
            if rid in processed or fp in processed_fps:
                continue

            rating = review.get("public", {}).get("rating")
            review_text = review.get("public", {}).get("review", "")
            reviewed_at = review.get("reviewed_at", "")

            # Mark all reviews as processed (not just 5-star) to avoid re-checking
            processed.add(rid)
            processed_fps.add(fp)

            if rating != 5:
                log.info(f"Skipping {rating}-star review for {pinfo['name']}")
                continue

            log.info(f"Found 5-star review for {pinfo['name']}!")
            new_five_stars.append({
                "review_id": rid,
                "property_id": pid,
                "property_name": pinfo["name"],
                "review_text": review_text[:200],
                "reviewed_at": reviewed_at,
            })

    if not new_five_stars:
        log.info("No new 5-star reviews found")
        state["processed_review_ids"] = list(processed)
        state["processed_fingerprints"] = list(processed_fps)
        save_state(state)
        return

    log.info(f"Found {len(new_five_stars)} new 5-star review(s)")

    # Cache GHL contact lookups per property to avoid redundant API calls
    contact_cache = {}

    for review_info in new_five_stars:
        pid = review_info["property_id"]
        pname = review_info["property_name"]

        # Search GHL for the most recent guest contact at this property
        if pid not in contact_cache:
            contact_cache[pid] = ghl_find_guest_by_property(pname)
            time.sleep(0.2)
        contact = contact_cache[pid]

        if dry_run:
            log.info(f"[DRY RUN] Would process 5-star review for {pname}")
            continue

        if not contact:
            log.warning(f"No GHL contact found for property {pname}")
            slack_notify(
                f"⭐ 5-star review received for *{pname}* but could not find "
                f"guest contact in GHL to send Google review request."
            )
            continue

        contact_id = contact.get("id")
        guest_first = contact.get("firstName", "")
        guest_last = contact.get("lastName", "")
        guest_phone = contact.get("phone", "")
        guest_full = f"{guest_first} {guest_last}".strip()

        # Add tag to trigger GHL workflow (workflow handles the SMS)
        success = ghl_add_tag(contact_id, GHL_REVIEW_TAG)

        if success:
            slack_notify(
                f"⭐ 5-star review at *{pname}*!\n"
                f"Guest: {guest_full}\n"
                f"✅ Tagged in GHL, review request workflow triggered"
            )
        else:
            slack_notify(
                f"⭐ 5-star review at *{pname}*\n"
                f"Guest: {guest_full}\n"
                f"❌ Failed to tag contact in GHL"
            )

    # Save state
    state["processed_review_ids"] = list(processed)
    state["processed_fingerprints"] = list(processed_fps)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    log.info("Done")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="5-Star Review → Google Review Request")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no SMS sent")
    parser.add_argument("--reset", action="store_true", help="Clear state, reprocess all reviews")
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            log.info("State file cleared")

    process_reviews(dry_run=args.dry_run)
