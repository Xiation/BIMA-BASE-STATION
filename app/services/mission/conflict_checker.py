"""Offline trajectory simulation and conflict detection for generated missions."""

import math
from typing import List, Tuple, Optional
from app.schemas.swarm_mission import TrajectoryConflict
from app.services.mission.survey_generator import latlon_to_enu

def interpolate_position(path: List[Tuple[float, float]], speed: float, time: float) -> Optional[Tuple[float, float]]:
    """Get the (east, north) position along a path at a given time."""
    if not path or time < 0:
        return None
        
    current_time = 0.0
    for i in range(len(path) - 1):
        x1, y1 = path[i]
        x2, y2 = path[i+1]
        
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        
        segment_time = dist / speed if speed > 0 else 0
        
        if current_time + segment_time >= time:
            # The point is on this segment
            progress = (time - current_time) / segment_time if segment_time > 0 else 0
            curr_x = x1 + dx * progress
            curr_y = y1 + dy * progress
            return (curr_x, curr_y)
            
        current_time += segment_time
        
    # Time is beyond the end of the path
    return path[-1]


def check_conflicts(
    path_3_latlon: List[Tuple[float, float]], 
    path_4_latlon: List[Tuple[float, float]], 
    speed_ms: float,
    min_separation_m: float
) -> List[TrajectoryConflict]:
    """Simulate paths and return list of conflicts if any."""
    
    if not path_3_latlon or not path_4_latlon:
        return []
        
    ref_lat, ref_lon = path_3_latlon[0]
    
    path_3_enu = [latlon_to_enu(lat, lon, ref_lat, ref_lon) for lat, lon in path_3_latlon]
    path_4_enu = [latlon_to_enu(lat, lon, ref_lat, ref_lon) for lat, lon in path_4_latlon]
    
    # Calculate total times
    def get_time(path):
        dist = 0
        for i in range(len(path) - 1):
            dist += math.hypot(path[i+1][0] - path[i][0], path[i+1][1] - path[i][1])
        return dist / speed_ms if speed_ms > 0 else 0
        
    time_3 = get_time(path_3_enu)
    time_4 = get_time(path_4_enu)
    max_time = max(time_3, time_4)
    
    conflicts = []
    
    # Simulate every 1 second
    t = 0.0
    in_conflict = False
    
    while t <= max_time:
        p3 = interpolate_position(path_3_enu, speed_ms, t)
        p4 = interpolate_position(path_4_enu, speed_ms, t)
        
        if p3 and p4:
            dist = math.hypot(p3[0] - p4[0], p3[1] - p4[1])
            if dist < min_separation_m:
                if not in_conflict:
                    conflicts.append(TrajectoryConflict(
                        time_s=t,
                        uav_3_pos=[p3[0], p3[1], 0], # ENU for now, or we can map back to lat/lon
                        uav_4_pos=[p4[0], p4[1], 0],
                        horizontal_sep_m=dist,
                        vertical_sep_m=0.0,
                        description=f"Horizontal separation {dist:.1f}m < {min_separation_m}m"
                    ))
                    in_conflict = True
            else:
                in_conflict = False
                
        t += 1.0
        
    return conflicts
