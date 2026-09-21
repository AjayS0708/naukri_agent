import { useEffect, useState } from "react";
import { Play, Square, Pause, RotateCcw, Power, Clock, Layers, Database } from "lucide-react";

interface LifecycleStatus {
  agent_state: string;
  scheduler: {
    is_running: boolean;
    is_paused: boolean;
    interval_minutes: number;
    last_run_at: string | null;
    next_run_at: string | null;
    enabled: boolean;
  } | null;
  ai_queue: {
    total_queued: number;
    total_processing: number;
    total_completed: number;
    total_items: number;
  } | null;
  prerequisites: {
    valid: boolean;
    missing: string[];
  };
}

interface AutoStartStatus {
  enabled: boolean;
  platform: string;
  task_name: string;
  supported: boolean;
}

export function AgentControl() {
  const [lifecycleStatus, setLifecycleStatus] = useState<LifecycleStatus | null>(null);
  const [autoStartStatus, setAutoStartStatus] = useState<AutoStartStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchStatus = async () => {
    try {
      const [lifecycleRes, autoStartRes] = await Promise.all([
        fetch("/api/agent/status"),
        fetch("/api/system/autostart")
      ]);
      
      if (lifecycleRes.ok) {
        const lifecycle = await lifecycleRes.json();
        setLifecycleStatus(lifecycle);
      }
      
      if (autoStartRes.ok) {
        const autoStart = await autoStartRes.json();
        setAutoStartStatus(autoStart);
      }
    } catch (error) {
      console.error("Failed to fetch status:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000); // Poll every 5 seconds
    return () => clearInterval(interval);
  }, []);

  const handleAction = async (action: string) => {
    setActionLoading(action);
    try {
      const res = await fetch(`/api/agent/${action}`, { method: "POST" });
      if (res.ok) {
        await fetchStatus();
      }
    } catch (error) {
      console.error(`Failed to ${action}:`, error);
    } finally {
      setActionLoading(null);
    }
  };

  const handleAutoStartToggle = async () => {
    if (!autoStartStatus) return;
    
    setActionLoading("autostart");
    try {
      const endpoint = autoStartStatus.enabled ? "/api/system/autostart/disable" : "/api/system/autostart/enable";
      const res = await fetch(endpoint, { 
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });
      if (res.ok) {
        await fetchStatus();
      }
    } catch (error) {
      console.error("Failed to toggle auto-start:", error);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading) {
    return <section className="status-panel"><div><p className="eyebrow">AGENT CONTROL</p><strong>Loading...</strong></div></section>;
  }

  const agentState = lifecycleStatus?.agent_state ?? "UNKNOWN";
  const isIdle = agentState === "IDLE";
  const isRunning = agentState === "RUNNING";
  const isPaused = agentState === "PAUSED";
  const isStopped = agentState === "STOPPED";
  const prerequisitesValid = lifecycleStatus?.prerequisites.valid ?? false;

  return <section className="status-panel">
    <div>
      <p className="eyebrow">AGENT CONTROL</p>
      <strong className={`agent-state ${agentState.toLowerCase()}`}>{agentState.replace(/_/g, " ")}</strong>
      {!prerequisitesValid && (
        <p className="warning-text">Missing prerequisites: {lifecycleStatus?.prerequisites.missing.join(", ")}</p>
      )}
    </div>
    
    <div className="control-buttons">
      {(isIdle || isStopped) && (
        <button 
          onClick={() => handleAction("start")}
          disabled={actionLoading === "start" || !prerequisitesValid}
          className="btn btn-primary"
        >
          <Play size={16} />
          {actionLoading === "start" ? "Starting..." : "Start"}
        </button>
      )}
      
      {isRunning && (
        <>
          <button 
            onClick={() => handleAction("pause")}
            disabled={actionLoading === "pause"}
            className="btn btn-secondary"
          >
            <Pause size={16} />
            {actionLoading === "pause" ? "Pausing..." : "Pause"}
          </button>
          <button 
            onClick={() => handleAction("stop")}
            disabled={actionLoading === "stop"}
            className="btn btn-danger"
          >
            <Square size={16} />
            {actionLoading === "stop" ? "Stopping..." : "Stop"}
          </button>
        </>
      )}
      
      {isPaused && (
        <>
          <button 
            onClick={() => handleAction("resume")}
            disabled={actionLoading === "resume" || !prerequisitesValid}
            className="btn btn-primary"
          >
            <RotateCcw size={16} />
            {actionLoading === "resume" ? "Resuming..." : "Resume"}
          </button>
          <button 
            onClick={() => handleAction("stop")}
            disabled={actionLoading === "stop"}
            className="btn btn-danger"
          >
            <Square size={16} />
            {actionLoading === "stop" ? "Stopping..." : "Stop"}
          </button>
        </>
      )}
    </div>

    {lifecycleStatus?.scheduler && (
      <div className="status-meta">
        <span><Clock size={14} /> Scheduler</span>
        <b>{lifecycleStatus.scheduler.is_running ? "Running" : "Stopped"}</b>
        {lifecycleStatus.scheduler.is_paused && <span className="paused-badge">Paused</span>}
      </div>
    )}

    {lifecycleStatus?.ai_queue && (
      <div className="status-meta">
        <span><Layers size={14} /> AI Queue</span>
        <b>{lifecycleStatus.ai_queue.total_queued} queued / {lifecycleStatus.ai_queue.total_processing} processing</b>
      </div>
    )}

    {autoStartStatus?.supported && (
      <div className="status-meta">
        <span><Power size={14} /> Windows Auto-Start</span>
        <button 
          onClick={handleAutoStartToggle}
          disabled={actionLoading === "autostart"}
          className={`toggle-btn ${autoStartStatus.enabled ? "enabled" : ""}`}
        >
          {actionLoading === "autostart" ? "..." : autoStartStatus.enabled ? "ON" : "OFF"}
        </button>
      </div>
    )}
  </section>;
}
