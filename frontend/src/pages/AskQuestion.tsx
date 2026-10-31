import { useSearchParams } from "react-router-dom";
import DemoExplorer from "./DemoExplorer";
import LiveQuestion from "./LiveQuestion";
import { apiBaseUrl } from "../lib/liveService";
import { PageHeader } from "../components/ui";
import { FiBookOpen, FiMessageSquare } from "react-icons/fi";

export default function AskQuestionPage() {
  const [params, setParams] = useSearchParams();
  const liveAvailable = Boolean(apiBaseUrl());
  const mode = params.get("mode") === "live" && liveAvailable ? "live" : "demo";
  function changeMode(next: string) {
    const updated = new URLSearchParams(params);
    updated.set("mode", next);
    setParams(updated);
  }
  return (
    <section className="study-page">
      <PageHeader
        eyebrow="ASK & UNDERSTAND"
        title="A good question starts here."
      >
        Follow your curiosity. We’ll help you find the context.
      </PageHeader>
      <div className="study-toolbar">
        <div
          className="mode-switch"
          role="group"
          aria-label="Choose how to ask Buddy"
        >
          <button
            aria-pressed={mode === "demo"}
            onClick={() => changeMode("demo")}
          >
            <FiBookOpen aria-hidden="true" />
            Explore demo
          </button>
          <button
            aria-pressed={mode === "live"}
            disabled={!liveAvailable}
            onClick={() => changeMode("live")}
          >
            <FiMessageSquare aria-hidden="true" />
            Ask live
          </button>
        </div>
        <span className="muted text-sm">
          {mode === "demo" ? "A guided first look" : "Connected library"}
        </span>
      </div>
      {!liveAvailable && (
        <p className="notice mb-6">
          Live questions and uploads aren’t connected yet. You can explore the
          demo below.
        </p>
      )}
      {mode === "demo" ? <DemoExplorer /> : <LiveQuestion />}
    </section>
  );
}
