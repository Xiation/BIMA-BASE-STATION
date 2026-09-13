"""Swarm orchestration API contracts — schemas for dual-copter operations."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.control import MissionItem


# ─── Swarm-Level State Machine ────────────────────────────────────────

class SwarmPhase(str, Enum):
    """System-wide coordinated flight phase."""

    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    READY_TO_START = "READY_TO_START"
    STARTING = "STARTING"
    ARMING = "ARMING"
    TAKEOFF = "TAKEOFF"
    HOVER_STABILIZING = "HOVER_STABILIZING"
    AUTO_RUNNING = "AUTO_RUNNING"
    COMPLETED = "COMPLETED"

    # Failure / degraded states
    PARTIAL_UPLOAD = "PARTIAL_UPLOAD"
    DEGRADED = "DEGRADED"
    ABORTING = "ABORTING"
    FAILED = "FAILED"


class PerUAVUploadStatus(str, Enum):
    """Per-UAV upload transaction status."""

    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class PerUAVFlightPhase(str, Enum):
    """Per-UAV flight phase during coordinated start."""

    IDLE = "IDLE"
    PRECHECK = "PRECHECK"
    ARMING = "ARMING"
    TAKEOFF = "TAKEOFF"
    HOVER_STABILIZING = "HOVER_STABILIZING"
    AUTO_RUNNING = "AUTO_RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


# ─── Request / Response Models ────────────────────────────────────────

class MissionBatchUploadRequest(BaseModel):
    """Payload: upload missions to both copters in one action."""

    mission_uav_3: list[MissionItem] = Field(
        min_length=1,
        max_length=1000,
        description="Mission items for Copter UAV-3 (slot 3)",
    )
    mission_uav_4: list[MissionItem] = Field(
        min_length=1,
        max_length=1000,
        description="Mission items for Copter UAV-4 (slot 4)",
    )
    ip_3: Optional[str] = None
    port_3: Optional[int] = None
    ip_4: Optional[str] = None
    port_4: Optional[int] = None


class PerUAVUploadResult(BaseModel):
    """Upload result for one UAV within a batch operation."""

    slot: int
    status: PerUAVUploadStatus
    total: int = 0
    sent: int = 0
    result_code: Optional[int] = None
    result_label: str = ""
    message: str = ""


class MissionBatchUploadResponse(BaseModel):
    """Response: result of the batch upload to both UAVs."""

    phase: SwarmPhase
    uav_3: PerUAVUploadResult
    uav_4: PerUAVUploadResult
    ready_to_start: bool = False
    message: str = ""


class SwarmStartRequest(BaseModel):
    """Payload for coordinated start mission (minimal — safety in backend)."""

    confirmation: str = Field(
        default="",
        description="Must be 'CONFIRM_START' to proceed (double-click protection)",
    )
    ip_3: Optional[str] = None
    port_3: Optional[int] = None
    ip_4: Optional[str] = None
    port_4: Optional[int] = None


class SwarmStartResponse(BaseModel):
    """Response to a coordinated start request."""

    phase: SwarmPhase
    accepted: bool = False
    message: str = ""
    uav_3_phase: PerUAVFlightPhase = PerUAVFlightPhase.IDLE
    uav_4_phase: PerUAVFlightPhase = PerUAVFlightPhase.IDLE


class SwarmAbortRequest(BaseModel):
    """Payload for emergency abort."""

    reason: str = "User abort"


class SwarmAbortResponse(BaseModel):
    """Response to an abort request."""

    phase: SwarmPhase
    message: str = ""
    uav_3_action: str = ""
    uav_4_action: str = ""


# ─── Status / Telemetry Models ────────────────────────────────────────

class APFStatus(BaseModel):
    """Real-time APF collision avoidance status for the dashboard."""

    active: bool = False
    d_ij: float = Field(default=-1.0, description="Current inter-UAV distance (m)")
    d_cpa: float = Field(default=-1.0, description="Predicted closest approach (m)")
    t_cpa: float = Field(default=0.0, description="Time to CPA (s)")
    uav_3_offset_m: float = 0.0
    uav_4_offset_m: float = 0.0
    uav_3_avoidance_active: bool = False
    uav_4_avoidance_active: bool = False
    stale: bool = False
    warning: str = ""


class SwarmStatusResponse(BaseModel):
    """Full swarm status snapshot for the dashboard."""

    phase: SwarmPhase = SwarmPhase.IDLE

    # Per-UAV states
    uav_3_upload: PerUAVUploadStatus = PerUAVUploadStatus.PENDING
    uav_4_upload: PerUAVUploadStatus = PerUAVUploadStatus.PENDING
    uav_3_flight: PerUAVFlightPhase = PerUAVFlightPhase.IDLE
    uav_4_flight: PerUAVFlightPhase = PerUAVFlightPhase.IDLE

    ready_to_start: bool = False

    # APF
    apf: APFStatus = Field(default_factory=APFStatus)

    # Safety
    interlocks_passed: bool = False
    interlock_failures: list[str] = Field(default_factory=list)

    message: str = ""
