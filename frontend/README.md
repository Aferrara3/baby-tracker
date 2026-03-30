# Baby Tracker - Frontend

A React + Vite + TypeScript frontend for tracking baby activities with real-time logging and timers.

## 🎯 Features

### Activity Logging
- **Tap to Log**: Single tap logs an activity and sends it to the backend
- **Long Press Timer**: Hold for 1+ seconds to start/stop activity timers
- **Real-time Display**: Shows active timers with elapsed time (HH:MM:SS format)
- **Notes**: Optional input field to add details after logging

### User Interface
- **8 Activity Buttons** in a responsive grid
- **Mobile Optimized**: 2-column layout on mobile, 4-column on desktop
- **Dark Mode Support**: Automatically respects system preferences
- **Toast Notifications**: Real-time feedback for all actions
- **Touch & Mouse Support**: Works on all devices

### Activity Types
| Icon | Activity | Color |
|------|----------|-------|
| 🍾 | Bottle | Blue |
| 🥄 | Food | Amber |
| 👶 | Diaper | Pink |
| 👶 | Diaper 2 | Violet |
| 🌙 | Sleep | Indigo |
| 👤 | Breastfeeding | Teal |
| 🥛 | Pump | Orange |
| ❓ | Help | Gray |

## 🚀 Quick Start

```bash
# Install dependencies (if not already done)
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

## 📋 Development

- **Framework**: React 19 with TypeScript
- **Build Tool**: Vite 8
- **Styling**: Tailwind CSS v4
- **Icons**: Lucide React
- **HTTP Client**: Axios
- **State Management**: React Hooks (useState, useRef, useEffect)

## 🔌 API Integration

Connects to `http://localhost:8000` with these endpoints:

```
POST /events
- Logs a single activity event
- Request: { activity_id, timestamp }

POST /activities/start
- Starts a timer for an activity
- Request: { activity_id }
- Response: { id, ... }

POST /activities/stop/{id}
- Stops a running activity timer
- Request: { duration }
```

## 📁 Project Structure

```
src/
├── App.tsx                 # Main app component with activity logic
├── App.css                 # App-specific styles
├── index.css              # Global styles and Tailwind directives
├── main.tsx               # React entry point
└── components/
    ├── ActivityButton.tsx  # Individual activity button with long-press detection
    └── Toast.tsx           # Toast notification component

public/                     # Static assets
dist/                      # Production build output
```

## 🛠️ Key Components

### ActivityButton
Handles individual activity buttons with:
- Tap detection for logging
- Long-press detection (1s threshold)
- Real-time timer display
- Visual feedback (ring, scale animations)
- Mouse and touch event support

### Toast
Notification component with:
- Success (green), error (red), info (blue) variants
- Auto-dismiss after 3 seconds
- Smooth animations
- Fixed position at top-right

### App
Main application component managing:
- Global state for running activities
- API communication
- Toast notifications
- Input modal for activity details

## 📦 Dependencies

```json
{
  "react": "^19.2.4",
  "react-dom": "^19.2.4",
  "typescript": "~5.9.3",
  "vite": "^8.0.1",
  "tailwindcss": "^4.2.2",
  "lucide-react": "^0.577.0",
  "axios": "^1.13.6",
  "clsx": "^2.1.1",
  "tailwind-merge": "^3.5.0"
}
```

## 🎨 Styling

All styling uses Tailwind CSS utility classes for:
- Responsive layouts
- Color schemes
- Dark mode support
- Animations and transitions
- Component styling

## 📱 Responsive Breakpoints

- **Mobile** (< 768px): 2-column grid for buttons, modal slides from bottom
- **Desktop** (≥ 768px): 4-column grid for buttons, centered modal

## ⌨️ Keyboard Support

- **Enter**: Submit activity details
- **Escape**: Close input modal without saving

## 🔧 Build Configuration

- TypeScript strict mode enabled
- ESLint with React and TypeScript support
- Vite optimized build with code splitting
- Production bundle: ~233KB (JavaScript) + 7.4KB (CSS)

## 📝 Notes

- All components are functional React components using hooks
- Fully typed with TypeScript
- No external state management library needed (React hooks sufficient)
- Events are sent immediately on tap/long-press
- Timer synchronization happens on the client (UI only)
- Duration calculated on stop and sent to backend

## 🚢 Deployment

Built files are in `dist/`:
```bash
npm run build
# Serve the dist/ directory with any static file server
```

## 📞 API Error Handling

- Network errors show red toast notifications
- Failed actions don't update local state
- Users can retry failed operations

## 🎯 Next Steps

1. Ensure backend is running on `http://localhost:8000`
2. Run `npm run dev` to start the development server
3. Open `http://localhost:5173` in your browser
4. Test with all activity types
5. Build with `npm run build` when ready for production

---

**Happy tracking!** 🎉
