import type { BadgeTone } from "./constants";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-concrete-400 bg-concrete-100 text-ink-700",
  warning: "border-clay-600 bg-clay-100 text-clay-600",
  success: "border-pine-600 bg-pine-100 text-pine-600",
  strong: "border-ink-950 bg-ink-950 text-concrete-50",
  muted: "border-concrete-200 bg-white text-ink-500",
};

/** Insignia reutilizada por estados de OP, BOM y centros de trabajo. */
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
