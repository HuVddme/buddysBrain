import { useState } from "react";
import { lessons } from "../demo/lessons";
interface Progress {
  viewed: Record<string, number[]>;
  lastLesson?: string;
  lastQuestion?: number;
}
export function readProgress(): Progress {
  try {
    const raw = JSON.parse(localStorage.getItem("buddy:lessons:v1") || "{}");
    const viewed: Record<string, number[]> = {};
    for (const lesson of lessons)
      viewed[lesson.id] = Array.isArray(raw.viewed?.[lesson.id])
        ? [
            ...new Set<number>(
              raw.viewed[lesson.id].filter(
                (n: unknown) =>
                  Number.isInteger(n) &&
                  Number(n) >= 0 &&
                  Number(n) < lesson.questions.length,
              ),
            ),
          ]
        : [];
    const last = lessons.find((l) => l.id === raw.lastLesson);
    return {
      viewed,
      lastLesson: last?.id,
      lastQuestion:
        last &&
        Number.isInteger(raw.lastQuestion) &&
        raw.lastQuestion >= 0 &&
        raw.lastQuestion < last.questions.length
          ? raw.lastQuestion
          : undefined,
    };
  } catch {
    return { viewed: {} };
  }
}
export function useLessonProgress() {
  const [progress, setProgress] = useState(readProgress);
  function markViewed(lessonId: string, question: number) {
    const viewed = [
      ...new Set([...(progress.viewed[lessonId] || []), question]),
    ];
    const next = {
      viewed: { ...progress.viewed, [lessonId]: viewed },
      lastLesson: lessonId,
      lastQuestion: question,
    };
    setProgress(next);
    try {
      localStorage.setItem("buddy:lessons:v1", JSON.stringify(next));
    } catch {
      /* In-memory progress still works. */
    }
    return (
      viewed.length ===
        lessons.find((l) => l.id === lessonId)!.questions.length &&
      viewed.length > (progress.viewed[lessonId]?.length || 0)
    );
  }
  return { progress, markViewed };
}
