# Copilot Instructions for `baby-tracker`

## Build, test, and lint

### Backend

From `backend/`:

```bash
./venv/bin/pytest -q
```

Run a single backend test:

```bash
./venv/bin/pytest -q tests/test_event_sync_flow.py::test_register_returns_session_and_profile
```

Live Google Calendar tests are opt-in:

```bash
ENABLE_LIVE_CALENDAR_TESTS=1 ./venv/bin/pytest -q
```

### Frontend

From `frontend/`:

```bash
npm run lint
npm run build
```

### Local app startup

From the repo root:

```bash
make dev
```

This runs the FastAPI backend against `backend/database-dev.db` and the Vite frontend dev server.

## High-level architecture

- The backend is a single FastAPI app in `backend/main.py`. It owns the SQLModel models, auth/session handling, tracker-button validation, event CRUD, calendar sync endpoints, and production static-file serving for the built frontend.
- Data is stored in SQLite. Local development defaults to `backend/database-dev.db`; deployed/container usage switches to `backend/database-prd.db` via env config.
- Authentication uses database-backed bearer sessions, not JWTs. Tokens returned to the frontend are hashed before storage in the `auth_session` table.
- Each account can have its own service-managed Google Calendar. Enabling sync provisions/shares the calendar, event writes are queued in `calendar_sync_job`, and a background worker in the API process retries Google writes with backoff.
- Google pull sync is separate from queued write sync: the frontend periodically calls `POST /calendar/sync`, and the backend reconciles Google changes back into local `event` rows using the stored sync token.
- The frontend is a Vite + React app with most application flow centralized in `frontend/src/App.tsx`. It handles auth, tracker interactions, settings, autosave for tracker buttons/theme palette, and periodic Google pull sync polling.
- Production is intended to be a single origin: the frontend is built into static assets, and FastAPI serves the built app when `FRONTEND_DIST_PATH` is configured.

## Key conventions

- Keep the Google sync flow consistent with the existing product behavior: save locally first, queue Google writes, retry automatically in the background, and surface sync state/messages in the UI. Do not introduce alternate sync flows for the same action.
- Tracker-button metadata is mirrored across backend and frontend. When changing default buttons, symbols, page limits, or color keys, update both `backend/main.py` and `frontend/src/trackerButtons.ts` so validation, labels, icons, emoji titles, and defaults stay aligned.
- Theme palette keys are also shared contract data. Keep backend `COLOR_PALETTE_KEYS` in sync with `frontend/src/theme.ts`.
- Activity types should be normalized through the existing alias helpers before branching on them. Backend calendar labeling and tracker-button lookup rely on normalized ids such as `diaper_pee`, `diaper_poop`, and `breastfeeding`.
- Event titles are not arbitrary strings: the backend derives them from the saved tracker-button config so calendar summaries and local event titles stay consistent with the user’s customized buttons.
- Tracker buttons are always saved as full pages of 8 buttons, with a maximum of 3 pages. Validation and frontend paging assume that exact shape.
- Share emails and usernames are normalized to lowercase and deduplicated; preserve that behavior when touching account settings or auth flows.
- For backend tests that exercise app behavior, prefer the existing pattern from `backend/tests/test_event_sync_flow.py`: replace `main.engine`, stub `_calendar_service`, disable the sync worker, and use `TestClient` against the real FastAPI app.
