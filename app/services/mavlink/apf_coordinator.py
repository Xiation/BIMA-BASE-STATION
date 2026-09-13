"""
Artificial Potential Field (APF) Coordinator
═════════════════════════════════════════════
Pure-math APF engine for dual-copter anti-collision.

Responsibilities:
  - Compute attractive force toward each UAV's active waypoint
  - Compute repulsive force between UAVs based on distance + CPA prediction
  - Apply right-of-way priority, hysteresis, saturation, low-pass filtering
  - Output corrected waypoint (lat/lon/alt) that can be written to FC via mission protocol

This module has ZERO MAVLink or I/O dependencies.  It can be unit-tested
and replayed from logs without any network or serial connection.

All default values are labelled **initial SITL tuning values** and
MUST NOT be considered safe for real flight without field testing.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple

# ─── Constants ────────────────────────────────────────────────────────

EARTH_RADIUS_M = 6_371_000.0
DEG_TO_RAD = math.pi / 180.0
RAD_TO_DEG = 180.0 / math.pi

# Prevent division-by-zero in distance and velocity computations
EPSILON = 1e-9


# ─── Configuration ────────────────────────────────────────────────────

@dataclass
class APFConfig:
    """
    All APF tuning parameters.

    **Initial SITL tuning values** — NOT safe for real flight.
    """

    # Attractive force gain
    k_att: float = 1.0

    # Repulsive force gain
    k_rep: float = 1.5

    # Distance thresholds (meters)
    d_safe: float = 5.0           # Hard minimum — trigger emergency if breached
    d_influence: float = 30.0     # Repulsive force active below this distance

    # CPA prediction
    prediction_horizon: float = 10.0  # seconds to look ahead

    # Output limits
    max_lateral_offset_m: float = 20.0   # max XY correction from original WP
    max_vertical_offset_m: float = 10.0  # max Z correction
    max_speed_ms: float = 5.0            # max velocity magnitude from APF
    max_acceleration_ms2: float = 2.0    # unused for now — placeholder

    # Altitude constraints
    altitude_floor_m: float = 2.0   # minimum relative altitude
    altitude_ceiling_m: float = 50.0  # maximum relative altitude

    # Filtering
    lowpass_alpha: float = 0.3  # exponential moving average weight (0..1)

    # Hysteresis
    hysteresis_enter_m: float = 25.0   # enter avoidance when d_ij < this
    hysteresis_exit_m: float = 35.0    # exit avoidance when d_ij > this

    # Cooldown after exiting avoidance (seconds)
    cooldown_s: float = 3.0

    # Stale data threshold (seconds)
    max_telemetry_age_s: float = 2.0

    # Vertical separation preference (meters) when head-on
    vertical_separation_m: float = 3.0

    # Tick rate (how often APF is computed — informational, not enforced here)
    tick_rate_hz: float = 5.0


# ─── Data Structures ─────────────────────────────────────────────────

class AvoidanceState(Enum):
    """Per-UAV avoidance engagement state."""
    INACTIVE = auto()
    ENTERING = auto()
    ACTIVE = auto()
    EXITING = auto()
    COOLDOWN = auto()


@dataclass
class Vec3:
    """Simple 3-component vector in NED meters."""
    x: float = 0.0  # North
    y: float = 0.0  # East
    z: float = 0.0  # Down (positive = lower altitude)

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> "Vec3":
        return self.__mul__(scalar)

    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def norm(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def norm_xy(self) -> float:
        """Horizontal distance only."""
        return math.sqrt(self.x ** 2 + self.y ** 2)

    def normalized(self) -> "Vec3":
        n = self.norm()
        if n < EPSILON:
            return Vec3(0, 0, 0)
        return Vec3(self.x / n, self.y / n, self.z / n)

    def clamped(self, max_magnitude: float) -> "Vec3":
        n = self.norm()
        if n <= max_magnitude or n < EPSILON:
            return Vec3(self.x, self.y, self.z)
        scale = max_magnitude / n
        return Vec3(self.x * scale, self.y * scale, self.z * scale)


@dataclass
class UAVState:
    """Snapshot of one UAV's telemetry for APF computation."""

    uav_id: int
    timestamp: float = 0.0      # epoch seconds when this data was captured

    # Position (global)
    lat: float = 0.0            # degrees
    lon: float = 0.0            # degrees
    alt_relative_m: float = 0.0  # meters above home (relative alt)

    # Velocity (m/s, NED)
    vx: float = 0.0  # North
    vy: float = 0.0  # East
    vz: float = 0.0  # Down

    # Heading (degrees, 0=North CW)
    heading_deg: float = 0.0

    # Current mission state
    current_seq: int = 0
    total_waypoints: int = 0

    # FC state
    flight_mode: str = ""
    armed: bool = False
    gps_fix: int = 0

    # Active target waypoint (global)
    target_lat: float = 0.0
    target_lon: float = 0.0
    target_alt_m: float = 0.0


