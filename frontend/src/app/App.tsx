import { useEffect, useState } from "react";
import { Activity, Bot, BriefcaseBusiness, ChartNoAxesColumn, CircleAlert, Settings, Sparkles } from "lucide-react";
import { getHealth } from "../services/api";
import type { HealthResponse, ProfileResponse } from "../types/api";
import { ProfileWorkspace } from "../components/ProfileWorkspace";

const metrics = [["Applications today", "0", BriefcaseBusiness], ["Jobs discovered", "Not available", ChartNoAxesColumn], ["Jobs analyzed", "Not available", Sparkles], ["Needs attention", "0", CircleAlert]] as const;

export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [, setProfile] = useState<ProfileResponse | null>(null);
  useEffect(() => { getHealth().then(setHealth).catch(() => setFailed(true)); }, []);
  const connection = failed ? "Backend unavailable" : health ? "Connected" : "Checking";
  return <main className="app-shell">
    <aside className="sidebar"><div className="brand"><Bot size={22} /><span>Naukri Agent</span></div><nav aria-label="Primary navigation"><a className="nav-item active" href="#overview"><Activity size={18} />Overview</a><a className="nav-item" href="#profile"><Settings size={18} />Profile</a><span className="nav-item disabled"><BriefcaseBusiness size={18} />Applications</span><span className="nav-item disabled"><ChartNoAxesColumn size={18} />Jobs</span></nav><p className="phase-note">Profile foundation<br />Phase 2</p></aside>
    <section className="content" id="overview"><header className="topbar"><div><p className="eyebrow">LOCAL WORKSPACE</p><h1>Agent overview</h1></div><span className={`connection ${failed ? "offline" : ""}`}><i />{connection}</span></header>
      <section className="status-panel"><div><p className="eyebrow">AGENT STATUS</p><strong>{health?.agent_state.replaceAll("_", " ") ?? "NOT RUNNING"}</strong><p>Automation is not configured in this foundation phase.</p></div><div className="status-meta"><span>Backend</span><b>{health ? `${health.service} v${health.version}` : "Not available"}</b></div></section>
      <section className="metrics">{metrics.map(([label, value, Icon]) => <article className="metric" key={label}><Icon size={19} /><p>{label}</p><strong>{value}</strong></article>)}</section>
      <section className="activity"><div><p className="eyebrow">LIVE ACTIVITY</p><h2>Ready for the next phase</h2></div><p>No discovery, AI analysis, or application actions have been enabled.</p></section>
      <section id="profile"><ProfileWorkspace onProfileChange={setProfile} /></section>
    </section></main>;
}
