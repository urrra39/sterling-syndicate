import { useEffect } from "react";

export type ToastKind = "success" | "error" | "info";

export type ToastState = { kind: ToastKind; message: string } | null;

export function Toast({
  toast,
  onDismiss,
  autoHideMs = 4500,
}: {
  toast: ToastState;
  onDismiss: () => void;
  autoHideMs?: number;
}) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDismiss, autoHideMs);
    return () => clearTimeout(t);
  }, [toast, autoHideMs, onDismiss]);

  if (!toast) return null;

  const palette =
    toast.kind === "error"
      ? "border-red-900/60 bg-red-950/80 text-red-100"
      : toast.kind === "success"
        ? "border-[#C5A059]/40 bg-[#0d1b12]/95 text-[#C5A059]"
        : "border-[#1c3527] bg-[#0d1b12]/95 text-zinc-300";

  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed right-4 top-4 z-50 max-w-sm rounded-none border px-4 py-3 text-sm shadow-xl shadow-[#050e09] backdrop-blur transition-all duration-500 ease-out ${palette}`}
    >
      <div className="flex items-start gap-3">
        <span className="flex-1">{toast.message}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="text-current/70 transition-all duration-300 hover:text-current"
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}