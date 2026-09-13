"""
Logging Router
──────────────
REST endpoints for the data-logging feature.

data_logger_instance is injected by main.py at startup.
"""

import logging

from fastapi import APIRouter, Path, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class StopLoggingRequest(BaseModel):
    name: str = None

router = APIRouter(prefix="/api/logging", tags=["logging"])

# Injected by main.py lifespan
data_logger_instance = None


@router.post("/start")
async def start_logging():
    """Start a new logging session."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    return await data_logger_instance.start_session()


@router.post("/stop")
async def stop_logging(req: StopLoggingRequest = None):
    """Stop the active logging session."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    name = req.name if req else None
    return await data_logger_instance.stop_session(name=name)


@router.get("/status")
async def logging_status():
    """Return current logging status (active flag + session info)."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    return data_logger_instance.get_status()


@router.get("/sessions")
async def list_sessions():
    """List all recorded logging sessions."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    return data_logger_instance.get_sessions()


@router.get("/sessions/{session_id}/data")
async def get_session_data(session_id: str):
    """Return all data rows for a specific session."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    data = data_logger_instance.get_session_data(session_id)
    if data is None:
        return {"error": "session not found"}
    return {"session_id": session_id, "data": data, "count": len(data)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a logging session and its data file."""
    if data_logger_instance is None:
        return {"error": "logging service not initialised"}
    success = data_logger_instance.delete_session(session_id)
    if not success:
        return {"error": "session not found or is currently active"}
    return {"success": True}


@router.get("/sessions/{session_id}/csv")
async def export_session_csv(session_id: str):
    """Export a logging session as a downloadable CSV file."""
    if data_logger_instance is None:
        return PlainTextResponse("logging service not initialised", status_code=500)
    csv_content = data_logger_instance.export_csv(session_id)
    if csv_content is None:
        return PlainTextResponse("session not found or empty", status_code=404)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="logging_{session_id}.csv"',
        },
    )
