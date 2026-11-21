import type { AccountBalanceStatus, JournalEntryStatus } from "./types";
import {
  BALANCE_STATUS_LABELS,
  BALANCE_STATUS_TONES,
  JOURNAL_STATUS_LABELS,
  JOURNAL_STATUS_TONES,
} from "./constants";
import type { BadgeTone } from "./constants";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-concrete-100 text-ink-700",
  warning: "bg-clay-100 text-clay-600",
  success: "bg-pine-100 text-pine-600",
  strong: "bg-ink-950 text-concrete-50",
  muted: "bg-concrete-100 text-concrete-400",
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-concrete-400",
  warning: "bg-clay-600",
  success: "bg-pine-600",
  strong: "bg-signal-500",
  muted: "bg-concrete-400",
};

function Badge({ tone, label }: { tone: BadgeTone; label: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-semibold",
        TONE_CLASSES[tone],
      ].join(" ")}
    >
      <span
        aria-hidden="true"
        className={["size-1.5 shrink-0", DOT_CLASSES[tone]].join(" ")}
      />
      {label}
    </span>
  );
}

export function JournalStatusBadge({ status }: { status: JournalEntryStatus }) {
  return <Badge tone={JOURNAL_STATUS_TONES[status]} label={JOURNAL_STATUS_LABELS[status]} />;
}

export function BalanceStatusBadge({ status }: { status: AccountBalanceStatus }) {
  return <Badge tone={BALANCE_STATUS_TONES[status]} label={BALANCE_STATUS_LABELS[status]} />;
}
