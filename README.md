# Baby Tracker

Baby activity tracker with a FastAPI backend, React frontend, SQLite storage, and Google Calendar sync.

## Current capabilities

- Household-scoped accounts with username/password sign-in
- Activity logging for bottle, food, diaper, sleep, breastfeeding, pump, and help
- Tap-to-log and hold-to-start/stop timer flows
- Service-account-managed Google Calendar provisioning and sharing
- Google Calendar write sync plus pull-based reconciliation back into SQLite
- Quick tools to simulate a sample day and delete the current local calendar day

## Repo layout

- `backend/` - FastAPI API, SQLite models, Google Calendar integration, tests
- `frontend/` - React + Vite UI

## Local development

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The API runs on `http://localhost:8090`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on `http://localhost:3005`.

## Tests

### Backend tests

```bash
cd backend
source venv/bin/activate
pytest -q
```

Live Google Calendar API tests are opt-in:

```bash
ENABLE_LIVE_CALENDAR_TESTS=1 pytest -q
```

### Frontend validation

```bash
cd frontend
npm run lint
npm run build
```

## Google Calendar notes

- The app is set up for one service-account-owned calendar per household account.
- Users can save share emails and enable sync from the Settings screen.
- Google pull sync runs automatically on a configurable interval in the frontend.
- The default poll interval is one hour via `VITE_GOOGLE_SYNC_POLL_INTERVAL_MS`.
