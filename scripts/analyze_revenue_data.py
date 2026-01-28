import csv
import json
from collections import defaultdict
import statistics

# Read and parse CSV data
data = []
with open(r'C:\Users\jef_p\Downloads\Revenue Estimate - Listings (Toronto 2 bedroom).csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        data.append(row)

print(f"Total listings analyzed: {len(data)}")

# Filter to listings with actual revenue data (median > 0)
active_listings = [d for d in data if d['Estimated Rental Revenue (Median)'] and
                   d['Estimated Rental Revenue (Median)'] != '0' and
                   d['Estimated Rental Revenue (Median)'] != 'N/A']

print(f"Listings with revenue data: {len(active_listings)}")

# Helper function to safely convert to float
def safe_float(val):
    try:
        if val == 'N/A' or val == '' or val is None:
            return None
        return float(val)
    except:
        return None

# Helper function to safely convert to int
def safe_int(val):
    try:
        if val == 'N/A' or val == '' or val is None:
            return None
        return int(float(val))
    except:
        return None

# Parse data for analysis
parsed_data = []
for d in active_listings:
    revenue = safe_float(d['Estimated Rental Revenue (Median)'])
    if revenue is None or revenue == 0:
        continue

    parsed = {
        'title': d['Listing Title'],
        'revenue': revenue,
        'adr': safe_float(d['Estimated ADR']),
        'occupancy': safe_float(d['Estimated Adjusted Occupancy']),
        'active_days': safe_int(d['Active days']),
        'booking_window': safe_int(d['Booking Window']),
        'length_of_stay': safe_int(d['Length of Stay']),
        'dynamic_pricing': d['Dynamic Pricing'],
        'min_stay': safe_int(d['Min Stay']),
        'professionally_managed': d['Professionally Managed'],
        'bathrooms': safe_float(d['Bathrooms']),
        'max_guests': safe_int(d['Max Guests']),
        'listed_price': safe_float(d['Listed Price']),
        'listing_type': d['Listing Type'],
        'is_active': d['Is Active'],
        'economic_category': d['Economic Category'],
        'rating': safe_float(d['Rating']),
        'reviews': safe_int(d['Reviews']),
        'hot_tub': d['Hot Tub'] == 'Yes',
        'kitchen': d['Kitchen'] == 'Yes',
        'pool': d['Pool'] == 'Yes',
        'pets_allowed': d['Pets Allowed'] == 'Yes',
        'ac': d['Air Conditioning'] == 'Yes',
        'cleaning_fee': safe_float(d['Cleaning Fee']),
        'guest_favorite': d['Guest Favorite'] == '1',
        'cancellation_policy': d['Cancellation Policy'],
        'ev_charger': d['EV Charger'] == 'Yes',
    }
    parsed_data.append(parsed)

print(f"\nParsed {len(parsed_data)} listings for analysis")

# Basic statistics
revenues = [d['revenue'] for d in parsed_data]
print(f"\n=== REVENUE STATISTICS ===")
print(f"Mean monthly revenue: ${statistics.mean(revenues):,.0f}")
print(f"Median monthly revenue: ${statistics.median(revenues):,.0f}")
print(f"Min revenue: ${min(revenues):,.0f}")
print(f"Max revenue: ${max(revenues):,.0f}")
print(f"Std deviation: ${statistics.stdev(revenues):,.0f}")

# Revenue by percentile
sorted_revenues = sorted(revenues)
n = len(sorted_revenues)
print(f"\n=== REVENUE PERCENTILES ===")
print(f"10th percentile: ${sorted_revenues[int(n*0.1)]:,.0f}")
print(f"25th percentile: ${sorted_revenues[int(n*0.25)]:,.0f}")
print(f"50th percentile: ${sorted_revenues[int(n*0.5)]:,.0f}")
print(f"75th percentile: ${sorted_revenues[int(n*0.75)]:,.0f}")
print(f"90th percentile: ${sorted_revenues[int(n*0.9)]:,.0f}")

# 1. Dynamic Pricing Impact
print(f"\n=== DYNAMIC PRICING IMPACT ===")
dynamic_pricing_groups = defaultdict(list)
for d in parsed_data:
    if d['dynamic_pricing'] and d['dynamic_pricing'] != 'Unknown':
        dynamic_pricing_groups[d['dynamic_pricing']].append(d['revenue'])

for pricing_type, revs in sorted(dynamic_pricing_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{pricing_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 2. Professional Management Impact
print(f"\n=== PROFESSIONAL MANAGEMENT IMPACT ===")
mgmt_groups = defaultdict(list)
for d in parsed_data:
    if d['professionally_managed'] and d['professionally_managed'] != 'Unknown':
        mgmt_groups[d['professionally_managed']].append(d['revenue'])

for mgmt_type, revs in sorted(mgmt_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{mgmt_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 3. Min Stay Impact
print(f"\n=== MINIMUM STAY IMPACT ===")
min_stay_groups = defaultdict(list)
for d in parsed_data:
    min_stay = d['min_stay']
    if min_stay is not None:
        if min_stay == 1:
            group = '1 night'
        elif min_stay <= 3:
            group = '2-3 nights'
        elif min_stay <= 7:
            group = '4-7 nights'
        elif min_stay <= 28:
            group = '8-28 nights'
        else:
            group = '29+ nights'
        min_stay_groups[group].append(d['revenue'])

for stay_type, revs in sorted(min_stay_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{stay_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 4. Bathroom Count Impact
print(f"\n=== BATHROOM COUNT IMPACT ===")
bath_groups = defaultdict(list)
for d in parsed_data:
    baths = d['bathrooms']
    if baths is not None:
        if baths <= 1:
            group = '1 bath'
        elif baths <= 1.5:
            group = '1.5 baths'
        else:
            group = '2+ baths'
        bath_groups[group].append(d['revenue'])

for bath_type, revs in sorted(bath_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{bath_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 5. Guest Capacity Impact
print(f"\n=== GUEST CAPACITY IMPACT ===")
guest_groups = defaultdict(list)
for d in parsed_data:
    guests = d['max_guests']
    if guests is not None:
        if guests <= 3:
            group = '1-3 guests'
        elif guests <= 4:
            group = '4 guests'
        elif guests <= 5:
            group = '5 guests'
        elif guests <= 6:
            group = '6 guests'
        else:
            group = '7+ guests'
        guest_groups[group].append(d['revenue'])

for guest_type, revs in sorted(guest_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{guest_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 6. Economic Category Impact
print(f"\n=== ECONOMIC CATEGORY IMPACT ===")
econ_groups = defaultdict(list)
for d in parsed_data:
    if d['economic_category'] and d['economic_category'] != 'N/A':
        econ_groups[d['economic_category']].append(d['revenue'])

for econ_type, revs in sorted(econ_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{econ_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 7. Rating Impact
print(f"\n=== RATING IMPACT ===")
rating_groups = defaultdict(list)
for d in parsed_data:
    rating = d['rating']
    if rating is not None and rating > 0:
        if rating >= 4.9:
            group = '4.9-5.0'
        elif rating >= 4.7:
            group = '4.7-4.89'
        elif rating >= 4.5:
            group = '4.5-4.69'
        else:
            group = 'Below 4.5'
        rating_groups[group].append(d['revenue'])

for rating_type, revs in sorted(rating_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{rating_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 8. Review Count Impact
print(f"\n=== REVIEW COUNT IMPACT ===")
review_groups = defaultdict(list)
for d in parsed_data:
    reviews = d['reviews']
    if reviews is not None:
        if reviews == 0:
            group = 'No reviews'
        elif reviews <= 10:
            group = '1-10 reviews'
        elif reviews <= 30:
            group = '11-30 reviews'
        elif reviews <= 50:
            group = '31-50 reviews'
        elif reviews <= 100:
            group = '51-100 reviews'
        else:
            group = '100+ reviews'
        review_groups[group].append(d['revenue'])

for review_type, revs in sorted(review_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{review_type}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 9. Guest Favorite Badge Impact
print(f"\n=== GUEST FAVORITE BADGE IMPACT ===")
gf_yes = [d['revenue'] for d in parsed_data if d['guest_favorite']]
gf_no = [d['revenue'] for d in parsed_data if not d['guest_favorite']]
if len(gf_yes) >= 3 and len(gf_no) >= 3:
    print(f"With Guest Favorite: ${statistics.mean(gf_yes):,.0f} avg (n={len(gf_yes)})")
    print(f"Without Guest Favorite: ${statistics.mean(gf_no):,.0f} avg (n={len(gf_no)})")
    diff = statistics.mean(gf_yes) - statistics.mean(gf_no)
    pct = (diff / statistics.mean(gf_no)) * 100
    print(f"Difference: +${diff:,.0f} (+{pct:.1f}%)")

# 10. Amenities Impact
print(f"\n=== AMENITIES IMPACT ===")
amenities = ['hot_tub', 'pool', 'pets_allowed', 'ac', 'ev_charger']
amenity_names = ['Hot Tub', 'Pool', 'Pets Allowed', 'Air Conditioning', 'EV Charger']

for amenity, name in zip(amenities, amenity_names):
    with_amenity = [d['revenue'] for d in parsed_data if d[amenity]]
    without_amenity = [d['revenue'] for d in parsed_data if not d[amenity]]
    if len(with_amenity) >= 3 and len(without_amenity) >= 3:
        diff = statistics.mean(with_amenity) - statistics.mean(without_amenity)
        pct = (diff / statistics.mean(without_amenity)) * 100
        print(f"{name}: +${diff:,.0f} ({pct:+.1f}%) | With: ${statistics.mean(with_amenity):,.0f} (n={len(with_amenity)}) | Without: ${statistics.mean(without_amenity):,.0f} (n={len(without_amenity)})")

# 11. Cancellation Policy Impact
print(f"\n=== CANCELLATION POLICY IMPACT ===")
cancel_groups = defaultdict(list)
for d in parsed_data:
    if d['cancellation_policy']:
        cancel_groups[d['cancellation_policy']].append(d['revenue'])

for policy, revs in sorted(cancel_groups.items(), key=lambda x: statistics.mean(x[1]) if len(x[1]) > 0 else 0, reverse=True):
    if len(revs) >= 3:
        print(f"{policy}: ${statistics.mean(revs):,.0f} avg (n={len(revs)})")

# 12. Listed Price vs Revenue Analysis
print(f"\n=== LISTED PRICE VS REVENUE ===")
price_groups = defaultdict(list)
for d in parsed_data:
    price = d['listed_price']
    if price is not None and price > 0:
        if price < 150:
            group = '<$150/night'
        elif price < 250:
            group = '$150-249/night'
        elif price < 350:
            group = '$250-349/night'
        elif price < 450:
            group = '$350-449/night'
        else:
            group = '$450+/night'
        price_groups[group].append(d)

print("Listed Price | Avg Revenue | Avg Occupancy | Count")
for price_range in ['<$150/night', '$150-249/night', '$250-349/night', '$350-449/night', '$450+/night']:
    if price_range in price_groups:
        listings = price_groups[price_range]
        avg_rev = statistics.mean([l['revenue'] for l in listings])
        occupancies = [l['occupancy'] for l in listings if l['occupancy'] is not None and l['occupancy'] > 0]
        avg_occ = statistics.mean(occupancies) if occupancies else 0
        print(f"{price_range}: ${avg_rev:,.0f} | {avg_occ:.0f}% | n={len(listings)}")

# 13. ADR (Average Daily Rate) analysis
print(f"\n=== AVERAGE DAILY RATE (ADR) ANALYSIS ===")
adrs = [d['adr'] for d in parsed_data if d['adr'] is not None and d['adr'] > 0]
if adrs:
    print(f"Mean ADR: ${statistics.mean(adrs):,.0f}")
    print(f"Median ADR: ${statistics.median(adrs):,.0f}")
    sorted_adrs = sorted(adrs)
    n_adr = len(sorted_adrs)
    print(f"25th percentile ADR: ${sorted_adrs[int(n_adr*0.25)]:,.0f}")
    print(f"75th percentile ADR: ${sorted_adrs[int(n_adr*0.75)]:,.0f}")

# 14. Occupancy analysis
print(f"\n=== OCCUPANCY ANALYSIS ===")
occupancies = [d['occupancy'] for d in parsed_data if d['occupancy'] is not None and d['occupancy'] > 0]
if occupancies:
    print(f"Mean occupancy: {statistics.mean(occupancies):.0f}%")
    print(f"Median occupancy: {statistics.median(occupancies):.0f}%")

# 15. Top 10 Revenue Earners
print(f"\n=== TOP 10 REVENUE EARNERS ===")
top_10 = sorted(parsed_data, key=lambda x: x['revenue'], reverse=True)[:10]
for i, listing in enumerate(top_10, 1):
    print(f"{i}. ${listing['revenue']:,.0f} - {listing['title'][:50]}...")
    print(f"   ADR: ${listing['adr'] or 0:,.0f} | Occupancy: {listing['occupancy'] or 0:.0f}% | Rating: {listing['rating'] or 'N/A'} | Reviews: {listing['reviews'] or 0}")

# 16. Calculate correlation-like relationships
print(f"\n=== KEY INSIGHTS SUMMARY ===")

# Dynamic pricing advantage
dp_high = [d['revenue'] for d in parsed_data if d['dynamic_pricing'] == 'High']
dp_none = [d['revenue'] for d in parsed_data if d['dynamic_pricing'] == 'None']
if dp_high and dp_none:
    dp_advantage = ((statistics.mean(dp_high) - statistics.mean(dp_none)) / statistics.mean(dp_none)) * 100
    print(f"1. Dynamic Pricing (High vs None): +{dp_advantage:.1f}% revenue advantage")

# Guest Favorite advantage
if gf_yes and gf_no:
    gf_advantage = ((statistics.mean(gf_yes) - statistics.mean(gf_no)) / statistics.mean(gf_no)) * 100
    print(f"2. Guest Favorite Badge: +{gf_advantage:.1f}% revenue advantage")

# 2+ baths vs 1 bath
bath_2plus = [d['revenue'] for d in parsed_data if d['bathrooms'] is not None and d['bathrooms'] >= 2]
bath_1 = [d['revenue'] for d in parsed_data if d['bathrooms'] is not None and d['bathrooms'] <= 1]
if bath_2plus and bath_1:
    bath_advantage = ((statistics.mean(bath_2plus) - statistics.mean(bath_1)) / statistics.mean(bath_1)) * 100
    print(f"3. 2+ Bathrooms vs 1 Bath: +{bath_advantage:.1f}% revenue advantage")

# High reviews (100+) vs low reviews
high_reviews = [d['revenue'] for d in parsed_data if d['reviews'] is not None and d['reviews'] >= 100]
low_reviews = [d['revenue'] for d in parsed_data if d['reviews'] is not None and d['reviews'] < 10 and d['reviews'] >= 0]
if high_reviews and low_reviews:
    review_advantage = ((statistics.mean(high_reviews) - statistics.mean(low_reviews)) / statistics.mean(low_reviews)) * 100
    print(f"4. 100+ Reviews vs <10 Reviews: +{review_advantage:.1f}% revenue advantage")

# Export summary data for visualization
summary_data = {
    'total_listings': len(data),
    'active_listings': len(parsed_data),
    'revenue_stats': {
        'mean': round(statistics.mean(revenues), 0),
        'median': round(statistics.median(revenues), 0),
        'min': round(min(revenues), 0),
        'max': round(max(revenues), 0),
        'percentiles': {
            '10': round(sorted_revenues[int(n*0.1)], 0),
            '25': round(sorted_revenues[int(n*0.25)], 0),
            '50': round(sorted_revenues[int(n*0.5)], 0),
            '75': round(sorted_revenues[int(n*0.75)], 0),
            '90': round(sorted_revenues[int(n*0.9)], 0),
        }
    },
    'dynamic_pricing': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in dynamic_pricing_groups.items() if len(v) >= 3},
    'management': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in mgmt_groups.items() if len(v) >= 3},
    'bathrooms': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in bath_groups.items() if len(v) >= 3},
    'guests': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in guest_groups.items() if len(v) >= 3},
    'economic_category': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in econ_groups.items() if len(v) >= 3},
    'rating': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in rating_groups.items() if len(v) >= 3},
    'reviews': {k: {'mean': round(statistics.mean(v), 0), 'count': len(v)} for k, v in review_groups.items() if len(v) >= 3},
    'guest_favorite': {
        'with': round(statistics.mean(gf_yes), 0) if gf_yes else 0,
        'without': round(statistics.mean(gf_no), 0) if gf_no else 0,
        'count_with': len(gf_yes),
        'count_without': len(gf_no)
    }
}

# Save summary data to JSON
with open(r'C:\Users\jef_p\toronto-airbnb-management\scripts\revenue_analysis_results.json', 'w') as f:
    json.dump(summary_data, f, indent=2)

print(f"\n\nAnalysis complete. Results saved to revenue_analysis_results.json")
