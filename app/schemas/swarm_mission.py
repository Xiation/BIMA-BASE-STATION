"""Schemas for auto-generated swarm missions and survey parameters."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from app.schemas.control import MissionItem


class SurveyArea(BaseModel):
    """A geospatial polygon defining the survey boundary."""

    # List of (latitude, longitude) tuples forming a closed polygon
    vertices: List[List[float]] = Field(
        min_length=3,
        description="List of [lat, lon] representing polygon vertices. Last vertex should match the first."
    )


class SurveyParameters(BaseModel):
    """Parameters for generating the lawnmower survey path."""

    area: SurveyArea
    altitude_m: float = Field(default=30.0, ge=5.0, description="Target survey altitude (meters)")
    speed_ms: float = Field(default=5.0, ge=1.0, description="Target ground speed (m/s)")
    lane_spacing_m: float = Field(default=20.0, ge=2.0, description="Distance between adjacent sweeps (meters)")
    sweep_angle_deg: Optional[float] = Field(
        default=None, 
        description="Manual sweep angle in degrees. If None, calculated automatically (longest edge)."
    )
    safety_margin_m: float = Field(default=0.0, ge=0.0, description="Shrink the polygon by this margin (meters)")
    min_horizontal_sep_m: float = Field(default=10.0, ge=2.0, description="Minimum allowed horizontal separation")
    
    # Home or current positions of the UAVs to determine optimal entry points
    uav_3_start_lat: Optional[float] = None
    uav_3_start_lon: Optional[float] = None
    uav_4_start_lat: Optional[float] = None
    uav_4_start_lon: Optional[float] = None


class TrajectoryConflict(BaseModel):
    """Represents a predicted collision or separation violation."""
    
    time_s: float
    uav_3_pos: List[float]  # [lat, lon, alt]
    uav_4_pos: List[float]  # [lat, lon, alt]
    horizontal_sep_m: float
    vertical_sep_m: float
    description: str


class GeneratedRoute(BaseModel):
    """Summary of the generated route for one UAV."""
    
    slot: int
    mission_items: List[MissionItem]
    route_distance_m: float = 0.0
    estimated_time_s: float = 0.0
    lane_count: int = 0


class MissionBatchResponse(BaseModel):
    """Final output of the generation process to be sent to the UI."""
    
    success: bool
    uav_3_route: Optional[GeneratedRoute] = None
    uav_4_route: Optional[GeneratedRoute] = None
    
    workload_difference_pct: float = 0.0
    predicted_conflicts: List[TrajectoryConflict] = Field(default_factory=list)
    min_horizontal_sep_m: float = -1.0
    
    message: str = ""
    error: Optional[str] = None
