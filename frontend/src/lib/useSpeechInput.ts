import { useEffect, useRef, useState } from "react";

export function speechFailure(code: string): string {
  const messages: Record<string, string> = {
    "not-allowed":
      "Microphone access was blocked. Allow microphone access for this site in your browser’s site settings, and check that your browser has microphone permission in your device settings. Then try again.",
    "service-not-allowed":
      "This browser cannot use its speech-recognition service. Open this page in a browser with speech recognition enabled, or type your question.",
    "audio-capture":
      "The browser could not access a microphone. Check that a microphone is connected, selected and allowed in your device settings.",
    network:
      "The browser’s speech-recognition service could not be reached. Check your connection. If you’re using an in-app browser, open this page in your regular browser and try again.",
    "no-speech":
      "No speech was detected. Try again and speak after the Listening message appears.",
    "language-not-supported":
      "This browser’s speech service does not support English recognition. You can type your question instead.",
    aborted:
      "Voice input stopped. Your draft is still here; press the microphone to try again.",
    timeout:
      "The browser did not start voice input. Check its microphone permission prompt. If you’re using an in-app browser, open this page in your regular browser.",
  };
  return (
    messages[code] ||
    "Voice input could not start. Check your browser’s microphone settings, or type your question."
  );
}

// A new recognizer per recording prevents late events from an old session
// overwriting a new draft. A transcript is always reviewed before submission.
export function useSpeechInput(setQuestion: (text: string) => void) {
  const supported = Boolean(
    window.SpeechRecognition || window.webkitSpeechRecognition,
  );
  const [phase, setPhase] = useState<
    "idle" | "starting" | "listening" | "stopping"
  >("idle");
  const [error, setError] = useState("");
  const active = useRef<BuddySpeechRecognition | null>(null);
  const stopping = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  function release(recognition: BuddySpeechRecognition) {
    if (active.current !== recognition) return;
    clearTimeout(timer.current);
    active.current = null;
    recognition.onstart =
      recognition.onresult =
      recognition.onerror =
      recognition.onend =
        null;
  }
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      const recognition = active.current;
      if (recognition) {
        release(recognition);
        try {
          recognition.abort();
        } catch {
          /* Already ended. */
        }
      }
    },
    [],
  );

  function toggle(draft: string) {
    if (active.current) {
      if (stopping.current) return;
      stopping.current = true;
      const recognition = active.current;
      setPhase("stopping");
      clearTimeout(timer.current);
      // stop() lets the service deliver its final transcript before onend.
      timer.current = setTimeout(() => {
        release(recognition);
        try {
          recognition.abort();
        } catch {
          /* Already ended. */
        }
        setPhase("idle");
        setError(
          "Voice input stopped before a final transcript arrived. Review the words in your draft before sending.",
        );
      }, 5000);
      try {
        recognition.stop();
      } catch {
        release(recognition);
        try {
          recognition.abort();
        } catch {
          /* Already ended. */
        }
        setPhase("idle");
        setError(speechFailure("aborted"));
      }
      return;
    }
    const Recognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return;
    setError("");
    if (window.isSecureContext === false) {
      setError(
        "Voice input needs a secure connection. Open the HTTPS version of this site.",
      );
      return;
    }
    let recognition: BuddySpeechRecognition;
    try {
      recognition = new Recognition();
    } catch {
      setError(speechFailure("service-not-allowed"));
      return;
    }
    active.current = recognition;
    stopping.current = false;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    let heardSpeech = false;
    const base = draft.trim();
    recognition.onstart = () => {
      if (active.current !== recognition || stopping.current) return;
      clearTimeout(timer.current);
      setPhase("listening");
      timer.current = setTimeout(() => {
        release(recognition);
        try {
          recognition.abort();
        } catch {
          /* Already ended. */
        }
        setPhase("idle");
        setError(
          "Voice input reached its one-minute limit. Review your draft, or press the microphone to continue.",
        );
      }, 60_000);
    };
    recognition.onresult = (event) => {
      if (active.current !== recognition) return;
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript || "")
        .join(" ")
        .trim();
      if (!transcript) return;
      heardSpeech = true;
      const next = [base, transcript].filter(Boolean).join(" ");
      setQuestion(next.slice(0, 2000));
      if (next.length > 2000)
        setError(
          "The question has reached its 2,000-character limit. Review and shorten it before sending.",
        );
    };
    recognition.onerror = (event) => {
      if (active.current !== recognition) return;
      release(recognition);
      try {
        recognition.abort();
      } catch {
        /* Already ended. */
      }
      setPhase("idle");
      setError(speechFailure(event.error));
    };
    recognition.onend = () => {
      if (active.current !== recognition) return;
      release(recognition);
      setPhase("idle");
      if (!heardSpeech) setError(speechFailure("no-speech"));
    };
    setPhase("starting");
    timer.current = setTimeout(() => {
      release(recognition);
      try {
        recognition.abort();
      } catch {
        /* Already ended. */
      }
      setPhase("idle");
      setError(speechFailure("timeout"));
    }, 15_000);
    try {
      window.speechSynthesis?.cancel();
      recognition.start();
    } catch (failure) {
      release(recognition);
      try {
        recognition.abort();
      } catch {
        /* Already ended. */
      }
      setPhase("idle");
      setError(
        speechFailure(
          (failure as { name?: string })?.name === "NotAllowedError"
            ? "not-allowed"
            : "service-not-allowed",
        ),
      );
    }
  }
  return { supported, phase, error, busy: phase !== "idle", toggle };
}
