"""
Nurture Social Media Content Bot (Slack Listener)
Listens for approval button clicks from content-machine.py, opens edit modal,
then posts approved content to social platforms.

Run: python scripts/content-bot.py (runs continuously via Socket Mode)
Scheduled: Windows Task Scheduler "on startup" to keep it running

Supported platforms:
  - X/Twitter (via Tweepy)
  - YouTube Shorts (via YouTube Data API v3)
  - Instagram, Facebook, Pinterest, Bluesky (coming soon)
"""

import json
import os
import sys
import logging
import re
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
import tweepy
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")

GHL_API_TOKEN = os.getenv("GHL_API_TOKEN")
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID")
GHL_USER_ID = "S2n7GTT5wizOg33AmUre"  # Jeff Pang's GHL user ID

# Hospitable API (for guest responder)
HOSPITABLE_TOKEN = os.getenv("HOSPITABLE_API_TOKEN")
HOSPITABLE_BASE = "https://public.api.hospitable.com/v2"

META_PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN")
META_PAGE_ID = os.getenv("META_PAGE_ID")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")

# GHL Social Planner account IDs (from /social-media-posting/{locationId}/accounts)
GHL_ACCOUNT_IDS = {
    "facebook":  "697e8188964d9df270aa537f_vtTGsxK2RAKQfFtpkhx5_798310683373466_page",
    "instagram": "697e816a964d9d0080aa4194_vtTGsxK2RAKQfFtpkhx5_17841480305453995",
    "tiktok":    "697e81e2964d9d737aaa849b_vtTGsxK2RAKQfFtpkhx5_000algCzTb0ocNTaXfxMHoslWFIrI2B7e6_profile",
    "pinterest": "697e8f1c964d9d20d4b2d23f_vtTGsxK2RAKQfFtpkhx5_1149895854766019346_profile",
    "youtube":   "697e8c2e86627e9b6b6fa024_vtTGsxK2RAKQfFtpkhx5_UCql_AMiKoirMXOqYnh57_SA_profile",
    "bluesky":   "697e924586627ebd4a73bef2_vtTGsxK2RAKQfFtpkhx5_did:plc:5w4dyz2ivtpyucrfrhdxvb7a_profile",
}

IMAGES_DIR = os.path.join(SCRIPT_DIR, "content-images")
META_FILE = os.path.join(IMAGES_DIR, "latest-posts.json")

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
_log_handlers = [logging.StreamHandler()]
try:
    _log_handlers.append(
        logging.FileHandler(os.path.join(SCRIPT_DIR, "content-bot-log.txt"), encoding="utf-8")
    )
except PermissionError:
    print("WARNING: log file locked, logging to console only")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_log_handlers,
)
log = logging.getLogger("content-bot")

# ---------------------------------------------------------------------------
# SLACK APP (Socket Mode)
# ---------------------------------------------------------------------------
app = App(token=SLACK_BOT_TOKEN)


def load_latest_meta():
    """Load the latest posts metadata saved by content-machine.py."""
    if os.path.exists(META_FILE):
        with open(META_FILE, "r") as f:
            return json.load(f)
    return None


def get_post_data(option_index):
    """Get post data from metadata file."""
    meta = load_latest_meta()
    if meta and "posts" in meta:
        posts = meta["posts"]
        if option_index < len(posts):
            return posts[option_index]
    return None


def get_media_path(option_index):
    """Get media path and type for the selected option.

    Returns (path, media_type) where media_type is 'video' or 'image'.
    Returns (None, None) if no media found.
    """
    meta = load_latest_meta()

    # Check for video path first (set by content-machine.py for video reels)
    if meta and "video_path" in meta:
        video_path = meta["video_path"]
        if os.path.exists(video_path):
            return video_path, "video"

    # Check image paths
    if meta and "image_paths" in meta:
        paths = meta["image_paths"]
        if option_index < len(paths) and os.path.exists(paths[option_index]):
            return paths[option_index], "image"

    # Fallback: try standard naming
    style_names = ["dark", "clean", "grid"]
    if option_index < len(style_names):
        path = os.path.join(IMAGES_DIR, f"post-{option_index + 1}-{style_names[option_index]}.png")
        if os.path.exists(path):
            return path, "image"

    return None, None


# ---------------------------------------------------------------------------
# SLACK BUTTON HANDLERS
# ---------------------------------------------------------------------------
@app.action("approve_1")
def handle_approve_1(ack, body, client):
    ack()
    open_edit_modal(body, client, option_index=0)


@app.action("approve_2")
def handle_approve_2(ack, body, client):
    ack()
    open_edit_modal(body, client, option_index=1)


@app.action("approve_3")
def handle_approve_3(ack, body, client):
    ack()
    open_edit_modal(body, client, option_index=2)


@app.action("skip_today")
def handle_skip(ack, body, client):
    ack()
    user = body.get("user", {}).get("username", "Unknown")
    channel = body.get("channel", {}).get("id", SLACK_CHANNEL_ID)
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")

    log.info(f"Skipped by {user}")

    # Update the button message to show it was skipped
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f":x: Skipped by @{user}. Fresh content will be generated tomorrow.",
    )


