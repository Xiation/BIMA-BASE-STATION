"use client";

import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, FeatureGroup, Polyline, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";

interface SwarmSurveyMapProps {
  onPolygonCreated: (vertices: number[][]) => void;
  onPolygonEdited: (vertices: number[][]) => void;
  onPolygonDeleted: () => void;
  uav3Path?: number[][];
  uav4Path?: number[][];
}

function GeomanControls({ onPolygonCreated, onPolygonEdited, onPolygonDeleted }: Omit<SwarmSurveyMapProps, "uav3Path" | "uav4Path">) {
  const map = useMap();
  const fgRef = useRef<L.FeatureGroup>(null);

  useEffect(() => {
    if (!map) return;

    map.pm.addControls({
      position: "topleft",
      drawMarker: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawRectangle: true,
      drawPolygon: true,
      drawCircle: false,
      drawText: false,
      editMode: true,
      dragMode: true,
      cutPolygon: false,
      removalMode: true,
    });

    map.pm.setGlobalOptions({
      allowSelfIntersection: false,
      snappable: true,
      layerGroup: map,
    });

    map.on("pm:create", (e) => {
      const layer = e.layer;
      
      // Allow only one polygon
      map.eachLayer((l) => {
        if (l instanceof L.Polygon && l !== layer) {
          map.removeLayer(l);
        }
      });

      const getCoords = (l: any) => {
        const latlngs = l.getLatLngs()[0];
        return latlngs.map((ll: L.LatLng) => [ll.lat, ll.lng]);
      };

      onPolygonCreated(getCoords(layer));

      layer.on("pm:edit", (evt) => {
        onPolygonEdited(getCoords(evt.layer));
      });
      layer.on("pm:dragend", (evt) => {
        onPolygonEdited(getCoords(evt.layer));
      });
    });

    map.on("pm:remove", (e) => {
      onPolygonDeleted();
    });

    return () => {
      map.pm.removeControls();
      map.off("pm:create");
      map.off("pm:remove");
    };
  }, [map, onPolygonCreated, onPolygonEdited, onPolygonDeleted]);

  return <FeatureGroup ref={fgRef} />;
}

export function SwarmSurveyMap({ onPolygonCreated, onPolygonEdited, onPolygonDeleted, uav3Path, uav4Path }: SwarmSurveyMapProps) {
  // Center roughly at UGM or fallback coordinates
  const center: [number, number] = [-7.77126, 110.37765];

  return (
    <div style={{ height: "400px", width: "100%", borderRadius: "8px", overflow: "hidden", border: "1px solid #4b5563" }}>
      <MapContainer center={center} zoom={18} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
          maxZoom={22}
          maxNativeZoom={20}
          attribution="&copy; Google Satellite"
        />
        <GeomanControls 
          onPolygonCreated={onPolygonCreated} 
          onPolygonEdited={onPolygonEdited} 
          onPolygonDeleted={onPolygonDeleted} 
        />
        
        {uav3Path && uav3Path.length > 0 && (
          <Polyline positions={uav3Path as [number, number][]} color="#f97316" weight={3} />
        )}
        
        {uav4Path && uav4Path.length > 0 && (
          <Polyline positions={uav4Path as [number, number][]} color="#ec4899" weight={3} />
        )}
      </MapContainer>
    </div>
  );
}
