"""Survey waypoint generation logic."""

import math
from typing import List, Tuple, Optional
from shapely.geometry import Polygon, LineString, Point, MultiLineString
from shapely.affinity import rotate

DEG_TO_RAD = math.pi / 180.0
RAD_TO_DEG = 180.0 / math.pi
EARTH_RADIUS_M = 6371000.0


def latlon_to_enu(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert global (lat/lon) to local ENU relative to a reference point (meters)."""
    d_lat = (lat - ref_lat) * DEG_TO_RAD
    d_lon = (lon - ref_lon) * DEG_TO_RAD

    north = d_lat * EARTH_RADIUS_M
    east = d_lon * EARTH_RADIUS_M * math.cos(ref_lat * DEG_TO_RAD)

    return east, north


def enu_to_latlon(east: float, north: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Convert local ENU back to global (lat/lon)."""
    lat = ref_lat + (north / EARTH_RADIUS_M) * RAD_TO_DEG
    lon = ref_lon + (east / (EARTH_RADIUS_M * math.cos(ref_lat * DEG_TO_RAD))) * RAD_TO_DEG
    return lat, lon


def get_longest_edge_angle(poly: Polygon) -> float:
    """Find the angle (in degrees, 0 = East, 90 = North) of the longest edge of the polygon."""
    coords = list(poly.exterior.coords)
    max_len_sq = -1
    best_angle = 0.0

    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i+1]
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx*dx + dy*dy
        if length_sq > max_len_sq:
            max_len_sq = length_sq
            best_angle = math.degrees(math.atan2(dy, dx))
            
    return best_angle


def generate_lawnmower_path_enu(
    enu_polygon: Polygon,
    spacing_m: float,
    sweep_angle_deg: Optional[float] = None,
    margin_m: float = 0.0
) -> List[Tuple[float, float]]:
    """Generate boustrophedon (lawnmower) path inside a polygon."""
    
    # 1. Apply safety margin (shrink polygon)
    working_poly = enu_polygon
    if margin_m > 0:
        working_poly = enu_polygon.buffer(-margin_m)
        if working_poly.is_empty:
            raise ValueError("Polygon becomes empty after applying safety margin.")

    # 2. Determine sweep angle
    if sweep_angle_deg is None:
        sweep_angle_deg = get_longest_edge_angle(working_poly)
        
    # We want sweep lines to be horizontal, so we rotate the polygon by -sweep_angle_deg
    # This aligns the sweep direction with the X axis.
    rotated_poly = rotate(working_poly, -sweep_angle_deg, origin='centroid', use_radians=False)
    
    # 3. Get bounding box of the rotated polygon
    minx, miny, maxx, maxy = rotated_poly.bounds
    
    # 4. Create horizontal sweep lines
    lines = []
    y = miny + (spacing_m / 2.0)
    while y <= maxy:
        # Create a line strictly wider than the bounding box
        line = LineString([(minx - 100, y), (maxx + 100, y)])
        lines.append(line)
        y += spacing_m

    # 5. Intersect lines with the polygon
    path_segments = []
    for line in lines:
        intersection = rotated_poly.intersection(line)
        if intersection.is_empty:
            continue
            
        if isinstance(intersection, LineString):
            path_segments.append(list(intersection.coords))
        elif isinstance(intersection, MultiLineString):
            for geom in intersection.geoms:
                path_segments.append(list(geom.coords))
                
    if not path_segments:
        return []

    # 6. Order segments in Boustrophedon pattern
    ordered_coords = []
    go_right = True
    
    for segment in path_segments:
        # Sort segment by X coordinate to ensure consistent direction
        sorted_seg = sorted(segment, key=lambda p: p[0])
        
        if go_right:
            ordered_coords.extend(sorted_seg)
        else:
            ordered_coords.extend(reversed(sorted_seg))
            
        go_right = not go_right
        
    # 7. Rotate back to original orientation
    final_path = []
    for (x, y) in ordered_coords:
        pt = rotate(Point(x, y), sweep_angle_deg, origin=working_poly.centroid, use_radians=False)
        final_path.append((pt.x, pt.y))
        
    return final_path


