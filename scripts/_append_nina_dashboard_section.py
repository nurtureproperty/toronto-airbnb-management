"""Append Daily Dashboard Check section to Nina Onboarding Plan in Notion."""
import sys, os, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"c:\Users\jef_p\toronto-airbnb-management\.env")

T = os.getenv("NOTION_TOKEN")
H = {"Authorization": f"Bearer {T}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

PAGE = "33809a91-8762-81b6-86be-eb8daa4aa48e"
DASHBOARD_URL = "https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
SOP_URL = "https://www.notion.so/Pricing-SOP-v2-Weekly-Pricing-Management-33909a9187628133ad39ee3c5ca842b6"
CHECKLIST_URL = "https://www.notion.so/Weekly-Pricing-Checklist-Template-33909a91876281658937d6928771f214"
QUICK_URL = "https://www.notion.so/Listing-Optimization-Quick-Checklist-33909a918762810686afd1785a932b41"

def text_block(block_type, text):
    return {"object": "block", "type": block_type, block_type: {"rich_text": [{"type": "text", "text": {"content": text}}]}}

def linked_list(block_type, parts):
    rt = []
    for text, url, bold in parts:
        item = {"type": "text", "text": {"content": text}}
        if url:
            item["text"]["link"] = {"url": url}
        if bold:
            item["annotations"] = {"bold": True}
        rt.append(item)
    return {"object": "block", "type": block_type, block_type: {"rich_text": rt}}

blocks = [
    {"object": "block", "type": "divider", "divider": {}},
    text_block("heading_2", "Daily Pricing Dashboard Check"),
    text_block("paragraph", "Every shift day, open the Pricing Dashboard at shift start. This is the single most important daily habit for pricing management. Takes 10 minutes."),
    text_block("heading_3", "The Routine"),
    linked_list("numbered_list_item", [
        ("Open the ", None, False),
        ("Pricing Dashboard", DASHBOARD_URL, False),
        (" Google Sheet", None, False),
    ]),
    text_block("numbered_list_item", "Scan the Grade column for any property that is 🔴 Needs Optimizing"),
    text_block("numbered_list_item", "Compare vs yesterday: did any new properties turn red today?"),
    text_block("numbered_list_item", "Check the Host Payout Last 30d column for any red (below 85% of minimum) cells"),
    text_block("numbered_list_item", "Read the Smart Recommendation column for flagged properties"),
    text_block("numbered_list_item", "Address urgent issues (new reds) before guest messaging and other work"),
    text_block("numbered_list_item", "Log any changes made in the Price Change Log or Listing Optimization Log columns"),
    text_block("heading_3", "When to Act Immediately"),
    text_block("bulleted_list_item", "A property went from 🟢 to 🔴 overnight: urgent, investigate and act today"),
    text_block("bulleted_list_item", "Host Payout dropped from green to red on any property: urgent, requires pricing or listing action"),
    text_block("bulleted_list_item", "Smart Recommendation says reoptimize: start the Listing Optimization Quick Checklist same day"),
    text_block("bulleted_list_item", "Zero forward bookings for 7+ days: escalate to Angelica immediately"),
    text_block("heading_3", "Weekly Deep Dive"),
    text_block("paragraph", "Every Saturday, a Notion task is auto-created in the Project List with a 34-item weekly review checklist. The Saturday 7 AM pricing summary email has the briefing. Complete this by 12 PM Saturday."),
    text_block("paragraph", "Every Monday 8 AM, a completion check runs. It verifies the Saturday review was actually completed and at least one pricing action was taken on every red property. If any check fails, you and Angelica get an email."),
    text_block("heading_3", "Key Resources"),
    linked_list("bulleted_list_item", [
        ("Pricing Dashboard: ", None, True),
        ("Open sheet", DASHBOARD_URL, False),
    ]),
    linked_list("bulleted_list_item", [
        ("Pricing SOP v2: ", None, True),
        ("Read SOP", SOP_URL, False),
    ]),
    linked_list("bulleted_list_item", [
        ("Weekly Pricing Checklist Template: ", None, True),
        ("Full 34-item reference", CHECKLIST_URL, False),
    ]),
    linked_list("bulleted_list_item", [
        ("Listing Optimization Quick Checklist: ", None, True),
        ("30-item condensed version", QUICK_URL, False),
    ]),
]

r = requests.patch(f"https://api.notion.com/v1/blocks/{PAGE}/children", headers=H, json={"children": blocks})
print(f"Append: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500])
else:
    print(f"Added {len(blocks)} blocks to Nina Onboarding Plan")
