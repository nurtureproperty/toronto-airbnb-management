"""Create the weekly pricing + listing optimization project assigned to Angelica."""
import sys, os, requests
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"c:\Users\jef_p\toronto-airbnb-management\.env")

T = os.getenv("NOTION_TOKEN")
H = {"Authorization": f"Bearer {T}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

PROJECT_LIST_DB = "b24ffa51-4302-4a76-8063-eed4318acff0"
ANGELICA_ID = "286d872b-594c-81f2-8019-00020f5c98d5"
PRICING_DASHBOARD_URL = "https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
CHECKLIST_TEMPLATE_URL = "https://www.notion.so/Weekly-Pricing-Checklist-Template-33909a91876281658937d6928771f214"
LISTING_OPT_QUICK_URL = "https://www.notion.so/Listing-Optimization-Quick-Checklist-33909a918762810686afd1785a932b41"
LISTING_OPT_FULL_URL = "https://www.notion.so/Listing-Optimization-What-To-Do-When-a-Listing-Isn-t-Getting-Bookings-33809a91876281a09d1ff9d4bbb3bb27"

today = date.today()
title = f"Weekly Pricing + Listing Optimization — {today.strftime('%b %d, %Y')}"

def h3(text):
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

def para(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

def para_linked(parts):
    """parts: list of (text, url_or_None) tuples"""
    rt = []
    for text, url in parts:
        item = {"type": "text", "text": {"content": text}}
        if url:
            item["text"]["link"] = {"url": url}
        rt.append(item)
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}

def todo(text):
    return {"object": "block", "type": "to_do",
            "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": False}}

children = [
    {"object": "block", "type": "heading_2",
     "heading_2": {"rich_text": [{"type": "text", "text": {"content": "This Week Pricing and Listing Optimization"}}]}},
    para("Complete the three sections below. Aim to finish by 12 PM Saturday. Mark each item as you go and set this task to Done when finished. The Saturday 7 AM pricing summary email has the data briefing for context."),
    h3("Section 1: Pricing Dashboard Review (34 items)"),
    para_linked([
        ("Open the ", None),
        ("Pricing Dashboard", PRICING_DASHBOARD_URL),
        (" and work through the full checklist below. Reference the ", None),
        ("Weekly Pricing Checklist Template", CHECKLIST_TEMPLATE_URL),
        (" for details. Log every change in the Price Change Log column on the Dashboard.", None),
    ]),
]

items = [
    "Open Hospitable and view the calendar",
    "Check the pricing dashboard for at-risk (yellow and red) properties",
    "Compare real occupancy to booking target (green, no color, light red, dark red)",
    "Complete the below tasks for each non-green property",
    "Scan next 4 weeks for awkward checkout days (Friday creating hard-to-fill weekend gaps)",
    "Identify orphan nights (1 to 3 night gaps between bookings)",
    "Flag gaps 7+ days out with no bookings (candidates for price drop or minimum stay reduction)",
    "Check if any days are stuck at minimum price and not booking (if yes, reduce minimum 10 to 15% OR reoptimize)",
    "Sample 3 similar listings in the same neighborhood (Airbnb or AirDNA)",
    "Note their nightly rate and compare to yours",
    "Confirm you are priced 20 to 30% higher than similar listings (the goal)",
    "Note any competitor deals or unusual pricing pulling bookings away",
    "Check the next 60 days for events, holidays, or long weekends",
    "Confirm premium is applied (TIFF, Taylor Swift, Nuit Blanche, Canadian holidays)",
    "Check for new event announcements since last week (Ticketmaster, city event calendars)",
    "Adjust minimum stay for major events (3 to 5 nights for TIFF, New Year)",
    "Adjacent factor is on for every listing",
    "Far-out premium is manually configured (not PriceLabs default)",
    "Gradual discount curve is set at the correct BLT",
    "Orphan night pricing is set (15 to 25% discount)",
    "Day-of-week adjustments are calibrated",
    "Minimum nights are consistent across Airbnb, Hospitable, and PriceLabs",
    "Over-occupied: raise base price by one increment (max +10% per week unless Algorithm Reset)",
    "Green: leave base price unchanged",
    "Light red: lower base price by one increment",
    "Dark red: lower base price by one to two increments OR reoptimize listing",
    "Check Airbnb Insights for views, wishlist saves, conversion rate per listing",
    "Note any listings with dropping view count (ranking issue, not pricing)",
    "Verify overall rating is at or above 4.95",
    "Check for new reviews under 5 stars that need responses",
    "Record changes in the Pricing Dashboard Price Change Log column",
    "Update Dashboard with new base prices and color codes",
    "Write Slack summary in general channel listing what changed this week",
    "Mark this Notion task as Done",
]
for item in items:
    children.append(todo(item))

children.append(h3("Section 2: Listing Optimization for Red Properties"))
children.append(para_linked([
    ("For every property currently marked 🔴 Needs Optimizing on the Dashboard, run through the ", None),
    ("Listing Optimization Quick Checklist", LISTING_OPT_QUICK_URL),
    (" (30 items). Log every change in the Listing Optimization Log column on the Dashboard. Full detailed SOP: ", None),
    ("Vacancy Troubleshooting SOP", LISTING_OPT_FULL_URL),
    (".", None),
]))
opt_items = [
    "List every 🔴 red property from the Dashboard here",
    "For each red property: screenshot current listing before any changes",
    "Work through the Quick Checklist for each red property",
    "Log each change in the Listing Optimization Log column with format: YYYY-MM-DD: what changed",
    "Wait 7 to 14 days before evaluating whether the change worked",
]
for item in opt_items:
    children.append(todo(item))

children.append(h3("Section 3: Daily Dashboard Check Commitment"))
children.append(para("Every shift day, open the Pricing Dashboard at shift start and handle any newly turned red properties. This is not one big weekly burst: it is a small 10-minute check every day."))
for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sun"]:
    children.append(todo(f"{day}: daily dashboard check done"))

print(f"Total blocks: {len(children)}")

payload = {
    "parent": {"database_id": PROJECT_LIST_DB},
    "properties": {
        "Project name": {"title": [{"text": {"content": title}}]},
        "Status": {"status": {"name": "Not Started"}},
        "Priority": {"select": {"name": "High"}},
        "Due By": {"date": {"start": today.isoformat()}},
        "Assignee": {"people": [{"id": ANGELICA_ID}]},
    },
    "children": children[:100],
}
r = requests.post("https://api.notion.com/v1/pages", headers=H, json=payload)
print(f"Create: {r.status_code}")
if r.status_code != 200:
    print(r.text[:500])
    sys.exit(1)
page = r.json()
page_id = page["id"]
print(f"URL: {page['url']}")

remaining = children[100:]
for i in range(0, len(remaining), 100):
    batch = remaining[i:i+100]
    r2 = requests.patch(f"https://api.notion.com/v1/blocks/{page_id}/children", headers=H, json={"children": batch})
    print(f"Batch {i//100+1}: {r2.status_code}")

print("DONE")
