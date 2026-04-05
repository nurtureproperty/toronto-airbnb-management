@echo off
cd /d C:\Users\jef_p\toronto-airbnb-management
python scripts/weekly-pricing-review.py >> scripts/weekly-pricing-review-log.txt 2>&1