# ---------------------------------------------------------------------------
# GUEST RESPONDER: Hospitable API + Button Handlers
# ---------------------------------------------------------------------------
def hosp_send_message(reservation_id, body_text):
    """Send a message to a guest via Hospitable API."""
    if not HOSPITABLE_TOKEN:
        log.error("HOSPITABLE_API_TOKEN not set")
        return False
    url = f"{HOSPITABLE_BASE}/reservations/{reservation_id}/messages"
    headers = {
        "Authorization": f"Bearer {HOSPITABLE_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json={"body": body_text}, timeout=30)
    if resp.status_code == 429:
        log.warning("Hospitable rate limited on send, waiting 5s...")
        time.sleep(5)
        resp = requests.post(url, headers=headers, json={"body": body_text}, timeout=30)
    if resp.status_code in (200, 201):
        log.info(f"Guest message sent for reservation {reservation_id}")
        return True
    else:
        log.error(f"Failed to send guest message: {resp.status_code} {resp.text[:300]}")
        return False


@app.action("guest_approve")
def handle_guest_approve(ack, body, client):
    """Send the draft reply to the guest via Hospitable."""
    ack()
    user = body.get("user", {}).get("username", "Unknown")
    channel = body.get("channel", {}).get("id", SLACK_CHANNEL_ID)
    message_ts = body.get("message", {}).get("ts")

    try:
        action = next(a for a in body.get("actions", []) if a.get("action_id") == "guest_approve")
        payload = json.loads(action.get("value", "{}"))
    except (StopIteration, json.JSONDecodeError):
        log.error("Could not parse guest_approve payload")
        return

    reservation_id = payload.get("reservation_id", "")
    reply = payload.get("reply", "")

    if not reply:
        client.chat_postMessage(channel=channel, thread_ts=message_ts,
                                text=":warning: No reply text found.")
        return

    log.info(f"Guest approve by {user}: reservation={reservation_id}")

    success = hosp_send_message(reservation_id, reply)

    if success:
        # Update the original message to show it was sent
        client.chat_postMessage(
            channel=channel,
            thread_ts=message_ts,
            text=f":white_check_mark: Reply sent by @{user}",
        )
        # Remove the buttons from the original message
        try:
            original_blocks = body.get("message", {}).get("blocks", [])
            updated_blocks = [b for b in original_blocks if b.get("block_id") != "guest_response_actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":white_check_mark: Sent by @{user} at {datetime.now().strftime('%H:%M')}"}],
            })
            client.chat_update(
                channel=channel,
                ts=message_ts,
                blocks=updated_blocks,
                text=body.get("message", {}).get("text", "Guest message sent"),
            )
        except Exception as e:
            log.warning(f"Could not update original message: {e}")
    else:
        client.chat_postMessage(
            channel=channel,
            thread_ts=message_ts,
            text=":x: Failed to send reply via Hospitable. Check the logs.",
        )


@app.action("guest_edit")
def handle_guest_edit(ack, body, client):
    """Open a modal to edit the draft reply before sending."""
    ack()
    trigger_id = body.get("trigger_id")
    message_ts = body.get("message", {}).get("ts")
    channel_id = body.get("channel", {}).get("id", SLACK_CHANNEL_ID)

    try:
        action = next(a for a in body.get("actions", []) if a.get("action_id") == "guest_edit")
        payload = json.loads(action.get("value", "{}"))
    except (StopIteration, json.JSONDecodeError):
        log.error("Could not parse guest_edit payload")
        return

    reservation_id = payload.get("reservation_id", "")
    reply = payload.get("reply", "")
    guest_name = payload.get("guest_name", "Guest")
    prop_name = payload.get("prop_name", "")

    metadata = json.dumps({
        "reservation_id": reservation_id,
        "message_ts": message_ts,
        "channel_id": channel_id,
    })

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "guest_edit_modal",
                "private_metadata": metadata,
                "title": {"type": "plain_text", "text": f"Reply to {guest_name}"},
                "submit": {"type": "plain_text", "text": "Send Reply"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f":house: *{prop_name}*"},
                    },
                    {
                        "type": "input",
                        "block_id": "reply_block",
                        "label": {"type": "plain_text", "text": "Message to guest"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "reply_text",
                            "multiline": True,
                            "initial_value": reply,
                        },
                    },
                ],
            },
        )
        log.info(f"Opened guest edit modal for reservation {reservation_id}")
    except Exception as e:
        log.error(f"Failed to open guest edit modal: {e}")


@app.action("guest_skip")
def handle_guest_skip(ack, body, client):
    """Skip replying to this guest message."""
    ack()
    user = body.get("user", {}).get("username", "Unknown")
    channel = body.get("channel", {}).get("id", SLACK_CHANNEL_ID)
    message_ts = body.get("message", {}).get("ts")

    log.info(f"Guest message skipped by {user}")

    client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text=f":fast_forward: Skipped by @{user}. No reply sent.",
    )

    # Remove buttons from original message
    try:
        original_blocks = body.get("message", {}).get("blocks", [])
        updated_blocks = [b for b in original_blocks if b.get("block_id") != "guest_response_actions"]
        updated_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f":fast_forward: Skipped by @{user} at {datetime.now().strftime('%H:%M')}"}],
        })
        client.chat_update(
            channel=channel,
            ts=message_ts,
            blocks=updated_blocks,
            text=body.get("message", {}).get("text", "Guest message skipped"),
        )
    except Exception as e:
        log.warning(f"Could not update original message: {e}")


