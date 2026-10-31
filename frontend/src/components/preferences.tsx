import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from "react";

const Preferences = createContext({
  dark: false,
  sound: false,
  toggleDark: () => {},
  toggleSound: () => {},
  playCompletion: () => {},
});
function saved(key: string) {
  try {
    return localStorage.getItem(key) === "on";
  } catch {
    return false;
  }
}
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [dark, setDark] = useState(() => saved("buddy:dark"));
  const [sound, setSound] = useState(() => saved("buddy:sound"));
  const audio = useRef<AudioContext | null>(null);
  const soundEnabled = useRef(sound);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("buddy:dark", dark ? "on" : "off");
    } catch {
      /* Browser storage is optional. */
    }
  }, [dark]);
  useEffect(() => {
    soundEnabled.current = sound;
    try {
      localStorage.setItem("buddy:sound", sound ? "on" : "off");
    } catch {
      /* Browser storage is optional. */
    }
  }, [sound]);
  useEffect(
    () => () => {
      void audio.current?.close();
    },
    [],
  );
  const prepareAudio = useCallback(() => {
    if (!window.AudioContext) return null;
    audio.current ||= new AudioContext();
    void audio.current.resume().catch(() => {});
    return audio.current;
  }, []);
  useEffect(() => {
    if (!sound) return;
    const unlock = () => {
      try {
        prepareAudio();
      } catch {
        /* Optional audio. */
      }
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, [sound, prepareAudio]);
  const playCompletion = useCallback(() => {
    if (!soundEnabled.current) return;
    try {
      const ctx = prepareAudio();
      if (!ctx) return;
      [523.25, 659.25].forEach((hz, i) => {
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        const start = ctx.currentTime + i * 0.12;
        oscillator.type = "sine";
        oscillator.frequency.value = hz;
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.035, start + 0.025);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.32);
        oscillator.connect(gain);
        gain.connect(ctx.destination);
        oscillator.start(start);
        oscillator.stop(start + 0.34);
      });
    } catch {
      /* Sound must never interrupt studying. */
    }
  }, [prepareAudio]);
  return (
    <Preferences.Provider
      value={{
        dark,
        sound,
        toggleDark: () => setDark((v) => !v),
        toggleSound: () => {
          if (!sound) {
            try {
              prepareAudio();
            } catch {
              /* Optional audio unavailable. */
            }
          }
          setSound((v) => !v);
        },
        playCompletion,
      }}
    >
      {children}
    </Preferences.Provider>
  );
}
// This hook also works in isolated page tests without enabling audio.
// eslint-disable-next-line react-refresh/only-export-components
export function usePreferences() {
  return useContext(Preferences);
}
