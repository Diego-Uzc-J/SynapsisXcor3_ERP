import type { BadgeTone } from "./constants";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-concrete-300 bg-concrete-100 text-ink-700",
  warning: "border-amber-400 bg-amber-50 text-amber-800",
  success: "border-pine-500 bg-pine-50 text-pine-700",
  strong: "border-ink-950 bg-ink-950 text-concrete-50",
  muted: "border-concrete-200 bg-white text-ink-500",
};

/** Insignia de estado reutilizada por contratos, asistencia y nómina. */
export default function StatusBadge({
  label,
  tone,
  hint,
}: {
  label: string;
  tone: BadgeTone;
  hint?: string | undefined;
}) {
  return (
    <span
      title={hint}
      className={[
        "inline-flex whitespace-nowrap border px-2 py-0.5 text-xs font-semibold",
        TONE_CLASSES[tone],
      ].join(" ")}
    >
      {label}
    </span>
  );
}