def generate_survey_path_latlon(
    latlon_polygon: List[Tuple[float, float]],
    spacing_m: float,
    sweep_angle_deg: Optional[float] = None,
    margin_m: float = 0.0
) -> List[Tuple[float, float]]:
    """Full pipeline: WGS84 -> ENU -> Generate -> WGS84"""
    
    if len(latlon_polygon) < 3:
        raise ValueError("Polygon must have at least 3 vertices.")
        
    ref_lat, ref_lon = latlon_polygon[0]
    
    enu_coords = [latlon_to_enu(lat, lon, ref_lat, ref_lon) for (lat, lon) in latlon_polygon]
    poly = Polygon(enu_coords)
    
    enu_path = generate_lawnmower_path_enu(poly, spacing_m, sweep_angle_deg, margin_m)
    
    latlon_path = [enu_to_latlon(e, n, ref_lat, ref_lon) for (e, n) in enu_path]
    return latlon_path


def partition_polygon(enu_polygon: Polygon, sweep_angle_deg: float) -> Tuple[Polygon, Polygon]:
    """Split the polygon into two contiguous halves perpendicular to the sweep direction."""
    # Rotate so sweep is horizontal (X axis)
    rotated_poly = rotate(enu_polygon, -sweep_angle_deg, origin='centroid', use_radians=False)
    
    minx, miny, maxx, maxy = rotated_poly.bounds
    mid_x = minx + (maxx - minx) / 2.0
    
    # Create two large boxes for left and right halves
    # Since sweeps are horizontal, left/right split creates contiguous blocks of horizontal sweeps
    left_box = Polygon([
        (minx - 100, miny - 100), (mid_x, miny - 100),
        (mid_x, maxy + 100), (minx - 100, maxy + 100)
    ])
    
    right_box = Polygon([
        (mid_x, miny - 100), (maxx + 100, miny - 100),
        (maxx + 100, maxy + 100), (mid_x, maxy + 100)
    ])
    
    left_part = rotated_poly.intersection(left_box)
    right_part = rotated_poly.intersection(right_box)
    
    # Rotate back
    part1 = rotate(left_part, sweep_angle_deg, origin=enu_polygon.centroid, use_radians=False)
    part2 = rotate(right_part, sweep_angle_deg, origin=enu_polygon.centroid, use_radians=False)
    
    return part1, part2


def calculate_path_distance(path: List[Tuple[float, float]]) -> float:
    dist = 0.0
    for i in range(len(path) - 1):
        dist += math.hypot(path[i+1][0] - path[i][0], path[i+1][1] - path[i][1])
    return dist


def generate_dual_survey_path_latlon(
    latlon_polygon: List[Tuple[float, float]],
    spacing_m: float,
    sweep_angle_deg: Optional[float] = None,
    margin_m: float = 0.0
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Generate two paths for two UAVs from one polygon."""
    
    if len(latlon_polygon) < 3:
        raise ValueError("Polygon must have at least 3 vertices.")
        
    ref_lat, ref_lon = latlon_polygon[0]
    
    enu_coords = [latlon_to_enu(lat, lon, ref_lat, ref_lon) for (lat, lon) in latlon_polygon]
    poly = Polygon(enu_coords)
    
    working_poly = poly
    if margin_m > 0:
        working_poly = poly.buffer(-margin_m)
        if working_poly.is_empty:
            raise ValueError("Polygon becomes empty after applying safety margin.")
            
    if sweep_angle_deg is None:
        sweep_angle_deg = get_longest_edge_angle(working_poly)
        
    part1, part2 = partition_polygon(working_poly, sweep_angle_deg)
    
    path1_enu = generate_lawnmower_path_enu(part1, spacing_m, sweep_angle_deg, 0.0) # margin already applied
    path2_enu = generate_lawnmower_path_enu(part2, spacing_m, sweep_angle_deg, 0.0)
    
    path1_latlon = [enu_to_latlon(e, n, ref_lat, ref_lon) for (e, n) in path1_enu]
    path2_latlon = [enu_to_latlon(e, n, ref_lat, ref_lon) for (e, n) in path2_enu]
    
    return path1_latlon, path2_latlon
