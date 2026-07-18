import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { forgotPassword } from "../lib/api";
import { Toast, type ToastState } from "../components/Toast";

const inputClass =
  "w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await forgotPassword(email.trim());
      setSent(true);
      setToast({ kind: "success", message: res.message });
    } catch (err) {
      setToast({
        kind: "error",
        message: err instanceof Error ? err.message : "Request failed",
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
          <p className="mt-2 font-sans text-zinc-400">
            Reset your access. Enter the email tied to your account.
          </p>
        </header>

        {sent ? (
          <div className="rounded-none border border-[#C5A059]/30 bg-[#050e09] px-4 py-4 text-sm text-zinc-300">
            If an account exists for <span className="text-[#C5A059]">{email}</span>, a
            reset link is on its way. Check your inbox (and spam).
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4 font-sans">
            <label className="block">
              <span className="mb-1 block text-sm text-zinc-300">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
              />
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-none bg-[#C5A059] px-4 py-2.5 font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:opacity-60"
            >
              {submitting ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}

        <p className="mt-6 font-sans text-sm text-zinc-400">
          Remembered it?{" "}
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