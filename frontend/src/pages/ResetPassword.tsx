import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { resetPassword } from "../lib/api";
import { Toast, type ToastState } from "../components/Toast";

const inputClass =
  "w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);

  useEffect(() => {
    if (!token) {
      setToast({
        kind: "error",
        message: "Missing or invalid reset token. Request a new link.",
      });
    }
  }, [token]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setToast({ kind: "error", message: "Passwords do not match." });
      return;
    }
    if (password.length < 8) {
      setToast({ kind: "error", message: "Password must be at least 8 characters." });
      return;
    }
    setSubmitting(true);
    try {
      const res = await resetPassword(token, password);
      setToast({ kind: "success", message: `${res.message} Redirecting…` });
      setTimeout(() => navigate("/login", { replace: true }), 1500);
    } catch (err) {
      setToast({
        kind: "error",
        message: err instanceof Error ? err.message : "Reset failed",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 animate-fade-in">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="border border-[#C5A059]/25 bg-[#0d1b12] p-8 shadow-xl shadow-[#050e09] transition-all duration-500 ease-out">
        <header className="mb-10">
          <p className="font-display text-3xl font-semibold tracking-tight text-[#C5A059]">
            The Sterling Syndicate
          </p>
          <p className="mt-2 font-sans text-zinc-400">Choose a new password.</p>
        </header>

        <form onSubmit={onSubmit} className="space-y-4 font-sans">
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">New password</span>
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Confirm password</span>
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={inputClass}
            />
          </label>
          <button
            type="submit"
            disabled={submitting || !token}
            className="w-full rounded-none bg-[#C5A059] px-4 py-2.5 font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:opacity-60"
          >
            {submitting ? "Resetting…" : "Reset password"}
          </button>
        </form>

        <p className="mt-6 font-sans text-sm text-zinc-400">
          <Link
            to="/login"
            className="text-[#C5A059] transition-colors duration-300 hover:text-[#D4AF37] hover:underline"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}