@dataclass
class APFResult:
    """Output of one APF computation tick for one UAV."""

    uav_id: int
    timestamp: float

    # Corrected waypoint (global coordinates)
    corrected_lat: float = 0.0
    corrected_lon: float = 0.0
    corrected_alt_m: float = 0.0

    # Original waypoint (for comparison / logging)
    original_lat: float = 0.0
    original_lon: float = 0.0
    original_alt_m: float = 0.0

    # Metrics
    d_ij: float = float("inf")          # current distance to peer
    d_cpa: float = float("inf")         # predicted closest point of approach
    t_cpa: float = 0.0                  # time to CPA
    f_att: Vec3 = field(default_factory=Vec3)
    f_rep: Vec3 = field(default_factory=Vec3)
    f_total: Vec3 = field(default_factory=Vec3)
    avoidance_state: AvoidanceState = AvoidanceState.INACTIVE
    avoidance_active: bool = False

    # Offset from original waypoint (meters)
    offset_m: float = 0.0

    # Stale / invalid flags
    stale: bool = False
    reason: str = ""


# ─── Coordinate Helpers ──────────────────────────────────────────────

def latlon_to_ned(
    lat: float,
    lon: float,
    alt: float,
    ref_lat: float,
    ref_lon: float,
    ref_alt: float,
) -> Vec3:
    """
    Convert global (lat/lon/alt) to local NED relative to a reference point.

    Uses flat-earth approximation (accurate within ~10 km).
    """
    d_lat = (lat - ref_lat) * DEG_TO_RAD
    d_lon = (lon - ref_lon) * DEG_TO_RAD

    north = d_lat * EARTH_RADIUS_M
    east = d_lon * EARTH_RADIUS_M * math.cos(ref_lat * DEG_TO_RAD)
    down = -(alt - ref_alt)  # NED: down is positive

    return Vec3(north, east, down)


def ned_to_latlon(
    ned: Vec3,
    ref_lat: float,
    ref_lon: float,
    ref_alt: float,
) -> Tuple[float, float, float]:
    """
    Convert local NED back to global (lat/lon/alt).
    """
    lat = ref_lat + (ned.x / EARTH_RADIUS_M) * RAD_TO_DEG
    lon = ref_lon + (ned.y / (EARTH_RADIUS_M * math.cos(ref_lat * DEG_TO_RAD))) * RAD_TO_DEG
    alt = ref_alt - ned.z  # NED: down is positive

    return lat, lon, alt


