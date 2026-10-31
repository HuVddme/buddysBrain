import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useSpeechInput } from "./useSpeechInput";

let instances: FakeRecognition[];
class FakeRecognition implements BuddySpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = "";
  onstart: BuddySpeechRecognition["onstart"] = null;
  onresult: BuddySpeechRecognition["onresult"] = null;
  onerror: BuddySpeechRecognition["onerror"] = null;
  onend: BuddySpeechRecognition["onend"] = null;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();
  constructor() {
    instances.push(this);
  }
}
beforeEach(() => {
  instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("SpeechRecognition", undefined);
  vi.stubGlobal("webkitSpeechRecognition", FakeRecognition);
  vi.stubGlobal("isSecureContext", true);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function setup(draft = "") {
  const change = vi.fn();
  const hook = renderHook(() => useSpeechInput(change));
  act(() => hook.result.current.toggle(draft));
  return { ...hook, change, recognition: instances[0] };
}
test("listening begins only after browser start, final transcript preserves typed draft and is editable after stop", () => {
  const { result, change, recognition } = setup("Explain");
  expect(result.current.phase).toBe("starting");
  act(() => recognition.onstart?.());
  expect(result.current.phase).toBe("listening");
  act(() => recognition.onresult?.({ results: [[{ transcript: "he" }]] }));
  act(() => recognition.onresult?.({ results: [[{ transcript: "heaps" }]] }));
  expect(change).toHaveBeenLastCalledWith("Explain heaps");
  act(() => result.current.toggle("Explain heaps"));
  expect(recognition.stop).toHaveBeenCalledOnce();
  expect(result.current.phase).toBe("stopping");
  act(() =>
    recognition.onresult?.({ results: [[{ transcript: "binary heaps" }]] }),
  );
  act(() => recognition.onend?.());
  expect(result.current.busy).toBe(false);
  expect(change).toHaveBeenLastCalledWith("Explain binary heaps");
  expect(result.current.error).toBe("");
});

test.each([
  ["not-allowed", "Microphone access was blocked"],
  ["audio-capture", "could not access a microphone"],
  ["network", "service could not be reached"],
  ["service-not-allowed", "cannot use its speech-recognition service"],
  ["no-speech", "No speech was detected"],
])(
  "reports actionable %s errors and releases the session",
  (error, message) => {
    const { result, change, recognition } = setup("Existing draft");
    act(() => recognition.onerror?.({ error }));
    expect(result.current.error).toContain(message);
    expect(result.current.busy).toBe(false);
    expect(change).not.toHaveBeenCalled();
    expect(recognition.abort).toHaveBeenCalledOnce();
    act(() => result.current.toggle("Existing draft"));
    expect(instances).toHaveLength(2);
  },
);

test("late events from a previous session cannot overwrite the next draft", () => {
  const { result, change, recognition } = setup();
  const late = recognition.onresult;
  act(() => recognition.onerror?.({ error: "network" }));
  act(() => result.current.toggle("New draft"));
  act(() => late?.({ results: [[{ transcript: "stale words" }]] }));
  expect(change).not.toHaveBeenCalled();
});

test("permission wait times out and unmount clears microphone and timers", () => {
  const { result, recognition, unmount } = setup();
  act(() => vi.advanceTimersByTime(15000));
  expect(result.current.error).toContain("did not start");
  expect(recognition.abort).toHaveBeenCalledOnce();
  act(() => result.current.toggle(""));
  unmount();
  expect(instances[1].abort).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});

test("no-speech end and a stuck stop both release the input", () => {
  const { result, recognition } = setup();
  act(() => recognition.onend?.());
  expect(result.current.error).toContain("No speech");
  act(() => result.current.toggle(""));
  act(() => instances[1].onstart?.());
  act(() => result.current.toggle(""));
  act(() => vi.advanceTimersByTime(5000));
  expect(result.current.busy).toBe(false);
  expect(result.current.error).toContain("final transcript");
});

test("dictation obeys the backend question length limit", () => {
  const { change, recognition, result } = setup("Draft");
  act(() =>
    recognition.onresult?.({ results: [[{ transcript: "a".repeat(2100) }]] }),
  );
  expect(change.mock.calls[0][0]).toHaveLength(2000);
  expect(result.current.error).toContain("2,000");
});

test("unsupported browsers do not construct a recognizer", () => {
  vi.stubGlobal("webkitSpeechRecognition", undefined);
  const { result } = renderHook(() => useSpeechInput(vi.fn()));
  expect(result.current.supported).toBe(false);
  act(() => result.current.toggle("draft"));
  expect(instances).toHaveLength(0);
});