# ---------------------------------------------------------------------------
# GUEST EDIT MODAL SUBMISSION
# ---------------------------------------------------------------------------
@app.view("guest_edit_modal")
def handle_guest_edit_submit(ack, body, view, client):
    """Handle submission of the guest edit modal: send the edited reply."""
    ack()

    values = view.get("state", {}).get("values", {})
    reply = values.get("reply_block", {}).get("reply_text", {}).get("value", "")
    metadata = json.loads(view.get("private_metadata", "{}"))
    reservation_id = metadata.get("reservation_id", "")
    message_ts = metadata.get("message_ts")
    channel_id = metadata.get("channel_id", SLACK_CHANNEL_ID)
    user = body.get("user", {}).get("username", "Unknown")

    if not reply:
        log.warning("Guest edit modal submitted with empty reply")
        return

    log.info(f"Guest edit+send by {user}: reservation={reservation_id}")

    success = hosp_send_message(reservation_id, reply)

    if success:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=message_ts,
            text=f":white_check_mark: Edited reply sent by @{user}:\n>{reply[:300]}",
        )
        # Remove buttons from original message
        try:
            orig_resp = client.conversations_history(channel=channel_id, latest=message_ts, limit=1, inclusive=True)
            orig_msg = orig_resp.get("messages", [{}])[0]
            original_blocks = orig_msg.get("blocks", [])
            updated_blocks = [b for b in original_blocks if b.get("block_id") != "guest_response_actions"]
            updated_blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f":pencil: Edited and sent by @{user} at {datetime.now().strftime('%H:%M')}"}],
            })
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                blocks=updated_blocks,
                text="Guest message sent (edited)",
            )
        except Exception as e:
            log.warning(f"Could not update original message after edit: {e}")
    else:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=message_ts,
            text=":x: Failed to send edited reply via Hospitable. Check the logs.",
        )


# ---------------------------------------------------------------------------
# CONTENT BOT: BUTTON HANDLERS (Social Media)
# ---------------------------------------------------------------------------
def open_edit_modal(body, client, option_index):
    """Open a Slack modal with editable post text and platform checkboxes."""
    trigger_id = body.get("trigger_id")
    thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
    channel_id = body.get("channel", {}).get("id", SLACK_CHANNEL_ID)

    post = get_post_data(option_index)
    if not post:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=":warning: Could not load post data. Try running content-machine.py again.",
        )
        return

    short_text = post.get("short", "")
    long_text = post.get("long", "")

    # Store context in private_metadata for the view submission handler
    metadata = json.dumps({
        "option_index": option_index,
        "thread_ts": thread_ts,
        "channel_id": channel_id,
    })

    try:
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "post_approval_modal",
                "private_metadata": metadata,
                "title": {"type": "plain_text", "text": f"Post Option {option_index + 1}"},
                "submit": {"type": "plain_text", "text": "Post Now"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "short_text_block",
                        "label": {"type": "plain_text", "text": "X/Twitter & Bluesky Text (max 280 chars)"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "short_text",
                            "multiline": True,
                            "initial_value": short_text,
                            "max_length": 280,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "long_text_block",
                        "label": {"type": "plain_text", "text": "Instagram & Facebook Text"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "long_text",
                            "multiline": True,
                            "initial_value": long_text,
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "platforms_block",
                        "label": {"type": "plain_text", "text": "Post to these platforms:"},
                        "element": {
                            "type": "checkboxes",
                            "action_id": "platforms",
                            "initial_options": [
                                {"text": {"type": "plain_text", "text": "X (Twitter)"}, "value": "twitter"},
                                {"text": {"type": "plain_text", "text": "Instagram"}, "value": "instagram"},
                                {"text": {"type": "plain_text", "text": "TikTok"}, "value": "tiktok"},
                                {"text": {"type": "plain_text", "text": "Facebook"}, "value": "facebook"},
                                {"text": {"type": "plain_text", "text": "YouTube"}, "value": "youtube"},
                                {"text": {"type": "plain_text", "text": "Pinterest"}, "value": "pinterest"},
                                {"text": {"type": "plain_text", "text": "Bluesky"}, "value": "bluesky"},
                            ],
                            "options": [
                                {"text": {"type": "plain_text", "text": "X (Twitter)"}, "value": "twitter"},
                                {"text": {"type": "plain_text", "text": "Instagram"}, "value": "instagram"},
                                {"text": {"type": "plain_text", "text": "TikTok"}, "value": "tiktok"},
                                {"text": {"type": "plain_text", "text": "Facebook"}, "value": "facebook"},
                                {"text": {"type": "plain_text", "text": "YouTube"}, "value": "youtube"},
                                {"text": {"type": "plain_text", "text": "Pinterest"}, "value": "pinterest"},
                                {"text": {"type": "plain_text", "text": "Bluesky"}, "value": "bluesky"},
                            ],
                        },
                    },
                ],
            },
        )
        log.info(f"Opened edit modal for option {option_index + 1}")
    except Exception as e:
        log.error(f"Failed to open modal: {e}")


