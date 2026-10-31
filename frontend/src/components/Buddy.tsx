import { CircleHelp, Lightbulb, Sparkles } from "lucide-react";
import mascot from "../assets/BuddysBirthday.png";
export default function Buddy({
  mood = "idle",
  size = "small",
}: {
  mood?: "idle" | "thinking" | "celebrating" | "curious";
  size?: "small" | "hero";
}) {
  const Icon =
    mood === "thinking"
      ? Lightbulb
      : mood === "celebrating"
        ? Sparkles
        : CircleHelp;
  return (
    <span className={`buddy buddy-${mood} buddy-${size}`} aria-hidden="true">
      <img src={mascot} alt="" />
      {mood !== "idle" && (
        <span className="buddy-bubble">
          <Icon />
        </span>
      )}
    </span>
  );
}
export function Celebration() {
  return (
    <span className="celebration" aria-hidden="true">
      {Array.from({ length: 12 }, (_, i) => (
        <i key={i} style={{ "--piece": i } as React.CSSProperties} />
      ))}
    </span>
  );
}
