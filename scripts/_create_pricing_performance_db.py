"""Create Notion Pricing Performance database under the Pricing page."""
import sys, os, requests
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv(r'c:\Users\jef_p\toronto-airbnb-management\.env')

TOKEN = os.getenv('NOTION_TOKEN')
H = {'Authorization': f'Bearer {TOKEN}', 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json'}

# Find a parent - search for any workspace-level page to use as parent
sr = requests.post('https://api.notion.com/v1/search', headers=H, json={
    'filter': {'property': 'object', 'value': 'page'},
    'page_size': 20,
})
parent_page_id = None
for p in sr.json().get('results', []):
    if p.get('parent', {}).get('type') == 'workspace':
        parent_page_id = p['id']
        break

if not parent_page_id:
    print('No workspace page to parent under')
    sys.exit(1)

# Create a Pricing Performance parent page
pp = requests.post('https://api.notion.com/v1/pages', headers=H, json={
    'parent': {'page_id': parent_page_id},
    'icon': {'type': 'emoji', 'emoji': '📊'},
    'properties': {'title': [{'type': 'text', 'text': {'content': 'Pricing Performance'}}]},
})
if pp.status_code != 200:
    print(f'Create page failed: {pp.text[:400]}')
    sys.exit(1)
parent_id = pp.json()['id']
print(f'Parent page: {pp.json()["url"]}')

# Create the DB
schema = {
    'Week Ending': {'title': {}},
    'Property': {'rich_text': {}},
    'Scope': {
        'select': {
            'options': [
                {'name': 'Team Total', 'color': 'blue'},
                {'name': 'Per Property', 'color': 'gray'},
            ]
        }
    },
    'Wins': {'number': {'format': 'number'}},
    'Neutral': {'number': {'format': 'number'}},
    'Misses': {'number': {'format': 'number'}},
    'Total Changes': {'number': {'format': 'number'}},
    'Accuracy %': {'number': {'format': 'percent'}},
    'Notes': {'rich_text': {}},
}

payload = {
    'parent': {'page_id': parent_id},
    'title': [{'type': 'text', 'text': {'content': 'Weekly Pricing Performance'}}],
    'icon': {'type': 'emoji', 'emoji': '📈'},
    'properties': schema,
}

r = requests.post('https://api.notion.com/v1/databases', headers=H, json=payload)
print(f'DB create: {r.status_code}')
if r.status_code != 200:
    print(r.text[:600])
    sys.exit(1)

db = r.json()
print(f'DB ID: {db["id"]}')
print(f'URL: {db["url"]}')
