import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  FiArrowUpRight,
  FiBookOpen,
  FiHome,
  FiMessageSquare,
  FiPlus,
  FiChevronRight,
} from "react-icons/fi";
import { apiBaseUrl } from "../lib/liveService";
import buddyLogo from "../assets/BuddysBirthday.png";

export default function AppShell() {
  const { pathname, search } = useLocation();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);
  const live = Boolean(apiBaseUrl());
  const mode = new URLSearchParams(search).get("mode");
  const section =
    pathname === "/submit"
      ? "Add a resource"
      : pathname === "/ask"
        ? mode === "live" && live
          ? "Ask live"
          : "Explore demo"
        : "Overview";
  useEffect(() => {
    document.title = `${section} · Buddy’s Brain`;
    if (previousPath.current !== pathname) {
      window.scrollTo(0, 0);
      main.current?.focus({ preventScroll: true });
      previousPath.current = pathname;
    }
  }, [pathname, section]);
  const links = [
    { to: "/", name: "Overview", icon: FiHome, active: pathname === "/" },
    {
      to: "/ask",
      name: "Explore demo",
      icon: FiBookOpen,
      active: pathname === "/ask" && (mode !== "live" || !live),
    },
    ...(live
      ? [
          {
            to: "/ask?mode=live",
            name: "Ask live",
            icon: FiMessageSquare,
            active: pathname === "/ask" && mode === "live",
          },
          {
            to: "/submit",
            name: "Add a resource",
            icon: FiPlus,
            active: pathname === "/submit",
          },
        ]
      : []),
  ];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="Buddy’s Brain home">
          <img src={buddyLogo} alt="" />
          <span>
            buddy’s brain
            <span className="brand-caption">A little clarity, every day.</span>
          </span>
        </Link>
        <p className="nav-label">YOUR WORKSPACE</p>
        <nav aria-label="Main navigation">
          {links.map(({ to, name, icon: Icon, active }) => (
            <Link
              key={to}
              to={to}
              className={`nav-item ${active ? "active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <Icon aria-hidden="true" />
              <span>{name}</span>
              {active && (
                <FiChevronRight className="nav-chevron" aria-hidden="true" />
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-note">
          <FiBookOpen aria-hidden="true" />
          <h2>Start with a small question.</h2>
          <p>Good understanding grows one idea at a time.</p>
          <Link to="/ask">
            Try a sample lesson <FiArrowUpRight aria-hidden="true" />
          </Link>
        </div>
        <div className="sidebar-footer">Made for curious minds.</div>
      </aside>
      <div className="workspace">
        <div className="workspace-bar">
          <span>
            Workspace <FiChevronRight aria-hidden="true" />{" "}
            <strong>{section}</strong>
          </span>
          <span className="workspace-tag">Your study companion</span>
        </div>
        <main
          id="main-content"
          ref={main}
          tabIndex={-1}
          className="workspace-main"
        >
          <Outlet />
        </main>
        <footer className="workspace-footer">
          <span>Buddy’s Brain</span>
          <span>Understand the answer. Explore the source.</span>
        </footer>
      </div>
    </div>
  );
}
