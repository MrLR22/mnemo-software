import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Activity, BookOpen, Box, Film, LayoutDashboard, MessageSquareText, Moon, Sun } from "lucide-react";

import { get, type Health, type ServiceHealth } from "../lib/api";
import { useData } from "../lib/hooks";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/recordings", label: "Recordings", icon: Film },
  { to: "/ask", label: "Ask", icon: MessageSquareText },
  { to: "/objects", label: "Objects", icon: Box },
  { to: "/diary", label: "Diary", icon: BookOpen },
  { to: "/system", label: "System", icon: Activity },
];

export const isUp = (s: ServiceHealth | undefined) => typeof s === "object" && s !== null;

export function Logo() {
  return (
    <span className="logo">
      <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
        <rect width="32" height="32" rx="6" className="logo-bg" />
        <g className="logo-bars">
          <rect x="7" y="11" width="4" height="13" rx="1" />
          <rect x="14" y="7" width="4" height="17" rx="1" />
          <rect x="21" y="14" width="4" height="10" rx="1" />
        </g>
      </svg>
      <span className="logo-word">mnemo</span>
    </span>
  );
}

function Theme() {
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? "dark");
  const flip = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("mnemo_theme", next); } catch { /* private window */ }
    setTheme(next);
  };
  return (
    <button className="icon-btn" onClick={flip} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            aria-label="Switch theme">
      {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

export function Shell() {
  const { data, error } = useData(() => get<Health>("/api/health"), [], 15000);
  const parts = [
    { name: "Backend", up: !error && !!data },
    { name: "Database", up: !!data && !data.database.startsWith("unreachable") },
    { name: "Small model", up: isUp(data?.small_model) },
    { name: "Big model", up: isUp(data?.big_model) },
  ];
  return (
    <div className="shell">
      <aside className="side">
        <NavLink to="/" className="side-brand"><Logo /></NavLink>
        <nav className="side-nav">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
              <Icon size={16} strokeWidth={1.75} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <NavLink to="/system" className="side-status">
            {parts.map((p) => (
              <div key={p.name} className="side-status-row">
                <span className={`dot ${p.up ? "up" : data || error ? "down" : "wait"}`} /><span>{p.name}</span>
              </div>
            ))}
          </NavLink>
          <Theme />
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
