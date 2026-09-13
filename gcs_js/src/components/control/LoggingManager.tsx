"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface LoggingSession {
  id: string;
  name?: string | null;
  filename: string;
  start_time: string;
  end_time: string | null;
  duration_s: number;
  data_count: number;
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("id-ID", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function LoggingManager() {
  const [sessions, setSessions] = useState<LoggingSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailSession, setDetailSession] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<Record<string, unknown>[] | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/logging/sessions`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setSessions(data);
      }
    } catch {
      // Ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    const interval = setInterval(fetchSessions, 5000);
    return () => clearInterval(interval);
  }, [fetchSessions]);

  const handleViewDetail = useCallback(async (sessionId: string) => {
    setDetailSession(sessionId);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const res = await fetch(`${API_BASE}/api/logging/sessions/${sessionId}/data`);
      const json = await res.json();
      if (json.data) {
        setDetailData(json.data);
      }
    } catch {
      setDetailData([]);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleCloseDetail = useCallback(() => {
    setDetailSession(null);
    setDetailData(null);
  }, []);

  const handleDelete = useCallback(async (sessionId: string) => {
    try {
      await fetch(`${API_BASE}/api/logging/sessions/${sessionId}`, {
        method: "DELETE",
      });
      setDeleteConfirm(null);
      fetchSessions();
    } catch {
      // Ignore
    }
  }, [fetchSessions]);

  const handleExportCSV = useCallback((sessionId: string) => {
    const url = `${API_BASE}/api/logging/sessions/${sessionId}/csv`;
    const a = document.createElement("a");
    a.href = url;
    a.download = `logging_${sessionId}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, []);

  // Collect all data keys for detail table
  const detailKeys: string[] = [];
  if (detailData && detailData.length > 0) {
    const seen = new Set<string>();
    for (const row of detailData) {
      for (const key of Object.keys(row)) {
        if (!seen.has(key)) {
          detailKeys.push(key);
          seen.add(key);
        }
      }
    }
  }

  return (
    <div className="logging-page">
      <div className="logging-page__header">
        <div className="logging-page__title-group">
          <h1 className="logging-page__title">Data Logging</h1>
          <p className="logging-page__subtitle">
            Manage recorded telemetry sessions — view, export, or delete.
          </p>
        </div>
        <div className="logging-page__summary">
          <div className="logging-page__stat">
            <span className="logging-page__stat-value">{sessions.length}</span>
            <span className="logging-page__stat-label">Sessions</span>
          </div>
          <div className="logging-page__stat">
            <span className="logging-page__stat-value">
              {sessions.reduce((sum, s) => sum + s.data_count, 0).toLocaleString()}
            </span>
            <span className="logging-page__stat-label">Total Samples</span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="logging-page__loading">
          <div className="logging-page__spinner" />
          Loading sessions…
        </div>
      ) : sessions.length === 0 ? (
        <div className="logging-page__empty">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="8" y="8" width="48" height="48" rx="8" />
            <circle cx="32" cy="28" r="8" />
            <line x1="20" y1="44" x2="44" y2="44" />
            <line x1="24" y1="50" x2="40" y2="50" />
          </svg>
          <p>No logging sessions yet.</p>
          <span>Use the <strong>Start Logging</strong> button on the dashboard to begin recording telemetry data.</span>
        </div>
      ) : (
        <div className="logging-page__table-wrapper">
          <table className="logging-sessions-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Session Name / ID</th>
                <th>Start Time</th>
                <th>End Time</th>
                <th>Duration</th>
                <th>Samples</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session, index) => {
                const isActive = session.end_time === null;
                return (
                  <tr key={session.id} className={isActive ? "is-active-session" : ""}>
                    <td className="cell-index">{sessions.length - index}</td>
                    <td className="cell-id">
                      {session.name ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <span style={{ fontWeight: 600 }}>{session.name}</span>
                          <code style={{ fontSize: '10px', opacity: 0.7 }}>{session.id}</code>
                        </div>
                      ) : (
                        <code>{session.id}</code>
                      )}
                    </td>
                    <td>{formatDateTime(session.start_time)}</td>
                    <td>{formatDateTime(session.end_time)}</td>
                    <td className="cell-mono">{formatDuration(session.duration_s)}</td>
                    <td className="cell-mono">{session.data_count.toLocaleString()}</td>
                    <td>
                      {isActive ? (
                        <span className="logging-badge logging-badge--active">
                          <span className="logging-badge__dot" />
                          Recording
                        </span>
                      ) : (
                        <span className="logging-badge logging-badge--complete">
                          Complete
                        </span>
                      )}
                    </td>
                    <td className="cell-actions">
                      <button
                        type="button"
                        className="logging-action-btn logging-action-btn--view"
                        onClick={() => handleViewDetail(session.id)}
                        title="View detail data"
                      >
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5Z" />
                          <circle cx="8" cy="8" r="2" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        className="logging-action-btn logging-action-btn--export"
                        onClick={() => handleExportCSV(session.id)}
                        title="Export as CSV"
                        disabled={isActive}
                      >
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M3 10v3h10v-3" />
                          <path d="M8 2v8" />
                          <path d="M5 7l3 3 3-3" />
                        </svg>
                      </button>
                      <button
                        type="button"
                        className="logging-action-btn logging-action-btn--delete"
                        onClick={() => setDeleteConfirm(session.id)}
                        title="Delete session"
                        disabled={isActive}
                      >
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                          <path d="M2 4h12" />
                          <path d="M5 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1" />
                          <path d="M4 4l1 10h6l1-10" />
                          <line x1="7" y1="7" x2="7" y2="11" />
                          <line x1="9" y1="7" x2="9" y2="11" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="logging-modal-overlay" onClick={() => setDeleteConfirm(null)}>
          <div
            className="logging-modal logging-modal--delete"
            onClick={(e) => e.stopPropagation()}
          >
            <h3>Delete Session</h3>
            <p>
              Are you sure you want to delete session <code>{deleteConfirm}</code>?
              This action cannot be undone.
            </p>
            <div className="logging-modal__actions">
              <button
                type="button"
                className="logging-modal__btn logging-modal__btn--cancel"
                onClick={() => setDeleteConfirm(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="logging-modal__btn logging-modal__btn--danger"
                onClick={() => handleDelete(deleteConfirm)}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail Data Modal */}
      {detailSession && (
        <div className="logging-modal-overlay" onClick={handleCloseDetail}>
          <div
            className="logging-modal logging-modal--detail"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="logging-modal__header">
              <h3>
                Session Data
                <code>{detailSession}</code>
              </h3>
              <button
                type="button"
                className="logging-modal__close"
                onClick={handleCloseDetail}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className="logging-modal__body">
              {detailLoading ? (
                <div className="logging-page__loading">
                  <div className="logging-page__spinner" />
                  Loading data…
                </div>
              ) : !detailData || detailData.length === 0 ? (
                <p className="logging-modal__empty">No data in this session.</p>
              ) : (
                <>
                  <div className="logging-modal__info">
                    {detailData.length.toLocaleString()} rows × {detailKeys.length} columns
                  </div>
                  <div className="logging-detail-table-wrapper">
                    <table className="logging-detail-table">
                      <thead>
                        <tr>
                          {detailKeys.map((key) => (
                            <th key={key}>{key}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {detailData.map((row, i) => (
                          <tr key={i}>
                            {detailKeys.map((key) => (
                              <td key={key}>
                                {row[key] !== undefined && row[key] !== null
                                  ? typeof row[key] === "number"
                                    ? (row[key] as number) % 1 !== 0
                                      ? (row[key] as number).toFixed(4)
                                      : String(row[key])
                                    : String(row[key])
                                  : "—"}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>

            <div className="logging-modal__footer">
              <button
                type="button"
                className="logging-modal__btn logging-modal__btn--cancel"
                onClick={handleCloseDetail}
              >
                Close
              </button>
              {detailData && detailData.length > 0 && (
                <button
                  type="button"
                  className="logging-modal__btn logging-modal__btn--primary"
                  onClick={() => handleExportCSV(detailSession)}
                >
                  Export CSV
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
