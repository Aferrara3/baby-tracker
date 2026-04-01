# Baby Tracker Frontend

React + Vite frontend for the Baby Tracker app.

## What it does

- Supports register, login, and logout
- Lets each household manage baby name and calendar share emails
- Enables service-managed Google Calendar sync
- Auto-syncs Google changes back into the app on a configurable interval
- Provides quick tools for force sync, simulate sample day, and delete today's events
- Supports tap logging and hold-to-start/stop timers for activity events

## Run locally

```bash
npm install
npm run dev
```

The dev server runs on `http://localhost:3005`.

## Validate

```bash
npm run lint
npm run build
```

## Runtime config

- `VITE_API_BASE_URL` defaults to `http://localhost:8090`
- `VITE_GOOGLE_SYNC_POLL_INTERVAL_MS` defaults to `3600000` (1 hour)
