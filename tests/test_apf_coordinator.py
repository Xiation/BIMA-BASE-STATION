"""
Unit tests for the APF Math Engine.
Run with: python -m pytest tests/test_apf_coordinator.py -v
"""

import math
import time
import pytest

from app.services.mavlink.apf_coordinator import (
    APFConfig,
    APFEngine,
    AvoidanceState,
    UAVState,
    Vec3,
    haversine_distance_m,
    latlon_to_ned,
    ned_to_latlon,
)


# ─── Vec3 Tests ──────────────────────────────────────────────────────

class TestVec3:
    def test_add(self):
        a = Vec3(1, 2, 3)
        b = Vec3(4, 5, 6)
        r = a + b
        assert r.x == 5 and r.y == 7 and r.z == 9

    def test_sub(self):
        a = Vec3(5, 5, 5)
        b = Vec3(1, 2, 3)
        r = a - b
        assert r.x == 4 and r.y == 3 and r.z == 2

    def test_scalar_mul(self):
        a = Vec3(1, 2, 3)
        r = a * 2
        assert r.x == 2 and r.y == 4 and r.z == 6

    def test_rmul(self):
        a = Vec3(1, 2, 3)
        r = 3 * a
        assert r.x == 3 and r.y == 6 and r.z == 9

    def test_dot(self):
        a = Vec3(1, 0, 0)
        b = Vec3(0, 1, 0)
        assert a.dot(b) == 0.0

    def test_norm(self):
        a = Vec3(3, 4, 0)
        assert abs(a.norm() - 5.0) < 1e-9

    def test_norm_xy(self):
        a = Vec3(3, 4, 100)
        assert abs(a.norm_xy() - 5.0) < 1e-9

    def test_normalized(self):
        a = Vec3(0, 0, 5)
        n = a.normalized()
        assert abs(n.z - 1.0) < 1e-9
        assert abs(n.norm() - 1.0) < 1e-9

    def test_normalized_zero(self):
        a = Vec3(0, 0, 0)
        n = a.normalized()
        assert n.norm() == 0.0

    def test_clamped(self):
        a = Vec3(100, 0, 0)
        c = a.clamped(10.0)
        assert abs(c.norm() - 10.0) < 1e-9

    def test_clamped_no_change(self):
        a = Vec3(3, 4, 0)
        c = a.clamped(10.0)
        assert abs(c.x - 3) < 1e-9 and abs(c.y - 4) < 1e-9


# ─── Coordinate Helpers Tests ────────────────────────────────────────

class TestCoordinateHelpers:
    def test_latlon_to_ned_same_point(self):
        ned = latlon_to_ned(0, 0, 10, 0, 0, 10)
        assert abs(ned.x) < 0.01
        assert abs(ned.y) < 0.01
        assert abs(ned.z) < 0.01

    def test_latlon_to_ned_north(self):
        # 1 degree north ≈ 111 km
        ned = latlon_to_ned(1, 0, 0, 0, 0, 0)
        assert ned.x > 110000  # North should be positive and large
        assert abs(ned.y) < 1  # East should be near zero

    def test_ned_roundtrip(self):
        ref_lat, ref_lon, ref_alt = -7.7, 110.3, 100
        ned = latlon_to_ned(-7.701, 110.301, 105, ref_lat, ref_lon, ref_alt)
        lat, lon, alt = ned_to_latlon(ned, ref_lat, ref_lon, ref_alt)
        assert abs(lat - (-7.701)) < 1e-6
        assert abs(lon - 110.301) < 1e-6
        assert abs(alt - 105) < 0.1

    def test_haversine_same_point(self):
        d = haversine_distance_m(0, 0, 0, 0)
        assert d < 0.01

    def test_haversine_known_distance(self):
        # Approx 111 km per degree at equator
        d = haversine_distance_m(0, 0, 1, 0)
        assert abs(d - 111_194.9) < 100  # within 100m of expected


# ─── APF Engine Tests ────────────────────────────────────────────────

