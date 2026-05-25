from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.models.schemas import HealthResponse
from api.routes.generate import router as generate_router
from config import settings

app = FastAPI(
    title="bupa-blueprint-app",
    description="Generate Blueprint-ready artefacts from Bupa process flow diagrams",
    version="2.0.0",
)

# In production the frontend is built and served from backend/static/
# In development the Vite dev server handles the frontend separately.
_STATIC = Path(__file__).parent / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate_router)
# Added by GC
from api.routes.mode import router as mode_router
app.include_router(mode_router)


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", version=app.version)


# Serve built React app — must be registered AFTER API routes
if _STATIC.exists():
    app.mount("/assets", StaticFiles(directory=_STATIC / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Return index.html for all non-API routes so React Router works."""
        return FileResponse(_STATIC / "index.html")
