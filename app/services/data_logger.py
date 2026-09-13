"""
DataLoggingService
──────────────────
Records all available telemetry data at a configurable interval, persists
each session to a JSONL file, and maintains a sessions manifest for the UI.

Storage layout:
    data/logging/sessions.json   — array of session metadata objects
    data/logging/<session_id>.jsonl — one JSON object per line per sample
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LOGGING_DIR = Path("data/logging")
SESSIONS_FILE = LOGGING_DIR / "sessions.json"
SAMPLE_INTERVAL_S = 1.0  # capture rate


class LoggingSession:
    """Metadata for one logging session."""

    def __init__(self, session_id: str, filename: str, start_time: str):
        self.id = session_id
        self.filename = filename
        self.start_time = start_time
        self.end_time: Optional[str] = None
        self.duration_s: float = 0.0
        self.data_count: int = 0
        self.name: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": self.duration_s,
            "data_count": self.data_count,
            "name": self.name,
        }

    @staticmethod
    def from_dict(d: dict) -> "LoggingSession":
        s = LoggingSession(d["id"], d["filename"], d["start_time"])
        s.end_time = d.get("end_time")
        s.duration_s = d.get("duration_s", 0.0)
        s.data_count = d.get("data_count", 0)
        s.name = d.get("name")
        return s


class DataLoggingService:
    """
    Singleton-style service injected into the FastAPI app.

    Call ``start_session`` / ``stop_session`` to control recording.
    The service polls ``telemetry_source.get_latest()`` every second.
    """

    def __init__(self) -> None:
        self._telemetry_source: Any = None  # set by main.py
        self._active_session: Optional[LoggingSession] = None
        self._task: Optional[asyncio.Task] = None
        self._file: Optional[io.TextIOWrapper] = None
        self._start_monotonic: float = 0.0
        LOGGING_DIR.mkdir(parents=True, exist_ok=True)

    # ─── Telemetry source injection ──────────────────────────────

    def set_telemetry_source(self, source: Any) -> None:
        self._telemetry_source = source

    # ─── Session lifecycle ───────────────────────────────────────

    async def start_session(self) -> dict:
        """Create a new logging session and begin periodic capture."""
        if self._active_session is not None:
            return {
                "error": "A logging session is already active",
                "session": self._active_session.to_dict(),
            }

        session_id = uuid.uuid4().hex[:12]
        start_dt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        filename = f"{session_id}.jsonl"

        session = LoggingSession(session_id, filename, start_dt)
        self._active_session = session
        self._start_monotonic = time.monotonic()

        filepath = LOGGING_DIR / filename
        self._file = open(filepath, "w", encoding="utf-8")

        self._task = asyncio.create_task(self._capture_loop())
        logger.info("Logging session started: %s", session_id)
        return {"success": True, "session": session.to_dict()}

    async def stop_session(self, name: str = None) -> dict:
        """Stop the active logging session and finalise metadata."""
        if self._active_session is None:
            return {"error": "No active logging session"}

        # Add name if provided
        if name:
            self._active_session.name = name

        # Cancel capture task
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Close data file
        if self._file is not None:
            self._file.close()
            self._file = None

        # Finalise session metadata
        session = self._active_session
        session.end_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
        session.duration_s = round(time.monotonic() - self._start_monotonic, 1)

        # Persist to manifest
        self._save_session_to_manifest(session)
        summary = session.to_dict()

        self._active_session = None
        logger.info("Logging session stopped: %s (%d samples)", session.id, session.data_count)
        return {"success": True, "session": summary}

    # ─── Query helpers ───────────────────────────────────────────

    def get_status(self) -> dict:
        if self._active_session is None:
            return {"active": False}
        session = self._active_session
        session.duration_s = round(time.monotonic() - self._start_monotonic, 1)
        return {"active": True, "session": session.to_dict()}

    def get_sessions(self) -> List[dict]:
        manifest = self._load_manifest()
        # Also inject live data_count for the active session
        if self._active_session:
            for entry in manifest:
                if entry["id"] == self._active_session.id:
                    entry["data_count"] = self._active_session.data_count
                    entry["duration_s"] = round(
                        time.monotonic() - self._start_monotonic, 1
                    )
        return manifest

    def get_session_data(self, session_id: str) -> Optional[List[dict]]:
        filepath = LOGGING_DIR / f"{session_id}.jsonl"
        if not filepath.exists():
            return None
        rows: List[dict] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows

    def delete_session(self, session_id: str) -> bool:
        # Don't delete the active session
        if self._active_session and self._active_session.id == session_id:
            return False

        manifest = self._load_manifest()
        new_manifest = [s for s in manifest if s["id"] != session_id]
        if len(new_manifest) == len(manifest):
            return False  # not found

        self._write_manifest(new_manifest)

        filepath = LOGGING_DIR / f"{session_id}.jsonl"
        if filepath.exists():
            filepath.unlink()

        logger.info("Deleted logging session: %s", session_id)
        return True

    def export_csv(self, session_id: str) -> Optional[str]:
        """Return CSV string for the given session, or None if not found."""
        data = self.get_session_data(session_id)
        if data is None or len(data) == 0:
            return None

        # Collect all unique keys across all rows
        all_keys: list[str] = []
        seen: set[str] = set()
        for row in data:
            for key in row.keys():
                if key not in seen:
                    all_keys.append(key)
                    seen.add(key)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            writer.writerow(row)
        return output.getvalue()

    # ─── Internal ────────────────────────────────────────────────

    async def _capture_loop(self) -> None:
        """Periodically sample telemetry and write to JSONL."""
        while True:
            try:
                await asyncio.sleep(SAMPLE_INTERVAL_S)
                if self._telemetry_source is None or self._file is None:
                    continue

                latest = self._telemetry_source.get_latest()
                if latest is None:
                    continue

                record = {
                    "log_timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                    "log_index": self._active_session.data_count if self._active_session else 0,
                }

                # Flatten all slot data into the record
                if isinstance(latest, dict):
                    for slot_key, slot_data in latest.items():
                        if isinstance(slot_data, dict):
                            prefix = slot_key  # e.g. "slot_1"
                            for k, v in slot_data.items():
                                record[f"{prefix}_{k}"] = v
                        else:
                            record[slot_key] = slot_data
                else:
                    record["data"] = str(latest)

                line = json.dumps(record, default=str)
                self._file.write(line + "\n")
                self._file.flush()

                if self._active_session:
                    self._active_session.data_count += 1

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Logging capture error: %s", exc)

    def _load_manifest(self) -> List[dict]:
        if not SESSIONS_FILE.exists():
            return []
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _write_manifest(self, sessions: List[dict]) -> None:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2, ensure_ascii=False)

    def _save_session_to_manifest(self, session: LoggingSession) -> None:
        manifest = self._load_manifest()
        # Update if exists, else append
        found = False
        for i, entry in enumerate(manifest):
            if entry["id"] == session.id:
                manifest[i] = session.to_dict()
                found = True
                break
        if not found:
            manifest.append(session.to_dict())
        self._write_manifest(manifest)

    async def shutdown(self) -> None:
        """Gracefully stop any active session on app shutdown."""
        if self._active_session:
            await self.stop_session()
