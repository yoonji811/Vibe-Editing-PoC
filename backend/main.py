"""FastAPI application entry point."""
import os
import traceback
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from routers import session, edit, trajectory
from agents.router import router as agent_router

app = FastAPI(title="AI Image Editor", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
_raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(session.router)
app.include_router(edit.router)
app.include_router(trajectory.router)
app.include_router(agent_router)


# ---------------------------------------------------------------------------
# Global error middleware — 개발 환경에서 상세 에러 반환
# ---------------------------------------------------------------------------
@app.middleware("http")
async def catch_exceptions(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        tb = traceback.format_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "traceback": tb},
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    from services import image_store
    return {
        "status": "ok",
        "cloudinary": "configured" if image_store._configured else "not configured",
    }


# ---------------------------------------------------------------------------
# Serve built frontend (production)
# ---------------------------------------------------------------------------
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
