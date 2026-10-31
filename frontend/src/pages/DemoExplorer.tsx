import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowRight as FiArrowRight,
  BookOpen as FiBookOpen,
  Download as FiDownload,
} from "lucide-react";
import { lessons, lessonPassages, type SampleQuestion } from "../demo/lessons";

import Buddy, { Celebration } from "../components/Buddy";
import { useLessonProgress } from "../lib/lessonProgress";
import { usePreferences } from "../components/preferences";
import { Link } from "react-router-dom";

export default function DemoExplorer() {
  const { progress, markViewed } = useLessonProgress();
  const { playCompletion } = usePreferences();
  const [celebrating, setCelebrating] = useState("");
  const [params, setParams] = useSearchParams();
  const lesson =
    lessons.find((item) => item.id === params.get("lesson")) || lessons[0];
  const [selection, setSelection] = useState<{
    lesson: string;
    question: SampleQuestion;
  } | null>(() => {
    const n = Number(params.get("question"));
    return params.has("question") && Number.isInteger(n) && lesson.questions[n]
      ? { lesson: lesson.id, question: lesson.questions[n] }
      : null;
  });
  const selectedQuestion =
    selection?.lesson === lesson.id ? selection.question : null;
  const passages = lessonPassages(lesson);
  function selectLesson(id: string) {
    const next = new URLSearchParams(params);
    next.set("lesson", id);
    next.delete("question");
    setParams(next, { replace: true });
    setSelection(null);
    setCelebrating("");
  }
  const explored = progress.viewed[lesson.id]?.length || 0;
  const nextLesson =
    lessons[lessons.findIndex((item) => item.id === lesson.id) + 1];
  function chooseQuestion(question: SampleQuestion) {
    const index = lesson.questions.indexOf(question);
    setSelection({ lesson: lesson.id, question });
    const next = new URLSearchParams(params);
    next.set("question", String(index));
    setParams(next, { replace: true });
    if (markViewed(lesson.id, index)) {
      setCelebrating(lesson.id);
      playCompletion();
    }
  }
  return (
    <section className="demo-explorer" aria-label="Sample lesson demo">
      <div className="demo-intro">
        <div>
          <span className="badge">
            <span className="status-dot" />
            Demo · saved examples
          </span>
          <h2>Try a lesson. Follow the sources.</h2>
          <p>Choose a question. See the answer and the notes behind it.</p>
        </div>
        <p className="demo-disclosure">
          Sample notes only.
          <br />
          No live AI calls or uploads.
        </p>
      </div>
      <div className="lesson-workspace">
        <aside className="lesson-sidebar">
          <p className="eyebrow">CHOOSE A LESSON</p>
          <div className="lesson-picker" aria-label="Choose a sample lesson">
            {lessons.map((item, index) => (
              <button
                key={item.id}
                aria-pressed={item.id === lesson.id}
                onClick={() => selectLesson(item.id)}
                aria-label={`${item.course} ${item.title}`}
              >
                <span className="lesson-number" aria-hidden="true">
                  0{index + 1}
                </span>
                <span>
                  <small>{item.course}</small>
                  <strong>{item.title}</strong>
                </span>
                <FiArrowRight aria-hidden="true" />
              </button>
            ))}
          </div>
          <p className="lesson-tip">
            <FiBookOpen aria-hidden="true" />
            Read the notes, then explore a question.
          </p>
        </aside>
        <div className="lesson-main">
          <div className="demo-document">
            <div className="lesson-heading">
              <div>
                <p className="eyebrow">{lesson.course} · SAMPLE NOTES</p>
                <h2>{lesson.title}</h2>
              </div>
              <a
                className="icon-link"
                href={lesson.url}
                download={`${lesson.id}.txt`}
                aria-label="Download sample notes"
              >
                <FiDownload aria-hidden="true" />
                <span>Download notes</span>
              </a>
            </div>
            <div className="lesson-progress">
              <span>
                {explored} of {lesson.questions.length} answers explored
              </span>
              <progress
                aria-label="Lesson progress"
                value={explored}
                max={lesson.questions.length}
              />
              <small>Progress stays in this browser.</small>
            </div>
            <details key={lesson.id} className="lesson-details">
              <summary>Read the full sample lesson</summary>
              <div className="lesson-text">
                {passages.map((text, index) => (
                  <p key={index}>
                    <span className="paragraph-number">{index + 1}</span>
                    {text}
                  </p>
                ))}
              </div>
            </details>
            <h3 className="text-sm font-semibold">
              What would you like to understand?
            </h3>
            <div className="suggested-questions">
              {lesson.questions.map((item) => (
                <button
                  key={item.question}
                  aria-pressed={selectedQuestion === item}
                  onClick={() => chooseQuestion(item)}
                >
                  {item.question}
                  <FiArrowRight aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
          <div aria-live="polite" aria-atomic="true">
            {selectedQuestion ? (
              <article className="demo-answer">
                <span className="answer-label">
                  <Buddy />
                  Saved sample answer · not generated live
                </span>
                <h3>{selectedQuestion.question}</h3>
                <p className="answer-prose">{selectedQuestion.answer}</p>
                <div className="evidence-heading">
                  <FiBookOpen aria-hidden="true" />
                  <h4>Where this answer comes from</h4>
                  <span>{selectedQuestion.passages.length} passages</span>
                </div>
                {selectedQuestion.passages.map((number) => (
                  <figure key={number}>
                    <blockquote>{passages[number - 1]}</blockquote>
                    <figcaption>
                      {lesson.title} · paragraph {number}
                    </figcaption>
                  </figure>
                ))}
              </article>
            ) : (
              <div className="answer-placeholder">
                <Buddy mood="curious" />
                <h3>Make an idea click.</h3>
                <p>
                  Choose a question above to see an answer and its supporting
                  passages.
                </p>
              </div>
            )}
          </div>
          {explored === lesson.questions.length && (
            <section className="lesson-complete" aria-label="Lesson complete">
              {celebrating === lesson.id && <Celebration />}
              <Buddy mood="celebrating" />
              <div>
                <h3>You explored every answer!</h3>
                <p>Nice work connecting the ideas to their sources.</p>
                {nextLesson ? (
                  <button
                    className="btn btn-primary"
                    onClick={() => selectLesson(nextLesson.id)}
                  >
                    Next lesson <FiArrowRight aria-hidden="true" />
                  </button>
                ) : (
                  <Link className="btn btn-primary" to="/">
                    Back to home
                  </Link>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
