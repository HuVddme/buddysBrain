import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  BookOpen,
  MessageCircle,
  Upload,
  ChevronRight,
  Moon,
  Sun,
  Volume2,
  VolumeX,
  CircleHelp,
  Home,
} from "lucide-react";
import { apiBaseUrl } from "../lib/liveService";
import Buddy from "./Buddy";
import { PreferencesProvider, usePreferences } from "./preferences";

function Shell() {
  const { pathname, search } = useLocation();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(pathname);
  const { dark, sound, toggleDark, toggleSound } = usePreferences();
  const live = Boolean(apiBaseUrl());
  const mode = new URLSearchParams(search).get("mode");
  const section =
    pathname === "/submit"
      ? "Add a resource"
      : pathname === "/ask"
        ? mode === "live" && live
          ? "Ask live"
          : "Explore demo"
        : "Home";
  useEffect(() => {
    document.title = `${section} · Buddy’s Brain`;
    if (previousPath.current !== pathname) {
      window.scrollTo(0, 0);
      main.current?.focus({ preventScroll: true });
      previousPath.current = pathname;
    }
  }, [pathname, section]);
  const links = [
    {
      to: "/ask",
      name: "Explore demo",
      Icon: BookOpen,
      active: pathname === "/ask" && (mode !== "live" || !live),
    },
    ...(live
      ? [
          {
            to: "/ask?mode=live",
            name: "Ask live",
            Icon: MessageCircle,
            active: pathname === "/ask" && mode === "live",
          },
          {
            to: "/submit",
            name: "Add a resource",
            Icon: Upload,
            active: pathname === "/submit",
          },
        ]
      : []),
  ];
  return (
    <div className={`app-shell ${pathname === "/" ? "is-home" : ""}`}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <Link to="/" className="brand" aria-label="Buddy’s Brain home">
          <Buddy />
          <span>Buddy’s Brain</span>
        </Link>
        {pathname !== "/" && (
          <nav aria-label="Main navigation">
            {links.map(({ to, name, Icon, active }) => (
              <Link
                key={to}
                to={to}
                aria-current={active ? "page" : undefined}
                className={`nav-item ${active ? "active" : ""}`}
              >
                <Icon aria-hidden="true" />
                {name}
              </Link>
            ))}
          </nav>
        )}
        <div className="header-tools">
          <Link
            className="icon-button"
            to="/?tour=1"
            aria-label="Replay quick tour"
            title="Quick tour"
          >
            <CircleHelp />
          </Link>
          <button
            className="icon-button"
            onClick={toggleDark}
            aria-label={dark ? "Use light mode" : "Use dark mode"}
            title={dark ? "Use light mode" : "Use dark mode"}
          >
            {dark ? <Sun /> : <Moon />}
          </button>
          <button
            className="icon-button"
            onClick={toggleSound}
            aria-pressed={sound}
            aria-label={
              sound ? "Turn completion sounds off" : "Turn completion sounds on"
            }
            title={`Completion sounds ${sound ? "on" : "off"}`}
          >
            {sound ? <Volume2 /> : <VolumeX />}
          </button>
        </div>
      </header>
      <main
        id="main-content"
        ref={main}
        tabIndex={-1}
        className={`workspace-main ${pathname === "/ask" && mode === "live" ? "chat-page" : ""}`}
      >
        {pathname !== "/" && (
          <div className="breadcrumb">
            <Link to="/">
              <Home aria-hidden="true" />
              Home
            </Link>
            <ChevronRight aria-hidden="true" />
            <span>{section}</span>
          </div>
        )}
        <div key={pathname} className="page-transition">
          <Outlet />
        </div>
      </main>
      <footer className="workspace-footer">
        <span>Made for curious minds.</span>
        <span>Buddy’s Brain</span>
      </footer>
    </div>
  );
}
export default function AppShell() {
  return (
    <PreferencesProvider>
      <Shell />
    </PreferencesProvider>
  );
}