# ---------------------------------------------------------------------------
# MODAL SUBMISSION HANDLER
# ---------------------------------------------------------------------------
# Debounce: track recent approvals to prevent duplicate posts
_recent_approvals = {}  # key: (thread_ts, option_index) -> timestamp
DEBOUNCE_SECONDS = 60


@app.view("post_approval_modal")
def handle_modal_submit(ack, body, view, client):
    """Handle the modal submission: post to selected platforms."""
    ack()

    # Extract form values
    values = view.get("state", {}).get("values", {})
    short_text = values.get("short_text_block", {}).get("short_text", {}).get("value", "")
    long_text = values.get("long_text_block", {}).get("long_text", {}).get("value", "")
    platform_options = values.get("platforms_block", {}).get("platforms", {}).get("selected_options", [])
    selected_platforms = [p["value"] for p in platform_options]

    # Get metadata
    metadata = json.loads(view.get("private_metadata", "{}"))
    option_index = metadata.get("option_index", 0)
    thread_ts = metadata.get("thread_ts")
    channel_id = metadata.get("channel_id", SLACK_CHANNEL_ID)

    user = body.get("user", {}).get("username", "Unknown")
    media_path, media_type = get_media_path(option_index)

    # Debounce: skip if the same option was already posted within DEBOUNCE_SECONDS
    dedup_key = (thread_ts, option_index)
    now = datetime.now(timezone.utc).timestamp()
    last_posted = _recent_approvals.get(dedup_key)
    if last_posted and (now - last_posted) < DEBOUNCE_SECONDS:
        log.warning(f"Duplicate approval blocked: option {option_index + 1} by {user} (posted {now - last_posted:.0f}s ago)")
        try:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Duplicate approval detected and blocked. This option was already posted {int(now - last_posted)} seconds ago.",
            )
        except Exception:
            pass
        return
    _recent_approvals[dedup_key] = now

    log.info(f"Approved by {user}: option {option_index + 1}, platforms: {selected_platforms}, media: {media_type}")

    # Post to each platform
    results = {}
    # Twitter posts directly via Tweepy API
    if "twitter" in selected_platforms:
        try:
            results["twitter"] = post_to_twitter(short_text, media_path, media_type)
        except Exception as e:
            results["twitter"] = {"success": False, "error": str(e)}
            log.error(f"Error posting to Twitter: {e}")

    # YouTube posts directly via YouTube Data API (GHL OAuth tokens expire frequently)
    if "youtube" in selected_platforms:
        try:
            results["youtube"] = post_to_youtube(short_text, long_text, media_path, media_type)
        except Exception as e:
            results["youtube"] = {"success": False, "error": str(e)}
            log.error(f"Error posting to YouTube: {e}")

    # All other platforms (Instagram, TikTok, Facebook, Pinterest, Bluesky) via GHL Social Planner
    ghl_platforms = [p for p in selected_platforms if p not in ("twitter", "youtube")]
    if ghl_platforms:
        try:
            ghl_result = post_to_ghl(long_text, media_path, media_type, ghl_platforms)
            # Spread GHL results back into per-platform results dict
            for platform in ghl_platforms:
                results[platform] = ghl_result.get(platform, {"success": False, "error": "No result"})
        except Exception as e:
            for platform in ghl_platforms:
                results[platform] = {"success": False, "error": str(e)}
            log.error(f"Error posting to GHL platforms {ghl_platforms}: {e}")

    # Send confirmation to Slack thread
    send_confirmation(client, channel_id, thread_ts, short_text, results, user, option_index)

    # Update metadata file with approval info
    try:
        meta = load_latest_meta()
        if meta:
            meta["approved_at"] = datetime.now().isoformat()
            meta["approved_by"] = user
            meta["approved_option"] = option_index
            meta["approved_text_short"] = short_text
            meta["approved_text_long"] = long_text
            meta["platforms_posted"] = results
            with open(META_FILE, "w") as f:
                json.dump(meta, f, indent=2)
    except Exception as e:
        log.error(f"Failed to update metadata: {e}")


# ---------------------------------------------------------------------------
# PLATFORM POSTING
# ---------------------------------------------------------------------------

def _reencode_for_instagram(media_path):
    """Re-encode video with H.264/yuv420p/BT.709 for platform compatibility.
    Returns re-encoded tmp path, or original path if ffmpeg unavailable."""
    import subprocess, tempfile

    ffmpeg_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "nurture-videos",
        "node_modules", "ffmpeg-static", "ffmpeg.exe"
    ))

    with tempfile.NamedTemporaryFile(suffix="-enc.mp4", delete=False) as tmp:
        tmp_path = tmp.name

    if os.path.exists(ffmpeg_path):
        try:
            subprocess.run([
                ffmpeg_path, "-i", media_path,
                "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
                "-pix_fmt", "yuv420p",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-y", tmp_path
            ], check=True, capture_output=True)
            log.info(f"Re-encoded video to: {tmp_path}")
            return tmp_path
        except Exception as e:
            log.warning(f"ffmpeg re-encode failed: {e}, using original")
            return media_path
    else:
        log.warning("ffmpeg not found, using original video")
        return media_path