class TestAPFEngine:
    def _make_uav(self, uav_id, lat, lon, alt, vx=0, vy=0, vz=0, ts=None):
        return UAVState(
            uav_id=uav_id,
            timestamp=ts or time.time(),
            lat=lat, lon=lon,
            alt_relative_m=alt,
            vx=vx, vy=vy, vz=vz,
            current_seq=1,
            total_waypoints=3,
            flight_mode="AUTO",
            armed=True,
            gps_fix=3,
            target_lat=lat + 0.001,  # Target slightly ahead
            target_lon=lon,
            target_alt_m=alt,
        )

    def test_no_avoidance_when_far_apart(self):
        engine = APFEngine(APFConfig(d_influence=30, hysteresis_enter_m=25))
        # Two UAVs 100m apart
        uav1 = self._make_uav(1, -7.770, 110.380, 10)
        uav2 = self._make_uav(2, -7.771, 110.380, 10)  # ~111m south

        r1, r2 = engine.tick(uav1, uav2)
        assert not r1.avoidance_active
        assert not r2.avoidance_active

    def test_avoidance_activates_when_close(self):
        config = APFConfig(d_influence=50, hysteresis_enter_m=45)
        engine = APFEngine(config)
        # Two UAVs very close — ~11m apart
        uav1 = self._make_uav(1, -7.7700, 110.380, 10)
        uav2 = self._make_uav(2, -7.7701, 110.380, 10)

        r1, r2 = engine.tick(uav1, uav2)
        assert r1.avoidance_active
        assert r2.avoidance_active

    def test_stale_telemetry_skips_avoidance(self):
        engine = APFEngine(APFConfig(max_telemetry_age_s=2.0))
        old_ts = time.time() - 10  # 10 seconds old
        uav1 = self._make_uav(1, -7.770, 110.380, 10, ts=old_ts)
        uav2 = self._make_uav(2, -7.7701, 110.380, 10)

        r1, r2 = engine.tick(uav1, uav2)
        assert r1.stale
        assert not r1.avoidance_active
        # Corrected waypoint should be the original target
        assert r1.corrected_lat == uav1.target_lat
        assert r1.corrected_lon == uav1.target_lon

    def test_priority_uav_dodges_less(self):
        config = APFConfig(d_influence=50, hysteresis_enter_m=45)
        engine = APFEngine(config)
        # Close UAVs — both should activate, but offsets differ
        uav1 = self._make_uav(1, -7.7700, 110.380, 10)
        uav2 = self._make_uav(2, -7.7701, 110.380, 10)

        r1, r2 = engine.tick(uav1, uav2)
        # UAV1 is priority, UAV2 is not — UAV2 should dodge more
        # (r2.offset_m should generally be >= r1.offset_m)
        assert r1.avoidance_active
        assert r2.avoidance_active

    def test_distance_metrics(self):
        config = APFConfig(d_influence=100)
        engine = APFEngine(config)
        uav1 = self._make_uav(1, -7.770, 110.380, 10)
        uav2 = self._make_uav(2, -7.7705, 110.380, 10)  # ~55m apart

        r1, r2 = engine.tick(uav1, uav2)
        assert r1.d_ij > 0
        assert r1.d_ij == r2.d_ij  # Same distance from both perspectives

    def test_hysteresis_prevents_oscillation(self):
        config = APFConfig(
            d_influence=50,
            hysteresis_enter_m=20,
            hysteresis_exit_m=30,
        )
        engine = APFEngine(config)

        # Start close — should activate
        uav1 = self._make_uav(1, -7.7700, 110.380, 10)
        uav2 = self._make_uav(2, -7.77010, 110.380, 10)  # ~11m
        r1, _ = engine.tick(uav1, uav2)
        assert r1.avoidance_active

        # Move to 25m (between enter and exit thresholds) — should stay active
        uav2_mid = self._make_uav(2, -7.77023, 110.380, 10)  # ~25m
        r1_mid, _ = engine.tick(uav1, uav2_mid)
        assert r1_mid.avoidance_active  # Hysteresis keeps it active

    def test_reset_clears_state(self):
        engine = APFEngine()
        uav1 = self._make_uav(1, -7.770, 110.380, 10)
        uav2 = self._make_uav(2, -7.7701, 110.380, 10)
        engine.tick(uav1, uav2)

        engine.reset()
        assert len(engine._avoidance_state) == 0
        assert len(engine._prev_f_total) == 0

    def test_altitude_clamped(self):
        config = APFConfig(altitude_floor_m=2, altitude_ceiling_m=50)
        engine = APFEngine(config)
        uav1 = self._make_uav(1, -7.770, 110.380, 10)
        uav1.target_alt_m = 10
        uav2 = self._make_uav(2, -7.7701, 110.380, 10)

        r1, _ = engine.tick(uav1, uav2)
        assert r1.corrected_alt_m >= config.altitude_floor_m
        assert r1.corrected_alt_m <= config.altitude_ceiling_m


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
