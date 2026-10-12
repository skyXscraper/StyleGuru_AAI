@echo off
rem Starts StyleGuru and opens it in the browser.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --port 8000
