"""Prepend a Start Here callout and clearer instructions to the existing Angelica weekly task."""
import sys, os, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"c:\Users\jef_p\toronto-airbnb-management\.env")

T = os.getenv("NOTION_TOKEN")
H = {"Authorization": f"Bearer {T}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

TASK_PAGE = "33909a91-8762-81f3-aa90-de3cc7711d43"  # The Angelica weekly task created earlier
PRICING_DASHBOARD_URL = "https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"

# Notion API doesn't support "prepend" directly; you can only append.
# Strategy: fetch existing blocks, delete them all, then re-create with new intro at top.
# Safer alternative: fetch existing, build full new block list, replace.
# But deletion of blocks is per-block via DELETE /blocks/{id}.
# Simpler: append the new intro at END so it's visible but below the checklist.
# Even simpler: fetch the existing first few blocks' content, then replace them by
# updating block text for the first heading + paragraph.

# Get first 5 blocks
r = requests.get(f"https://api.notion.com/v1/blocks/{TASK_PAGE}/children", headers=H, params={"page_size": 5})
if r.status_code != 200:
    print(f"Error: {r.text[:400]}")
    sys.exit(1)

blocks = r.json().get("results", [])
print(f"Found {len(blocks)} top blocks")
for b in blocks:
    btype = b.get("type")
    if btype in ("heading_2", "heading_3", "paragraph"):
        rt = b.get(btype, {}).get("rich_text", [])
        text = "".join([t.get("plain_text", "") for t in rt])[:80]
        print(f"  {b['id']}: {btype} | {text}")

# Approach: insert the new callout + instructions AFTER the heading_2 ("This Week Pricing and Listing Optimization")
# by using the "after" parameter on PATCH /blocks/{id}/children.
# That means: append new blocks as children of the page, placed after a specific block id.

# Find the heading_2 id
heading_id = None
for b in blocks:
    if b.get("type") == "heading_2":
        heading_id = b["id"]
        break

if not heading_id:
    print("No heading_2 found, aborting")
    sys.exit(1)

print(f"Anchor heading: {heading_id}")

# New intro blocks to insert after the heading
new_blocks = [
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "📊"},
            "color": "green_background",
            "rich_text": [
                {"type": "text", "text": {"content": "START HERE: Open the "}},
                {
                    "type": "text",
                    "text": {"content": "Pricing Dashboard Google Sheet", "link": {"url": PRICING_DASHBOARD_URL}},
                    "annotations": {"bold": True},
                },
                {"type": "text", "text": {"content": ". This is the primary tool for the review. All data, grades, recommendations, and change logs live here."}},
            ],
        },
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": "What You Need to Do"}}]},
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {"type": "text", "text": {"content": "Your goal this week: review every property in the Dashboard, act on anything yellow or red, log every change, and keep host payouts above their Minimum 30d Revenue targets. Follow the 5 steps below in order."}}
            ]
        },
    },
    {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Open the "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "Pricing Dashboard", "link": {"url": PRICING_DASHBOARD_URL}}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": ". Sort or filter the Grade column to surface 🔴 Needs Optimizing and 🟡 Slightly Under properties first. These are your priorities."}},
            ]
        },
    },
    {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Read the Smart Recommendation column "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "for each flagged property. It gives layered tactical advice based on BLT, occupancy trends, and historical data. Use it as your starting point."}},
            ]
        },
    },
    {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Check the Host Payout Last 30d column "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "for cells highlighted red or yellow. Red means payout is 85% or less of the client's Minimum 30d Revenue target. Fix these first, they cost real money."}},
            ]
        },
    },
    {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Work through the 34-item checklist below "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "(Section 1 of this task). Each item is a specific action: scan calendar gaps, compare to competitors, adjust base prices, verify customizations, etc. Tick each item as you complete it."}},
            ]
        },
    },
    {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Log every change in the Dashboard. "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "Base price changes go in the Price Change Log column (YYYY-MM-DD: $X to $Y, reason). Listing changes go in Listing Optimization Log. Without logs, the Friday audit cannot measure whether your decisions worked."}},
            ]
        },
    },
]

# Append with "after" parameter to place right after the heading
payload = {"children": new_blocks, "after": heading_id}
r = requests.patch(f"https://api.notion.com/v1/blocks/{TASK_PAGE}/children", headers=H, json=payload)
print(f"Insert: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500])
else:
    print(f"Inserted {len(new_blocks)} blocks after heading")
