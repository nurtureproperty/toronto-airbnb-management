@echo off
cd /d C:\Users\jef_p\toronto-airbnb-management
python scripts/update-pricing-dashboard.py >> scripts/update-pricing-dashboard-log.txt 2>&1
