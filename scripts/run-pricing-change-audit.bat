@echo off
cd /d C:\Users\jef_p\toronto-airbnb-management
python scripts/pricing-change-audit.py >> scripts/pricing-change-audit-log.txt 2>&1
