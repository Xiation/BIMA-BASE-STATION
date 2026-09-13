/** REST helpers for swarm orchestration endpoints. */

import type {
  MissionBatchUploadRequest,
  MissionBatchUploadResponse,
  SwarmAbortRequest,
  SwarmAbortResponse,
  SwarmStartRequest,
  SwarmStartResponse,
  SwarmStatusResponse,
} from "@/types/swarm";

export const SWARM_API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class SwarmApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "SwarmApiError";
    this.status = status;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${SWARM_API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const err = payload as { detail?: string } | null;
    throw new SwarmApiError(
      err?.detail || `Swarm API request failed (${response.status})`,
      response.status,
    );
  }
  return payload as T;
}

/** Get full swarm status snapshot. */
export async function fetchSwarmStatus(): Promise<SwarmStatusResponse> {
  return requestJson<SwarmStatusResponse>("/api/swarm/status");
}

/** Upload missions to both copters in one action. */
export async function uploadBatchMission(payload: {
  mission_uav_3: any[];
  mission_uav_4: any[];
  ip_3?: string;
  port_3?: number;
  ip_4?: string;
  port_4?: number;
}): Promise<MissionBatchUploadResponse> {
  return requestJson<MissionBatchUploadResponse>("/api/swarm/upload", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Send coordinated start to both copters. */
export async function startSwarmMission(
  request: SwarmStartRequest = { confirmation: "CONFIRM_START" },
): Promise<SwarmStartResponse> {
  return requestJson<SwarmStartResponse>("/api/swarm/start", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** Emergency abort both copters. */
export async function abortSwarmMission(
  request: SwarmAbortRequest = { reason: "User abort" },
): Promise<SwarmAbortResponse> {
  return requestJson<SwarmAbortResponse>("/api/swarm/abort", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** Reset swarm state to IDLE. */
export async function resetSwarm(): Promise<SwarmStatusResponse> {
  return requestJson<SwarmStatusResponse>("/api/swarm/reset", {
    method: "POST",
  });
}

/** Generate survey mission items from parameters. */
export async function generateSwarmMission(
  payload: any,
): Promise<any> {
  return requestJson<any>("/api/swarm/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
