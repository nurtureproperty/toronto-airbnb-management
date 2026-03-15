@echo off
cd /d "%~dp0\.."
python scripts/build-bot-knowledge.py
if %ERRORLEVEL% EQU 0 (
    cd /d "%~dp0\.."
    git add ghl-claude-server/bot-knowledge.md
    git commit -m "Auto-update bot knowledge base [weekly]"
    git push origin master
)
