@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:8766
.venv\Scripts\python.exe -m equity_research_agent.cli serve --port 8766
