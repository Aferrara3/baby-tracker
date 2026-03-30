# Baby Tracker

A simple web app to track baby activities, inspired by the Talli device.

## Features
- **8 Activity Buttons**: Bottle, Food, Diaper (Pee/Poop), Sleep, Breastfeeding, Pump, Help.
- **Tap to Log**: Quickly log an event with a single tap.
- **Long Press to Time**: Hold (>1s) to start a timer, hold again to stop.
- **Add Details**: After logging or stopping a timer, you can add text notes.
- **Data Persistence**: All events are stored in a SQLite database.

## Prerequisites
- Node.js & npm
- Python 3.10+

## Setup & Running

### 1. Backend (FastAPI)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```
The backend will start at `http://localhost:8090`.

### 2. Frontend (React + Vite)

Open a new terminal:

```bash
cd frontend
npm install
npm run dev
```
The frontend will start at `http://localhost:3005`.

## Usage
- Click a button to log an event.
- **Long press** a button to start a timer (it will show as running).
- **Long press** again to stop the timer.
- After logging, a popup will appear to let you enter optional details.
