import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  MessageCircle,
  Upload,
  X,
  RotateCcw,
} from "lucide-react";
import Buddy from "../components/Buddy";
import { apiBaseUrl } from "../lib/liveService";
import { readProgress } from "../lib/lessonProgress";
import { lessons } from "../demo/lessons";

const greeting = "What can Buddy do for you today?";
const tourCopy = [
  "Meet Buddy with a sample lesson. Choose a question and explore the notes behind its saved answer.",
  "Ready for your own question? Ask live searches the shared library and shows sources alongside the answer.",
  "Add a resource to help the library grow. Documents show their processing progress after you submit.",
];
function seenTour() {
  try {
    return localStorage.getItem("buddy:tour:v1") === "seen";
  } catch {
    return false;
  }
}
export default function Home() {
  const [typed, setTyped] = useState(() =>
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
      ? greeting
      : "",
  );
  const [params, setParams] = useSearchParams();
  const [dismissed, setDismissed] = useState(seenTour);
  const [step, setStep] = useState(0);
  const [progress] = useState(readProgress);
  const live = Boolean(apiBaseUrl());
  const lastLesson = lessons.find((l) => l.id === progress.lastLesson);
  const showTour = !dismissed || params.get("tour") === "1";
  useEffect(() => {
    const media = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (media?.matches) return;
    let index = 0;
    const timer = setInterval(() => {
      index++;
      setTyped(greeting.slice(0, index));
      if (index >= greeting.length) clearInterval(timer);
    }, 75);
    const reduce = () => {
      if (media?.matches) {
        clearInterval(timer);
        setTyped(greeting);
      }
    };
    media?.addEventListener("change", reduce);
    return () => {
      clearInterval(timer);
      media?.removeEventListener("change", reduce);
    };
  }, []);
  function finishTour() {
    setDismissed(true);
    setStep(0);
    try {
      localStorage.setItem("buddy:tour:v1", "seen");
    } catch {
      /* Optional preference. */
    }
    const next = new URLSearchParams(params);
    next.delete("tour");
    setParams(next, { replace: true });
  }
  const actions = [
    {
      name: "Explore demo",
      to: "/ask",
      description: "Sample lessons. Saved answers. No setup.",
      Icon: BookOpen,
    },
    {
      name: "Ask live",
      to: "/ask?mode=live",
      description: "Your questions, answered with library sources.",
      Icon: MessageCircle,
    },
    {
      name: "Add a resource",
      to: "/submit",
      description: "Share notes, an article, or a video.",
      Icon: Upload,
    },
  ];
  return (
    <section className="home-page">
      <div className="home-card">
        <Buddy size="hero" />
        <h1>Welcome to Buddy’s Brain</h1>
        <h2 className="typewriter-text">
          <span className="sr-only">{greeting}</span>
          <span aria-hidden="true">
            {typed}
            <span className="typing-cursor">|</span>
          </span>
        </h2>
        <div className="home-actions">
          {actions.map(({ name, to, description, Icon }, index) => (
            <div
              key={to}
              className={`home-action ${showTour && step === index ? "tour-highlight" : ""}`}
            >
              {index === 0 || live ? (
                <Link
                  className={`btn ${index === (live ? 1 : 0) ? "btn-primary" : "btn-secondary"}`}
                  to={to}
                >
                  <Icon aria-hidden="true" />
                  {name}
                  <ArrowRight aria-hidden="true" />
                </Link>
              ) : (
                <button className="btn btn-secondary" disabled>
                  <Icon aria-hidden="true" />
                  {name}
                </button>
              )}
              <p>
                {index > 0 && !live
                  ? "Available when the live service is connected."
                  : description}
              </p>
            </div>
          ))}
        </div>
        <p className="home-note">
          A little curiosity. A clearer understanding.
        </p>
        {lastLesson && (
          <Link
            className="continue-card"
            to={`/ask?lesson=${lastLesson.id}&question=${progress.lastQuestion ?? 0}`}
          >
            <RotateCcw aria-hidden="true" />
            <span>
              <strong>Continue where you left off</strong>
              <small>
                {lastLesson.title} ·{" "}
                {progress.viewed[lastLesson.id]?.length || 0} of{" "}
                {lastLesson.questions.length} answers explored
              </small>
            </span>
            <ArrowRight aria-hidden="true" />
          </Link>
        )}
        {showTour && (
          <aside
            className="buddy-tour"
            role="dialog"
            aria-label="Meet Buddy: quick tour"
          >
            <Buddy mood="curious" />
            <div aria-live="polite">
              <p className="eyebrow">A QUICK HELLO · {step + 1} OF 3</p>
              <h3>{actions[step].name}</h3>
              <p>{tourCopy[step]}</p>
              <div className="tour-controls">
                <button className="text-button" onClick={finishTour}>
                  Skip tour
                </button>
                {step > 0 && (
                  <button
                    className="text-button"
                    onClick={() => setStep((s) => s - 1)}
                  >
                    Back
                  </button>
                )}
                <button
                  className="btn btn-primary"
                  onClick={() =>
                    step === 2 ? finishTour() : setStep((s) => s + 1)
                  }
                >
                  {step === 2 ? "Got it" : "Next"}
                  <ArrowRight aria-hidden="true" />
                </button>
              </div>
            </div>
            <button
              className="icon-button tour-close"
              aria-label="Close tour"
              onClick={finishTour}
            >
              <X />
            </button>
          </aside>
        )}
      </div>
    </section>
  );
}