def post_to_ghl(text, media_path=None, media_type="image", platforms=None):
    """Post to multiple platforms via GHL Social Planner in one API call.
    Returns a dict of {platform: result} for each requested platform."""
    if not GHL_API_TOKEN or not GHL_LOCATION_ID:
        return {p: {"success": False, "error": "GHL credentials not configured"} for p in (platforms or [])}

    platforms = platforms or list(GHL_ACCOUNT_IDS.keys())
    account_ids = [GHL_ACCOUNT_IDS[p] for p in platforms if p in GHL_ACCOUNT_IDS]
    unknown = [p for p in platforms if p not in GHL_ACCOUNT_IDS]
    if unknown:
        log.warning(f"Unknown GHL platforms (skipping): {unknown}")

    if not account_ids:
        return {p: {"success": False, "error": "No GHL account found"} for p in platforms}

    # GHL requires top-level "type": reel for video, post for images
    post_type = "reel" if media_type == "video" else "post"

    payload = {
        "userId": GHL_USER_ID,
        "type": post_type,
        "accountIds": account_ids,
        "summary": text,
        "status": "published",
        "media": [],
    }

    # Upload media to GHL's own CDN (assets.cdn.filesafe.space) — required for TikTok domain verification
    if media_path and os.path.exists(media_path):
        if media_type == "video":
            log.info(f"Uploading video to GHL media library...")
            # Re-encode for compatibility first
            encoded_path = _reencode_for_instagram(media_path)
            upload_path = encoded_path if encoded_path else media_path
            with open(upload_path, "rb") as f:
                upload_resp = requests.post(
                    "https://services.leadconnectorhq.com/medias/upload-file",
                    headers={"Authorization": f"Bearer {GHL_API_TOKEN}", "Version": "2021-07-28"},
                    files={"file": (os.path.basename(upload_path), f, "video/mp4")},
                    data={"fileType": "video/mp4", "name": os.path.basename(upload_path)},
                )
            upload_data = upload_resp.json()
            cdn_url = upload_data.get("url")
            if cdn_url:
                log.info(f"GHL media upload succeeded: {cdn_url}")
                payload["media"] = [{"url": cdn_url, "type": "video/mp4"}]
            else:
                log.warning(f"GHL media upload failed: {upload_data}, posting text only")
        elif media_type == "image":
            import base64
            with open(media_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            upload_resp = requests.post(
                "https://services.leadconnectorhq.com/medias/upload-file",
                headers={"Authorization": f"Bearer {GHL_API_TOKEN}", "Version": "2021-07-28"},
                json={"name": os.path.basename(media_path), "base64": b64, "fileType": "image/png"},
            )
            upload_data = upload_resp.json()
            cdn_url = upload_data.get("url") or upload_data.get("fileUrl")
            if cdn_url:
                payload["media"] = [{"url": cdn_url, "type": "image/png"}]
            else:
                log.warning(f"GHL image upload failed: {upload_data}, posting text only")

    log.info(f"Posting to GHL platforms: {platforms}")
    resp = requests.post(
        f"https://services.leadconnectorhq.com/social-media-posting/{GHL_LOCATION_ID}/posts",
        headers={"Authorization": f"Bearer {GHL_API_TOKEN}", "Version": "2021-07-28", "Content-Type": "application/json"},
        json=payload,
    )
    data = resp.json()
    log.info(f"GHL response: {data}")

    # Build per-platform results
    per_platform = {}
    if data.get("post") or data.get("id") or data.get("success"):
        post_id = data.get("post", {}).get("id") or data.get("id", "")
        post_url = f"https://app.gohighlevel.com/social-planner" if not post_id else f"https://app.gohighlevel.com/social-planner/post/{post_id}"
        for p in platforms:
            per_platform[p] = {"success": True, "url": post_url}
        log.info(f"GHL post created: {post_url}")
    else:
        error = data.get("message") or data.get("error") or str(data)
        log.error(f"GHL post failed: {error}")
        for p in platforms:
            per_platform[p] = {"success": False, "error": error}

    return per_platform


def post_to_twitter(text, media_path=None, media_type="image"):
    """Post to X/Twitter using Tweepy v2 with image or video upload."""
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        return {"success": False, "error": "Twitter credentials not configured"}

    try:
        # v1.1 auth for media upload (v2 doesn't support media upload directly)
        auth = tweepy.OAuth1UserHandler(
            TWITTER_API_KEY, TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET,
        )
        api_v1 = tweepy.API(auth)

        # v2 client for creating tweet
        client_v2 = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET,
        )

        media_id = None
        if media_path and os.path.exists(media_path):
            if media_type == "video":
                # Chunked upload for video via v1.1
                media = api_v1.chunked_upload(
                    filename=media_path,
                    media_category="tweet_video",
                )
                media_id = media.media_id
                log.info(f"Uploaded video to Twitter: media_id={media_id}")
            else:
                # Simple upload for images via v1.1
                media = api_v1.media_upload(filename=media_path)
                media_id = media.media_id
                log.info(f"Uploaded image to Twitter: media_id={media_id}")

        # Create tweet via v2
        kwargs = {"text": text}
        if media_id:
            kwargs["media_ids"] = [media_id]

        response = client_v2.create_tweet(**kwargs)
        tweet_id = response.data.get("id")
        tweet_url = f"https://x.com/i/web/status/{tweet_id}"

        log.info(f"Posted to Twitter: {tweet_url}")
        return {"success": True, "url": tweet_url, "tweet_id": tweet_id}

    except Exception as e:
        log.error(f"Twitter post error: {e}")
        return {"success": False, "error": str(e)}


