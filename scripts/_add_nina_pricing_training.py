"""Add pricing + listing optimization training tasks to Nina's Training Competency Tracker."""
import sys, os, requests
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(r"c:\Users\jef_p\toronto-airbnb-management\.env")

T = os.getenv("NOTION_TOKEN")
H = {"Authorization": f"Bearer {T}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
TRAINING_DB = "33809a91-8762-8177-9704-eca9189e40e1"

# Step 1: Add "Pricing & Optimization" as a new category option
r = requests.get(f"https://api.notion.com/v1/databases/{TRAINING_DB}", headers=H)
db = r.json()
existing_cats = db["properties"]["Category"]["multi_select"] if "multi_select" in db["properties"]["Category"] else db["properties"]["Category"]["select"]
print(f"Category type: {list(db['properties']['Category'].keys())}")

# It's a select, update options
current_options = db["properties"]["Category"]["select"]["options"]
new_name = "Pricing & Optimization"
if not any(o["name"] == new_name for o in current_options):
    new_options = [{"name": o["name"]} for o in current_options] + [{"name": new_name, "color": "purple"}]
    r = requests.patch(
        f"https://api.notion.com/v1/databases/{TRAINING_DB}",
        headers=H,
        json={"properties": {"Category": {"select": {"options": new_options}}}},
    )
    print(f"Added category: {r.status_code}")
else:
    print("Category already exists")

# Step 2: Add the training rows
PRICING_DASHBOARD_URL = "https://docs.google.com/spreadsheets/d/1Ok4Nshw5XBNM5pqNNhDkUtRN9LPrF1YrkoqH2qOap1A"
PRICING_SOP_V2_URL = "https://www.notion.so/Pricing-SOP-v2-Weekly-Pricing-Management-33909a9187628133ad39ee3c5ca842b6"
CHECKLIST_TEMPLATE_URL = "https://www.notion.so/Weekly-Pricing-Checklist-Template-33909a91876281658937d6928771f214"
LISTING_OPT_QUICK_URL = "https://www.notion.so/Listing-Optimization-Quick-Checklist-33909a918762810686afd1785a932b41"
LISTING_OPT_FULL_URL = "https://www.notion.so/Listing-Optimization-What-To-Do-When-a-Listing-Isn-t-Getting-Bookings-33809a91876281a09d1ff9d4bbb3bb27"

tasks = [
    {
        "task": "Daily Pricing Dashboard check at shift start",
        "priority": "Week 1",
        "sop_url": PRICING_DASHBOARD_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides",
        "notes": "Every shift, open the Pricing Dashboard and scan for any property that turned 🔴 red since yesterday. Address in order of severity. 10 minutes max.",
    },
    {
        "task": "Read and understand Pricing SOP v2",
        "priority": "Week 1",
        "sop_url": PRICING_SOP_V2_URL,
        "sop_status": "Complete (SOP + Loom)",
        "authority": "Nina decides",
        "notes": "Read through all 15 sections. Focus on: Market Percentile, BLT, Base/Min Price, Customizations, Algorithm Reset, Escalation rules.",
    },
    {
        "task": "Complete Weekly Pricing Review (34 items)",
        "priority": "Week 2",
        "sop_url": CHECKLIST_TEMPLATE_URL,
        "sop_status": "Complete (SOP + Loom)",
        "authority": "Nina decides + logs",
        "notes": "Every Saturday, a Notion task is auto-created with the full 34-item checklist. Complete it by 12 PM Saturday. Monday completion check verifies everything was done.",
    },
    {
        "task": "Log every base price change in Price Change Log column",
        "priority": "Week 2",
        "sop_url": PRICING_DASHBOARD_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides + logs",
        "notes": "Format: YYYY-MM-DD: $X to $Y (reason). Critical for the Friday audit to work.",
    },
    {
        "task": "Run Listing Optimization Quick Checklist on red properties",
        "priority": "Week 2",
        "sop_url": LISTING_OPT_QUICK_URL,
        "sop_status": "Complete (SOP + Loom)",
        "authority": "Nina decides + logs",
        "notes": "30-item condensed version. Use when a property turns 🔴 Needs Optimizing. Full SOP available for reference.",
    },
    {
        "task": "Update BLT Benchmark for each property from Airbnb Insights",
        "priority": "Week 2",
        "sop_url": PRICING_SOP_V2_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides",
        "notes": "Pull booking lead time from Airbnb Insights for each listing. Enter in BLT Benchmark column. Drives the grading system.",
    },
    {
        "task": "Apply pricing changes in PriceLabs or Hospitable",
        "priority": "Week 2",
        "sop_url": PRICING_SOP_V2_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides + logs",
        "notes": "Use whatever pricing tool is configured per property. Weekly changes up to 10%. Algorithm Reset only with Angelica approval.",
    },
    {
        "task": "Run Wishlist Mock Stay competitor comparison",
        "priority": "Week 3",
        "sop_url": LISTING_OPT_QUICK_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides",
        "notes": "Create a wishlist in Airbnb Guest App with your listing + 10 comparable properties. Compare total prices for 3-night weekend and 5-night midweek. Do this on red properties.",
    },
    {
        "task": "Document reoptimization attempts with before/after",
        "priority": "Week 3",
        "sop_url": LISTING_OPT_QUICK_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides + logs",
        "notes": "Screenshot the listing before changes, log in Listing Optimization Log column, wait 7-14 days, then evaluate.",
    },
    {
        "task": "Interpret Smart Recommendation column and act on it",
        "priority": "Month 2",
        "sop_url": PRICING_DASHBOARD_URL,
        "sop_status": "SOP Exists",
        "authority": "Nina decides + logs",
        "notes": "The Smart Recommendation column layers multiple signals (far-out premium, inverted BLT, mid-term dominance, etc.). Use it to decide specific actions, not just raise/lower.",
    },
]

# Add rows
for t in tasks:
    payload = {
        "parent": {"database_id": TRAINING_DB},
        "properties": {
            "Task": {"title": [{"text": {"content": t["task"]}}]},
            "Category": {"select": {"name": "Pricing & Optimization"}},
            "Priority": {"select": {"name": t["priority"]}},
            "SOP / Resource": {"url": t["sop_url"]},
            "SOP Status": {"select": {"name": t["sop_status"]}},
            "Competency": {"select": {"name": "Not Started"}},
            "Decision Authority": {"select": {"name": t["authority"]}},
            "Notes": {"rich_text": [{"text": {"content": t["notes"]}}]},
        },
    }
    r = requests.post("https://api.notion.com/v1/pages", headers=H, json=payload)
    status = "OK" if r.status_code == 200 else f"FAIL {r.status_code}"
    print(f"  {status}: {t['task']}")
    if r.status_code != 200:
        print(f"    {r.text[:300]}")

print("DONE")
