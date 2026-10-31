import { Link } from "react-router-dom";
import {
  FiArrowRight,
  FiArrowUpRight,
  FiBookOpen,
  FiMessageSquare,
  FiPlus,
  FiCheck,
} from "react-icons/fi";
import { apiBaseUrl } from "../lib/liveService";
import { lessons } from "../demo/lessons";

export default function Home() {
  const live = Boolean(apiBaseUrl());
  return (
    <div className="overview-page">
      <section className="home-hero">
        <div className="hero-copy">
          <p className="eyebrow">A SPACE TO MAKE SENSE OF THINGS</p>
          <h1>
            Less searching.
            <br />
            More <em>understanding.</em>
          </h1>
          <p>
            Bring your course material and your curiosity. Buddy helps you
            connect the ideas, with sources you can explore.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              className="btn btn-primary"
              to={live ? "/ask?mode=live" : "/ask"}
            >
              {live ? "Ask Buddy" : "Explore demo"}
              <FiArrowRight aria-hidden="true" />
            </Link>
            <Link className="btn btn-secondary" to={live ? "/submit" : "/ask"}>
              {live ? "Add a resource" : "Try a sample lesson"}
              <FiPlus aria-hidden="true" />
            </Link>
          </div>
        </div>
        <div className="hero-example" aria-label="Saved sample answer preview">
          <div className="example-top">
            <FiBookOpen aria-hidden="true" />
            <span>A MOMENT OF CLARITY</span>
            <span className="example-dot" />
          </div>
          <p className="example-question">Is a min-heap a fully sorted tree?</p>
          <div className="example-answer">
            <span className="mini-avatar">b.</span>
            <div>
              <strong>Not quite.</strong>
              <p>
                The smallest value sits at the root. Each parent is no greater
                than its children, but the rest of the tree doesn’t have to be
                sorted.
              </p>
              <span className="source-chip">
                <FiCheck aria-hidden="true" /> Binary heaps · paragraphs 1–2
              </span>
            </div>
          </div>
          <Link to="/ask?lesson=heaps">
            Explore this saved example <FiArrowUpRight aria-hidden="true" />
          </Link>
        </div>
      </section>
      <section className="getting-started">
        <div className="section-heading">
          <div>
            <p className="eyebrow">FIND YOUR STARTING POINT</p>
            <h2>A clearer way to study.</h2>
          </div>
          <span className="muted text-sm">
            From a question to an explanation.
          </span>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <Link className="action-card" to="/ask">
            <FiBookOpen className="card-icon" aria-hidden="true" />
            <span className="card-number">01</span>
            <h3>Try a sample lesson</h3>
            <p>
              See a saved answer alongside the notes that support it. No setup
              needed.
            </p>
            <span className="card-link">
              Explore demo <FiArrowRight aria-hidden="true" />
            </span>
          </Link>
          {live ? (
            <Link className="action-card" to="/ask?mode=live">
              <FiMessageSquare className="card-icon" aria-hidden="true" />
              <span className="card-number">02</span>
              <h3>Ask your own question</h3>
              <p>
                Search the connected library and get an explanation you can
                follow.
              </p>
              <span className="card-link">
                Ask live <FiArrowRight aria-hidden="true" />
              </span>
            </Link>
          ) : (
            <div className="action-card">
              <FiMessageSquare className="card-icon" aria-hidden="true" />
              <h3>Ask your own question</h3>
              <p>
                Live questions will be available when this workspace is
                connected.
              </p>
              <span className="badge">Coming when connected</span>
            </div>
          )}
          {live ? (
            <Link className="action-card" to="/submit">
              <FiPlus className="card-icon" aria-hidden="true" />
              <span className="card-number">03</span>
              <h3>Build the library</h3>
              <p>
                Add notes, an article, or a video to make more knowledge
                searchable.
              </p>
              <span className="card-link">
                Add a resource <FiArrowRight aria-hidden="true" />
              </span>
            </Link>
          ) : (
            <div className="action-card">
              <FiPlus className="card-icon" aria-hidden="true" />
              <h3>Build the library</h3>
              <p>
                Resource submissions will be available when the live service is
                connected.
              </p>
            </div>
          )}
        </div>
      </section>
      <section className="sample-strip">
        <div>
          <p className="eyebrow">A LITTLE PRACTICE</p>
          <h2>Something to get curious about.</h2>
        </div>
        <div className="sample-links">
          {lessons.map((lesson) => (
            <Link key={lesson.id} to={`/ask?lesson=${lesson.id}`}>
              <span>{lesson.course}</span>
              {lesson.title}
              <FiArrowUpRight aria-hidden="true" />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