def post_to_youtube(short_text, long_text, media_path=None, media_type="video"):
    """Upload a video as a YouTube Short."""
    if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        return {"success": False, "error": "YouTube credentials not configured"}

    if media_type != "video" or not media_path or not os.path.exists(media_path):
        return {"success": False, "error": "No video file available for YouTube upload"}

    try:
        credentials = Credentials(
            token=None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )

        youtube = build("youtube", "v3", credentials=credentials)

        # Use short text as title (truncate to 100 chars for YouTube limit)
        # Strip hashtags from title, put them in description
        title_text = re.sub(r'#\w+', '', short_text).strip()
        if len(title_text) > 100:
            title_text = title_text[:97] + "..."

        # Build description: long text + Shorts hashtag
        description = long_text if long_text else short_text
        if "#Shorts" not in description:
            description += "\n\n#Shorts"

        body = {
            "snippet": {
                "title": title_text,
                "description": description,
                "tags": ["Toronto Airbnb", "Airbnb Host", "Short Term Rental", "Toronto", "Airbnb Tips"],
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            media_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info(f"YouTube upload progress: {int(status.progress() * 100)}%")

        video_id = response["id"]
        video_url = f"https://youtube.com/shorts/{video_id}"

        log.info(f"Posted to YouTube: {video_url}")
        return {"success": True, "url": video_url, "video_id": video_id}

    except Exception as e:
        log.error(f"YouTube post error: {e}")
        return {"success": False, "error": str(e)}


def post_to_facebook(text, media_path=None, media_type="image", public_video_url=None):
    """Post to Facebook Page. Supports video, image, or text-only posts."""
    if not all([META_PAGE_ACCESS_TOKEN, META_PAGE_ID]):
        return {"success": False, "error": "Facebook credentials not configured"}

    try:
        if media_type == "video" and (media_path or public_video_url):
            # Get a public URL for the video
            video_url = public_video_url
            if not video_url and media_path and os.path.exists(media_path):
                log.info("Generating public URL for Facebook video...")
                video_url = _get_public_video_url(media_path)

            if video_url:
                # Post as a feed link — uses pages_manage_posts (no special video permission needed)
                feed_url = f"https://graph.facebook.com/v21.0/{META_PAGE_ID}/feed"
                resp = requests.post(feed_url, data={
                    "message": text,
                    "link": video_url,
                    "access_token": META_PAGE_ACCESS_TOKEN,
                })
                data = resp.json()
                if "id" in data:
                    post_id = data["id"]
                    post_url = f"https://www.facebook.com/{post_id.replace('_', '/posts/')}"
                    log.info(f"Posted to Facebook feed: {post_url}")
                    return {"success": True, "url": post_url, "post_id": post_id}
                else:
                    error = data.get("error", {}).get("message", str(data))
                    log.error(f"Facebook feed post error: {error}")
                    return {"success": False, "error": error}
            else:
                return {"success": False, "error": "No video source available for Facebook"}

        elif media_path and os.path.exists(media_path) and media_type == "image":
            # Image upload
            url = f"https://graph.facebook.com/v21.0/{META_PAGE_ID}/photos"
            with open(media_path, "rb") as f:
                resp = requests.post(url, data={
                    "message": text,
                    "access_token": META_PAGE_ACCESS_TOKEN,
                }, files={"source": (os.path.basename(media_path), f, "image/png")})

            data = resp.json()
            if "id" in data:
                log.info(f"Posted image to Facebook: {data['id']}")
                return {"success": True, "url": f"https://www.facebook.com/{data['id']}", "post_id": data["id"]}
            else:
                error = data.get("error", {}).get("message", str(data))
                return {"success": False, "error": error}

        else:
            # Text-only post
            url = f"https://graph.facebook.com/v21.0/{META_PAGE_ID}/feed"
            resp = requests.post(url, data={
                "message": text,
                "access_token": META_PAGE_ACCESS_TOKEN,
            })
            data = resp.json()
            if "id" in data:
                log.info(f"Posted text to Facebook: {data['id']}")
                return {"success": True, "url": f"https://www.facebook.com/{data['id']}", "post_id": data["id"]}
            else:
                error = data.get("error", {}).get("message", str(data))
                return {"success": False, "error": error}

    except Exception as e:
        log.error(f"Facebook post error: {e}")
        return {"success": False, "error": str(e)}


def post_to_instagram(text, media_path=None, media_type="image"):
    """Post to Instagram as a Reel (video) or photo."""
    if not all([META_PAGE_ACCESS_TOKEN, INSTAGRAM_USER_ID]):
        return {"success": False, "error": "Instagram credentials not configured"}

    if not media_path or not os.path.exists(media_path):
        return {"success": False, "error": "Media file required for Instagram"}

    try:
        if media_type == "video":
            # Step 1: Re-encode and get a public URL via catbox.moe
            video_url = _get_public_video_url(media_path)
            if not video_url:
                return {"success": False, "error": "Failed to get public video URL for Instagram"}

            # Step 2: Create media container for Reel
            container_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{INSTAGRAM_USER_ID}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": text,
                    "access_token": META_PAGE_ACCESS_TOKEN,
                }
            ).json()

            if "id" not in container_resp:
                error = container_resp.get("error", {}).get("message", str(container_resp))
                log.error(f"Instagram container error: {error}")
                return {"success": False, "error": error}

            container_id = container_resp["id"]
            log.info(f"Instagram container created: {container_id}")

            # Step 3: Poll until container is ready
            for attempt in range(40):
                time.sleep(5)
                status_resp = requests.get(
                    f"https://graph.facebook.com/v21.0/{container_id}",
                    params={"fields": "status_code,status", "access_token": META_PAGE_ACCESS_TOKEN}
                ).json()
                status_code = status_resp.get("status_code", "")
                log.info(f"Instagram container status: {status_code} (attempt {attempt + 1})")
                if status_code == "FINISHED":
                    break
                elif status_code == "ERROR":
                    status_detail = status_resp.get("status", "unknown error")
                    log.error(f"Instagram processing error: {status_detail}")
                    return {"success": False, "error": f"Video processing failed: {status_detail}"}
            else:
                return {"success": False, "error": "Instagram video processing timed out"}

            # Step 4: Publish
            publish_resp = requests.post(
                f"https://graph.facebook.com/v21.0/{INSTAGRAM_USER_ID}/media_publish",
                data={"creation_id": container_id, "access_token": META_PAGE_ACCESS_TOKEN},
            ).json()

            if "id" in publish_resp:
                media_id = publish_resp["id"]
                ig_url = f"https://www.instagram.com/reel/{media_id}/"
                log.info(f"Posted Reel to Instagram: {ig_url}")
                return {"success": True, "url": ig_url, "media_id": media_id, "public_video_url": video_url}
            else:
                error = publish_resp.get("error", {}).get("message", str(publish_resp))
                return {"success": False, "error": error}

        else:
            # Image post
            image_url = _upload_image_for_instagram(media_path)
            if not image_url:
                return {"success": False, "error": "Failed to get public image URL for Instagram"}

            url = f"https://graph.facebook.com/v21.0/{INSTAGRAM_USER_ID}/media"
            resp = requests.post(url, data={
                "image_url": image_url,
                "caption": text,
                "access_token": META_PAGE_ACCESS_TOKEN,
            })
            data = resp.json()
            if "id" not in data:
                error = data.get("error", {}).get("message", str(data))
                return {"success": False, "error": error}

            container_id = data["id"]

            # Publish
            publish_url = f"https://graph.facebook.com/v21.0/{INSTAGRAM_USER_ID}/media_publish"
            publish_resp = requests.post(publish_url, data={
                "creation_id": container_id,
                "access_token": META_PAGE_ACCESS_TOKEN,
            })
            publish_data = publish_resp.json()
            if "id" in publish_data:
                media_id = publish_data["id"]
                log.info(f"Posted image to Instagram: {media_id}")
                return {"success": True, "url": f"https://www.instagram.com/p/{media_id}/", "media_id": media_id}
            else:
                error = publish_data.get("error", {}).get("message", str(publish_data))
                return {"success": False, "error": error}

    except Exception as e:
        log.error(f"Instagram post error: {e}")
        return {"success": False, "error": str(e)}


