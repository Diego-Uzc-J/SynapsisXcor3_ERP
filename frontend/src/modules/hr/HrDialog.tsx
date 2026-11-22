import { useEffect, useId } from "react";
import type { ReactNode } from "react";

interface HrDialogProps {
  open: boolean;
  title: string;
  subtitle?: string | undefined;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}

/** Diálogo modal para confirmaciones sensibles, como aprobar una nómina. */
export default function HrDialog({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
}: HrDialogProps) {
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <button
        type="button"
        aria-label="Cerrar diálogo"
        className="backdrop-enter absolute inset-0 cursor-default bg-ink-950/55"
        onClick={onClose}
      />
      <div className="sheet-enter relative flex max-h-[92vh] w-full max-w-lg flex-col bg-concrete-50 shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-concrete-200 bg-white px-5 py-4">
          <div>
            <h2 id={titleId} className="text-lg font-bold tracking-tight">
              {title}
            </h2>
            {subtitle === undefined ? null : (
              <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="-mr-1 grid size-8 place-items-center border border-transparent text-xl leading-none text-ink-500 hover:border-concrete-200 hover:text-ink-950"
          >
            ×
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
        <footer className="flex items-center justify-end gap-3 border-t border-concrete-200 bg-white px-5 py-4">
          {footer}
        </footer>
      </div>
    </div>
  );
}
