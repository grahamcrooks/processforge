"""
api/routes/mode.py
GET  /api/mode        — returns current mode (live / mock)
POST /api/mode        — switches mode, requires PIN
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import settings

router = APIRouter(prefix="/api")

# Runtime mode — starts from whatever DEV_MODE is set to in .env
# Stored in memory; resets to .env value on server restart.
_state = {"mock": settings.dev_mode}


class ModeSwitchRequest(BaseModel):
    mode: str   # 'live' or 'mock'
    pin: str


class ModeResponse(BaseModel):
    mode: str   # 'live' or 'mock'


@router.get("/mode", response_model=ModeResponse)
def get_mode():
    return ModeResponse(mode="mock" if _state["mock"] else "live")


@router.post("/mode", response_model=ModeResponse)
def set_mode(req: ModeSwitchRequest):
    # Validate PIN
    if req.pin != settings.mode_pin:
        raise HTTPException(status_code=403, detail="Incorrect PIN")

    if req.mode not in ("live", "mock"):
        raise HTTPException(status_code=400, detail="mode must be 'live' or 'mock'")

    _state["mock"] = (req.mode == "mock")

    # Keep claude_service in sync
    try:
        from services.claude_service import set_dev_mode
        set_dev_mode(_state["mock"])
    except Exception:
        pass  # if claude_service doesn't expose set_dev_mode yet, silent fail

    return ModeResponse(mode=req.mode)