def _get_public_video_url(media_path):
    """Re-encode video with BT.709 color space and upload to catbox.moe for a public URL.
    Instagram requires a publicly accessible video URL with proper H.264/yuv420p encoding."""
    import subprocess, tempfile

    try:
        # Re-encode to yuv420p + BT.709 if needed (Instagram requires standard color space)
        ffmpeg_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "nurture-videos", "node_modules", "ffmpeg-static", "ffmpeg.exe"
        )
        ffmpeg_path = os.path.normpath(ffmpeg_path)

        suffix = os.path.splitext(media_path)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(suffix="-ig.mp4", delete=False) as tmp:
            tmp_path = tmp.name

        if os.path.exists(ffmpeg_path):
            log.info("Re-encoding video for Instagram compatibility...")
            subprocess.run([
                ffmpeg_path, "-i", media_path,
                "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
                "-pix_fmt", "yuv420p",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-y", tmp_path
            ], check=True, capture_output=True)
            upload_path = tmp_path
        else:
            log.warning("ffmpeg not found, uploading original (may cause IG format errors)")
            upload_path = media_path

        # Try multiple upload hosts in order until one works
        public_url = None

        # Host 1: catbox.moe
        try:
            log.info("Uploading video to catbox.moe...")
            result = subprocess.run([
                "curl", "-s", "-F", "reqtype=fileupload", "-F", f"fileToUpload=@{upload_path}",
                "https://catbox.moe/user/api.php"
            ], capture_output=True, text=True, timeout=120)
            url = result.stdout.strip()
            if url and "catbox.moe" in url:
                public_url = url
                log.info(f"catbox.moe upload succeeded: {public_url}")
        except Exception as e:
            log.warning(f"catbox.moe failed: {e}")

        # Host 2: 0x0.st
        if not public_url:
            try:
                log.info("Trying 0x0.st...")
                result = subprocess.run([
                    "curl", "-s", "-F", f"file=@{upload_path}",
                    "https://0x0.st"
                ], capture_output=True, text=True, timeout=120)
                url = result.stdout.strip()
                if url and url.startswith("http"):
                    public_url = url
                    log.info(f"0x0.st upload succeeded: {public_url}")
            except Exception as e:
                log.warning(f"0x0.st failed: {e}")

        # Host 3: tmpfiles.org
        if not public_url:
            try:
                log.info("Trying tmpfiles.org...")
                result = subprocess.run([
                    "curl", "-s", "-F", f"file=@{upload_path}",
                    "https://tmpfiles.org/api/v1/upload"
                ], capture_output=True, text=True, timeout=120)
                import json as _json
                data = _json.loads(result.stdout.strip())
                url = data.get("data", {}).get("url", "")
                # tmpfiles returns https://tmpfiles.org/XXXXX, convert to direct dl link
                if url:
                    url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    public_url = url
                    log.info(f"tmpfiles.org upload succeeded: {public_url}")
            except Exception as e:
                log.warning(f"tmpfiles.org failed: {e}")

        if tmp_path != media_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

        if public_url:
            return public_url

        log.error("All public video upload hosts failed")
        return None

    except Exception as e:
        log.error(f"Public video URL failed: {e}")
        return None