def haversine_distance_m(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Great-circle distance in meters between two lat/lon points."""
    dlat = (lat2 - lat1) * DEG_TO_RAD
    dlon = (lon2 - lon1) * DEG_TO_RAD
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * DEG_TO_RAD)
        * math.cos(lat2 * DEG_TO_RAD)
        * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── APF Engine ──────────────────────────────────────────────────────

class APFEngine:
    """
    Stateful APF engine for two UAVs.

    Usage:
        engine = APFEngine(config)
        result_1, result_2 = engine.tick(uav1_state, uav2_state)
    """

    def __init__(self, config: Optional[APFConfig] = None) -> None:
        self.config = config or APFConfig()

        # Per-UAV avoidance state tracking
        self._avoidance_state: dict[int, AvoidanceState] = {}
        self._avoidance_entered_at: dict[int, float] = {}
        self._cooldown_until: dict[int, float] = {}

        # Low-pass filter memory (previous output forces)
        self._prev_f_total: dict[int, Vec3] = {}

    def tick(
        self,
        uav1: UAVState,
        uav2: UAVState,
    ) -> Tuple[APFResult, APFResult]:
        """
        Compute one APF cycle for both UAVs simultaneously.

        Returns a tuple (result_uav1, result_uav2).
        """
        now = time.time()
        cfg = self.config

        # --- Staleness check ---
        result1 = APFResult(uav_id=uav1.uav_id, timestamp=now)
        result2 = APFResult(uav_id=uav2.uav_id, timestamp=now)

        age1 = now - uav1.timestamp if uav1.timestamp > 0 else float("inf")
        age2 = now - uav2.timestamp if uav2.timestamp > 0 else float("inf")

        if age1 > cfg.max_telemetry_age_s:
            result1.stale = True
            result1.reason = f"UAV {uav1.uav_id} telemetry stale ({age1:.1f}s)"
        if age2 > cfg.max_telemetry_age_s:
            result2.stale = True
            result2.reason = f"UAV {uav2.uav_id} telemetry stale ({age2:.1f}s)"

        # If either is stale, return without correction
        if result1.stale or result2.stale:
            # Set original waypoints as corrected (no change)
            result1.corrected_lat = uav1.target_lat
            result1.corrected_lon = uav1.target_lon
            result1.corrected_alt_m = uav1.target_alt_m
            result1.original_lat = uav1.target_lat
            result1.original_lon = uav1.target_lon
            result1.original_alt_m = uav1.target_alt_m

            result2.corrected_lat = uav2.target_lat
            result2.corrected_lon = uav2.target_lon
            result2.corrected_alt_m = uav2.target_alt_m
            result2.original_lat = uav2.target_lat
            result2.original_lon = uav2.target_lon
            result2.original_alt_m = uav2.target_alt_m
            return result1, result2

        # --- Common reference frame: midpoint of the two UAVs ---
        ref_lat = (uav1.lat + uav2.lat) / 2
        ref_lon = (uav1.lon + uav2.lon) / 2
        ref_alt = (uav1.alt_relative_m + uav2.alt_relative_m) / 2

        # --- Convert to NED ---
        p1 = latlon_to_ned(uav1.lat, uav1.lon, uav1.alt_relative_m, ref_lat, ref_lon, ref_alt)
        p2 = latlon_to_ned(uav2.lat, uav2.lon, uav2.alt_relative_m, ref_lat, ref_lon, ref_alt)

        v1 = Vec3(uav1.vx, uav1.vy, uav1.vz)
        v2 = Vec3(uav2.vx, uav2.vy, uav2.vz)

        goal1 = latlon_to_ned(uav1.target_lat, uav1.target_lon, uav1.target_alt_m, ref_lat, ref_lon, ref_alt)
        goal2 = latlon_to_ned(uav2.target_lat, uav2.target_lon, uav2.target_alt_m, ref_lat, ref_lon, ref_alt)

        # --- Compute inter-UAV distance and CPA ---
        r = p2 - p1
        d_ij = r.norm()

        v_rel = v2 - v1
        rv_dot = r.dot(v_rel)
        vv_dot = v_rel.dot(v_rel)

        t_cpa = max(0.0, min(
            -rv_dot / max(vv_dot, EPSILON),
            cfg.prediction_horizon,
        ))

        r_at_cpa = r + v_rel * t_cpa
        d_cpa = r_at_cpa.norm()

        # --- Compute forces for each UAV ---
        result1 = self._compute_single(
            uav1, p1, v1, goal1, p2, v2, d_ij, d_cpa, t_cpa,
            ref_lat, ref_lon, ref_alt, now, priority=True,
        )
        result2 = self._compute_single(
            uav2, p2, v2, goal2, p1, v1, d_ij, d_cpa, t_cpa,
            ref_lat, ref_lon, ref_alt, now, priority=False,
        )

        return result1, result2

    def _compute_single(
        self,
        uav: UAVState,
        p_self: Vec3,
        v_self: Vec3,
        goal: Vec3,
        p_peer: Vec3,
        v_peer: Vec3,
        d_ij: float,
        d_cpa: float,
        t_cpa: float,
        ref_lat: float,
        ref_lon: float,
        ref_alt: float,
        now: float,
        priority: bool,
    ) -> APFResult:
        """Compute APF for one UAV against one peer."""
        cfg = self.config
        uid = uav.uav_id

        result = APFResult(
            uav_id=uid,
            timestamp=now,
            original_lat=uav.target_lat,
            original_lon=uav.target_lon,
            original_alt_m=uav.target_alt_m,
            d_ij=d_ij,
            d_cpa=d_cpa,
            t_cpa=t_cpa,
        )

        # --- Hysteresis state management ---
        current_state = self._avoidance_state.get(uid, AvoidanceState.INACTIVE)
        threat_dist = min(d_ij, d_cpa)  # Use whichever is more threatening

        if current_state == AvoidanceState.INACTIVE:
            if threat_dist < cfg.hysteresis_enter_m:
                current_state = AvoidanceState.ACTIVE
                self._avoidance_entered_at[uid] = now
        elif current_state == AvoidanceState.ACTIVE:
            if threat_dist > cfg.hysteresis_exit_m:
                current_state = AvoidanceState.COOLDOWN
                self._cooldown_until[uid] = now + cfg.cooldown_s
        elif current_state == AvoidanceState.COOLDOWN:
            if now >= self._cooldown_until.get(uid, 0):
                current_state = AvoidanceState.INACTIVE
            elif threat_dist < cfg.hysteresis_enter_m:
                # Re-enter if threat returns during cooldown
                current_state = AvoidanceState.ACTIVE
                self._avoidance_entered_at[uid] = now

        self._avoidance_state[uid] = current_state
        result.avoidance_state = current_state
        avoidance_active = current_state == AvoidanceState.ACTIVE
        result.avoidance_active = avoidance_active

        # --- Attractive force ---
        f_att = (goal - p_self) * cfg.k_att
        result.f_att = f_att

        # --- Repulsive force ---
        f_rep = Vec3()
        if avoidance_active and d_ij > EPSILON and d_ij < cfg.d_influence:
            # Standard repulsive potential field
            diff = p_self - p_peer
            direction = diff.normalized()

            magnitude = cfg.k_rep * (1.0 / d_ij - 1.0 / cfg.d_influence) * (1.0 / (d_ij ** 2))
            f_rep = direction * magnitude

            # --- CPA-based boost ---
            # If predicted CPA is small, increase repulsion proportionally
            if d_cpa < cfg.d_influence and t_cpa > 0:
                cpa_urgency = max(0.0, 1.0 - d_cpa / cfg.d_influence)
                time_urgency = max(0.0, 1.0 - t_cpa / cfg.prediction_horizon)
                boost = 1.0 + cpa_urgency * time_urgency * 2.0
                f_rep = f_rep * boost

            # --- Right-of-way: lower priority UAV takes evasive action more ---
            if not priority:
                f_rep = f_rep * 1.5  # Non-priority UAV dodges harder
            else:
                f_rep = f_rep * 0.7  # Priority UAV dodges less

            # --- Head-on detection: add vertical separation ---
            v_closing = (v_peer - v_self).dot(diff.normalized())
            if v_closing > 1.0 and d_ij < cfg.d_influence * 0.5:
                # Approaching head-on — add vertical offset
                vertical_dir = -1.0 if priority else 1.0  # priority goes up, non-priority goes down
                f_rep = f_rep + Vec3(0, 0, vertical_dir * cfg.vertical_separation_m * cfg.k_rep)

        result.f_rep = f_rep

        # --- Resultant force ---
        f_total = f_att + f_rep

        # --- Saturation / clamping ---
        f_total_xy = Vec3(f_total.x, f_total.y, 0).clamped(cfg.max_lateral_offset_m * cfg.k_att)
        f_total_z = max(-cfg.max_vertical_offset_m * cfg.k_att,
                        min(cfg.max_vertical_offset_m * cfg.k_att, f_total.z))
        f_total = Vec3(f_total_xy.x, f_total_xy.y, f_total_z)

        # --- Low-pass filter ---
        prev = self._prev_f_total.get(uid, Vec3())
        alpha = cfg.lowpass_alpha
        f_total = Vec3(
            alpha * f_total.x + (1 - alpha) * prev.x,
            alpha * f_total.y + (1 - alpha) * prev.y,
            alpha * f_total.z + (1 - alpha) * prev.z,
        )
        self._prev_f_total[uid] = f_total
        result.f_total = f_total

        # --- Convert force to corrected waypoint position ---
        # The force vector represents desired displacement from current position
        # toward the goal.  We normalize by k_att so the output is in meters.
        if cfg.k_att > EPSILON:
            displacement = Vec3(
                f_total.x / cfg.k_att,
                f_total.y / cfg.k_att,
                f_total.z / cfg.k_att,
            )
        else:
            displacement = Vec3()

        # Clamp displacement to max offset from original goal
        goal_to_corrected = displacement - (goal - p_self)
        clamped_offset = goal_to_corrected.clamped(cfg.max_lateral_offset_m)

        # Corrected position in NED
        corrected_ned = goal + clamped_offset

        # --- Altitude constraints ---
        # In NED, z is down-positive.  Convert to altitude for constraint check:
        corrected_alt = ref_alt - corrected_ned.z
        corrected_alt = max(cfg.altitude_floor_m, min(cfg.altitude_ceiling_m, corrected_alt))
        corrected_ned = Vec3(corrected_ned.x, corrected_ned.y, -(corrected_alt - ref_alt))

        # --- Convert back to lat/lon ---
        c_lat, c_lon, c_alt = ned_to_latlon(corrected_ned, ref_lat, ref_lon, ref_alt)

        result.corrected_lat = c_lat
        result.corrected_lon = c_lon
        result.corrected_alt_m = c_alt

        # --- Compute offset magnitude ---
        offset_ned = Vec3(
            corrected_ned.x - goal.x,
            corrected_ned.y - goal.y,
            corrected_ned.z - goal.z,
        )
        result.offset_m = offset_ned.norm()

        return result

    def reset(self) -> None:
        """Clear all internal state (for testing or mission reset)."""
        self._avoidance_state.clear()
        self._avoidance_entered_at.clear()
        self._cooldown_until.clear()
        self._prev_f_total.clear()
