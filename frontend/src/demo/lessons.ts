import limitsText from "./limits.txt?raw";
import limitsUrl from "./limits.txt?url";
import heapsText from "./heaps.txt?raw";
import heapsUrl from "./heaps.txt?url";
import normalizationText from "./normalization.txt?raw";
import normalizationUrl from "./normalization.txt?url";

// Hand-authored examples, not an AI evaluation dataset or live model output.
export interface SampleQuestion {
  question: string;
  answer: string;
  passages: number[];
}
export interface Lesson {
  id: string;
  course: string;
  title: string;
  text: string;
  url: string;
  questions: SampleQuestion[];
}
export const lessons: Lesson[] = [
  {
    id: "limits",
    course: "CALC101",
    title: "Limits and continuity",
    text: limitsText,
    url: limitsUrl,
    questions: [
      {
        question: "Can a limit exist where a function is undefined?",
        answer:
          "Yes. A limit describes behavior near a point, rather than requiring a value at the point itself. For example, (x² − 4) / (x − 2) has limit 4 as x approaches 2, even though the expression is undefined at 2.",
        passages: [1, 2],
      },
      {
        question: "What makes a function continuous at a point?",
        answer:
          "The function must have a value at the point, a two-sided limit must exist there, and that limit must equal the function’s value. The left-hand and right-hand limits must agree.",
        passages: [3, 4],
      },
    ],
  },
  {
    id: "heaps",
    course: "CS201",
    title: "Binary heaps",
    text: heapsText,
    url: heapsUrl,
    questions: [
      {
        question: "Is a min-heap a fully sorted tree?",
        answer:
          "No. In a min-heap, each parent is no greater than its children, which places the minimum at the root. This does not require siblings or whole subtrees to be sorted.",
        passages: [1, 2],
      },
      {
        question: "How fast are min-heap insertion and minimum lookup?",
        answer:
          "Insertion takes O(log n) time in the worst case because the new element may move up the tree. Looking at the minimum takes O(1), while removing it takes O(log n) because the heap may need to be repaired.",
        passages: [3, 4],
      },
    ],
  },
  {
    id: "normalization",
    course: "DB101",
    title: "Database normalization",
    text: normalizationText,
    url: normalizationUrl,
    questions: [
      {
        question: "Why separate courses from student enrollments?",
        answer:
          "When each course has one instructor, the instructor depends on the course rather than on an individual enrollment. Keeping that fact in a Course table records it once and avoids inconsistent updates across enrollment rows.",
        passages: [2, 3],
      },
      {
        question: "Does normalization make every query faster?",
        answer:
          "No. Normalization reduces redundancy, but reading related information can require additional joins. Denormalization may simplify some reads at the cost of keeping duplicated data consistent, so the choice should follow the workload.",
        passages: [1, 4],
      },
    ],
  },
];

export function lessonPassages(lesson: Lesson) {
  return lesson.text
    .trim()
    .split(/\n\s*\n/)
    .slice(1);
}
