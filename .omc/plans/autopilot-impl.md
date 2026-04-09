# Autopilot Implementation Plan — AI Image Editor

## Spec Source
CLAUDE.md (Image Editor Web App)

## Stack
- Backend: FastAPI + OpenCV + Pillow + Gemini API
- Frontend: React + Vite + TailwindCSS
- Storage: JSON trajectories

---

## Phase 2 — Execution Tasks

### Backend (sequential)
1. [ ] Directory scaffolding: backend/ + frontend/
2. [ ] backend/requirements.txt
3. [ ] .env.example
4. [ ] backend/models/schemas.py — Pydantic models
5. [ ] backend/services/trajectory_store.py — JSON trajectory storage
6. [ ] backend/services/opencv_editor.py — OpenCV edit functions
7. [ ] backend/services/intent_router.py — Gemini intent classification
8. [ ] backend/services/gemini_editor.py — Gemini generative editing
9. [ ] backend/routers/session.py — Session CRUD
10. [ ] backend/routers/edit.py — Edit endpoint
11. [ ] backend/routers/trajectory.py — Trajectory API
12. [ ] backend/main.py — App entry, CORS, StaticFiles

### Frontend (parallel with backend)
13. [ ] frontend/ Vite scaffold + tailwind config
14. [ ] frontend/src/api/client.ts
15. [ ] frontend/src/hooks/useSession.ts
16. [ ] frontend/src/components/ImageUploader.tsx
17. [ ] frontend/src/components/ChatPanel.tsx
18. [ ] frontend/src/components/ImageViewer.tsx
19. [ ] frontend/src/components/HistoryBar.tsx
20. [ ] frontend/src/App.tsx

### Config
21. [ ] backend/data/trajectories/.gitkeep

---

## Key Design Decisions
- Images stored in memory/temp only; only metadata in trajectory JSON
- Results returned as base64 to frontend
- Session max 50 edits (memory management)
- Intent router uses full session history as context
- Gemini image model: gemini-2.0-flash-exp (image output via response_modalities)
- Fallback: if Gemini image fails, return explanation text
