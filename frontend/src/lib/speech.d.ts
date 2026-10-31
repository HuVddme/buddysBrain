interface BuddySpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }>>;
      }) => void)
    | null;
  onstart: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
interface Window {
  SpeechRecognition?: new () => BuddySpeechRecognition;
  webkitSpeechRecognition?: new () => BuddySpeechRecognition;
}
