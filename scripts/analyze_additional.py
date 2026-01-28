import csv
import statistics

# Read CSV data
listings = []
with open(r'C:\Users\jef_p\Downloads\Revenue Estimate - Listings (Toronto 2 bedroom).csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            revenue = float(row['Estimated Rental Revenue (Median)'])
            if revenue > 0:
                listings.append({
                    'revenue': revenue,
                    'pets': row['Pets Allowed'],
                    'smoking': row['Smoking Allowed'],
                    'cancellation': row['Cancellation Policy']
                })
        except:
            pass

print(f'Total listings with revenue: {len(listings)}')

# Pets analysis
pets_yes = [l['revenue'] for l in listings if l['pets'] == 'Yes']
pets_no = [l['revenue'] for l in listings if l['pets'] == 'No']
print(f'\nPETS ALLOWED:')
print(f'  Yes: avg ${statistics.mean(pets_yes):,.0f}/year (${statistics.mean(pets_yes)/12:,.0f}/mo), n={len(pets_yes)}')
print(f'  No:  avg ${statistics.mean(pets_no):,.0f}/year (${statistics.mean(pets_no)/12:,.0f}/mo), n={len(pets_no)}')
diff_pets = ((statistics.mean(pets_no) - statistics.mean(pets_yes)) / statistics.mean(pets_yes)) * 100
print(f'  Impact: No pets earns {diff_pets:+.1f}% vs pets allowed')

# Smoking analysis
smoking_yes = [l['revenue'] for l in listings if l['smoking'] == 'Yes']
smoking_no = [l['revenue'] for l in listings if l['smoking'] == 'No']
print(f'\nSMOKING ALLOWED:')
if smoking_yes:
    print(f'  Yes: avg ${statistics.mean(smoking_yes):,.0f}/year (${statistics.mean(smoking_yes)/12:,.0f}/mo), n={len(smoking_yes)}')
else:
    print(f'  Yes: n=0 (no listings allow smoking)')
print(f'  No:  avg ${statistics.mean(smoking_no):,.0f}/year (${statistics.mean(smoking_no)/12:,.0f}/mo), n={len(smoking_no)}')

# Cancellation Policy analysis
print(f'\nCANCELLATION POLICY:')
for policy in ['Flexible', 'Moderate', 'Strict', 'Firm']:
    policy_listings = [l['revenue'] for l in listings if l['cancellation'] == policy]
    if policy_listings:
        print(f'  {policy}: avg ${statistics.mean(policy_listings):,.0f}/year (${statistics.mean(policy_listings)/12:,.0f}/mo), n={len(policy_listings)}')
