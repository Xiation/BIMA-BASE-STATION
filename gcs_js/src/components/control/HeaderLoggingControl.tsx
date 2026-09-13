import { useState, useEffect } from "react";
import Swal from "sweetalert2";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface LoggingStatus {
  active: boolean;
  session: {
    id: string;
    start_time: string;
    data_count: number;
  } | null;
}

export function HeaderLoggingControl() {
  const [status, setStatus] = useState<LoggingStatus>({
    active: false,
    session: null,
  });
  const [loading, setLoading] = useState(false);
  const [localDuration, setLocalDuration] = useState(0);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/logging/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (err) {
      console.error("Failed to fetch logging status", err);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (status.active && status.session?.start_time) {
      const startMs = new Date(status.session.start_time).getTime();
      const tick = () => {
        setLocalDuration(Math.floor((Date.now() - startMs) / 1000));
      };
      tick();
      const timer = setInterval(tick, 1000);
      return () => clearInterval(timer);
    } else {
      setLocalDuration(0);
    }
  }, [status.active, status.session?.start_time]);

  const handleStart = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/logging/start`, { method: "POST" });
      if (res.ok) await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    const result = await Swal.fire({
      title: 'Stop Logging',
      text: 'Masukkan nama untuk sesi logging ini (opsional):',
      input: 'text',
      inputPlaceholder: 'Misal: Penerbangan Mode Auto',
      showCancelButton: true,
      confirmButtonText: 'Stop & Save',
      cancelButtonText: 'Cancel',
      background: '#161616',
      color: '#ededed',
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#3a3a3c',
      customClass: {
        popup: 'sweet-logging-popup',
        input: 'sweet-logging-input'
      }
    });

    if (result.isDismissed) return; // User cancelled

    const sessionName = result.value || null;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/logging/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: sessionName })
      });
      if (res.ok) await fetchStatus();
    } finally {
      setLoading(false);
    }
  };

  const formatDuration = (sec: number) => {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return `${h.toString().padStart(2, "0")}:${m
      .toString()
      .padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  return (
    <div className={`header-logging-control ${status.active ? "header-logging-control--active" : ""}`}>
      {status.active && (
        <span className="logging-badge__dot" style={{ color: '#ef4444' }} />
      )}
      
      {status.active && status.session ? (
        <>
          <span className="header-logging-control__timer" style={{ fontSize: '12px' }}>
            {formatDuration(localDuration)}
          </span>
          <span className="header-logging-control__count" style={{ fontSize: '11px' }}>
            {status.session.data_count.toLocaleString()}
          </span>
          <button
            type="button"
            className="header-logging-control__btn header-logging-control__btn--stop"
            onClick={handleStop}
            disabled={loading}
            style={{ padding: '3px 10px', fontSize: '11px' }}
          >
            <svg width="10" height="10" viewBox="0 0 14 14" fill="currentColor">
              <rect x="1" y="1" width="12" height="12" rx="2" />
            </svg>
            Stop
          </button>
        </>
      ) : (
        <button
          type="button"
          className="header-logging-control__btn header-logging-control__btn--start"
          onClick={handleStart}
          disabled={loading}
          style={{ padding: '3px 10px', fontSize: '11px' }}
        >
          <svg width="10" height="10" viewBox="0 0 14 14" fill="currentColor">
            <circle cx="7" cy="7" r="6" />
          </svg>
          Start Logging
        </button>
      )}
    </div>
  );
}