def _upload_image_for_instagram(media_path):
    """Upload image to Facebook Page (unlisted) and return the hosted URL for Instagram."""
    try:
        url = f"https://graph.facebook.com/v21.0/{META_PAGE_ID}/photos"
        with open(media_path, "rb") as f:
            resp = requests.post(url, data={
                "access_token": META_PAGE_ACCESS_TOKEN,
                "published": "false",
            }, files={"source": (os.path.basename(media_path), f, "image/png")})

        data = resp.json()
        if "id" not in data:
            log.error(f"Failed to upload image for IG: {data}")
            return None

        photo_id = data["id"]
        info_resp = requests.get(
            f"https://graph.facebook.com/v21.0/{photo_id}",
            params={"fields": "images", "access_token": META_PAGE_ACCESS_TOKEN}
        ).json()

        images = info_resp.get("images", [])
        if images:
            return images[0].get("source")

        return None

    except Exception as e:
        log.error(f"Image upload for Instagram failed: {e}")
        return None


# ---------------------------------------------------------------------------
# CONFIRMATION MESSAGE
# ---------------------------------------------------------------------------
def send_confirmation(client, channel_id, thread_ts, text, results, user, option_index):
    """Send a confirmation message to Slack (top-level + thread) with per-platform status and links."""
    icons = {"twitter": ":bird:", "instagram": ":camera:", "tiktok": ":musical_note:", "facebook": ":blue_book:",
             "youtube": ":youtube:", "pinterest": ":pushpin:", "bluesky": ":cloud:"}

    successes = {p: r for p, r in results.items() if r.get("success")}
    failures = {p: r for p, r in results.items() if not r.get("success")}

    # Build platform status lines
    platform_lines = []
    for platform, result in results.items():
        icon = icons.get(platform, ":globe_with_meridians:")
        if result.get("success"):
            url = result.get("url", "")
            link_text = f"<{url}|View Post>" if url else "Posted"
            platform_lines.append(f"{icon} *{platform.title()}*  :white_check_mark:  {link_text}")
        else:
            error = result.get("error", result.get("message", "Unknown error"))
            # Truncate long error messages
            if len(error) > 120:
                error = error[:117] + "..."
            platform_lines.append(f"{icon} *{platform.title()}*  :x:  {error}")

    # Header
    if not failures:
        header = f":white_check_mark:  *Content posted to {len(successes)} platform(s)!*"
    elif not successes:
        header = f":rotating_light:  *All {len(failures)} platform(s) FAILED*"
    else:
        header = f":warning:  *Posted to {len(successes)}, failed on {len(failures)} platform(s)*"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Posting Results", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(platform_lines)}},
        {"type": "divider"},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Approved by @{user}  |  Option {option_index + 1}  |  `{text[:80]}{'...' if len(text) > 80 else ''}`"}
        ]},
    ]

    fallback_text = f"Posted to {len(successes)}/{len(results)} platforms. " + ", ".join(
        f"{p}: {'OK' if r.get('success') else 'FAILED'}" for p, r in results.items()
    )

    try:
        # Send as top-level message (not buried in thread) so it's easy to see
        client.chat_postMessage(
            channel=channel_id,
            text=fallback_text,
            blocks=blocks,
            unfurl_links=False,
        )
        # Also post a brief summary in the original thread for context
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=fallback_text,
        )
    except Exception as e:
        log.error(f"Failed to send confirmation: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Nurture Content Bot starting (Socket Mode)")
    log.info(f"Listening for approval buttons in channel: {SLACK_CHANNEL_ID}")
    log.info("Press Ctrl+C to stop")
    log.info("=" * 60)

    if not SLACK_BOT_TOKEN:
        log.error("SLACK_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not SLACK_APP_TOKEN:
        log.error("SLACK_APP_TOKEN not set in .env")
        sys.exit(1)

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()


if __name__ == "__main__":
    main()
