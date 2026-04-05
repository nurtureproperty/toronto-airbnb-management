@echo off
cd /d C:\Users\jef_p\toronto-airbnb-management
python scripts/weekly-pricing-summary-email.py >> scripts/weekly-pricing-summary-email-log.txt 2>&1
