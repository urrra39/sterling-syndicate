import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  PIPELINE_COLUMNS,
  ingestSource,
  listLeads,
  pasteLead,
  updateLeadStatus,
  type Lead,
  type PipelineStatus,
} from "../lib/api";
import { useAuth } from "../lib/auth";

const inputClass =
  "w-full rounded-none border border-[#1c3527] bg-[#050e09] px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 outline-none transition-all duration-300 focus:border-[#C5A059] focus:ring-1 focus:ring-[#C5A059]/40";

export default function BoardPage() {
  const { token } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [minScore, setMinScore] = useState(0);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const data = await listLeads(token, minScore > 0 ? minScore : undefined);
      setLeads(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leads");
    }
  }, [token, minScore]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const byStatus = useMemo(() => {
    const map: Record<string, Lead[]> = {};
    for (const col of PIPELINE_COLUMNS) map[col.id] = [];
    for (const lead of leads) {
      const bucket = map[lead.pipeline_status];
      if (!bucket) {
        // Unknown status (backend schema drift). Drop it loudly instead of
        // silently misfiling into the New column, which hid the mismatch.
        console.warn(
          `Lead ${lead.id} has unknown pipeline_status "${lead.pipeline_status}"; skipping`,
        );
        continue;
      }
      bucket.push(lead);
    }
    return map;
  }, [leads]);

  async function onDrop(status: PipelineStatus, leadId: string) {
    if (!token) return;
    const lead = leads.find((l) => l.id === leadId);
    if (!lead || lead.pipeline_status === status) return;
    setLeads((prev) =>
      prev.map((l) => (l.id === leadId ? { ...l, pipeline_status: status } : l)),
    );
    try {
      await updateLeadStatus(token, leadId, status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Status update failed");
      void refresh();
    }
  }

  async function onPaste(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    try {
      await pasteLead(token, {
        title: pasteTitle,
        raw_text: pasteText,
      });
      setPasteText("");
      setPasteTitle("");
      setPasteOpen(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Paste failed");
    } finally {
      setBusy(false);
    }
  }

  async function onIngest(source: "remoteok" | "weworkremotely") {
    if (!token) return;
    setBusy(true);
    try {
      await ingestSource(token, { source, limit: 10 });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold text-zinc-100">Pipeline</h1>
          <p className="mt-1 max-w-xl text-sm text-zinc-400">
            AI drafts stay drafts. You copy, send, then mark sent — never auto-posted.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => setPasteOpen((v) => !v)}
            className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:opacity-50"
          >
            Paste job
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onIngest("remoteok")}
            className="rounded-none border border-[#1c3527] px-3 py-2 text-sm text-zinc-300 transition-all duration-500 ease-out hover:border-[#C5A059]/60 hover:text-[#C5A059]"
          >
            Fetch RemoteOK
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void onIngest("weworkremotely")}
            className="rounded-none border border-[#1c3527] px-3 py-2 text-sm text-zinc-300 transition-all duration-500 ease-out hover:border-[#C5A059]/60 hover:text-[#C5A059]"
          >
            Fetch WWR RSS
          </button>
        </div>
      </div>

      <label className="flex items-center gap-3 text-sm text-zinc-400">
        Min match score
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={minScore}
          onChange={(e) => setMinScore(Number(e.target.value))}
          className="w-40 accent-[#C5A059]"
        />
        <span className="tabular-nums text-zinc-300">{minScore.toFixed(2)}</span>
      </label>

      {pasteOpen && (
        <form
          onSubmit={onPaste}
          className="space-y-3 border border-[#C5A059]/20 bg-[#0d1b12] p-4 transition-all duration-500 ease-out"
        >
          <input
            placeholder="Title (optional)"
            value={pasteTitle}
            onChange={(e) => setPasteTitle(e.target.value)}
            className={inputClass}
          />
          <textarea
            required
            minLength={20}
            rows={6}
            placeholder="Paste the full job post here (including Upwork/Fiverr text you copied yourself)…"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            className={inputClass}
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-none bg-[#C5A059] px-3 py-2 text-sm font-semibold tracking-wide text-[#050e09] transition-all duration-500 hover:bg-[#b08d4a] disabled:opacity-50"
          >
            Score &amp; add lead
          </button>
        </form>
      )}

      {error && (
        <p className="rounded-none border border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-200">
          {error}
        </p>
      )}

      <div className="flex gap-3 overflow-x-auto pb-4">
        {PIPELINE_COLUMNS.map((col) => (
          <div
            key={col.id}
            className={
              col.id === "pending_payment_verification"
                ? "flex w-64 shrink-0 flex-col border-2 border-[#D4AF37]/80 bg-[#112419] transition-all duration-500 ease-out"
                : col.id === "paused_for_budget_extension" ||
                    col.id === "paused_for_captcha"
                  ? "flex w-64 shrink-0 flex-col border-2 border-red-900/80 bg-[#112419] transition-all duration-500 ease-out"
                  : col.id === "rejected_by_sast"
                    ? "flex w-64 shrink-0 flex-col border-2 border-[#b08d4a]/60 bg-[#112419] transition-all duration-500 ease-out"
                    : "flex w-64 shrink-0 flex-col border border-[#1c3527] bg-[#0d1b12] transition-all duration-500 ease-out"
            }
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const id = e.dataTransfer.getData("text/lead-id");
              if (id) void onDrop(col.id, id);
            }}
          >
            <div
              className={
                col.id === "pending_payment_verification"
                  ? "border-b border-[#C5A059]/50 px-3 py-2 font-display text-xs font-bold uppercase tracking-wide text-[#D4AF37]"
                  : col.id === "paused_for_budget_extension" ||
                      col.id === "paused_for_captcha"
                    ? "border-b border-red-900/50 px-3 py-2 font-display text-xs font-bold uppercase tracking-wide text-red-300"
                    : col.id === "rejected_by_sast"
                      ? "border-b border-[#b08d4a]/50 px-3 py-2 font-display text-xs font-bold uppercase tracking-wide text-[#b08d4a]"
                      : "border-b border-[#1c3527] px-3 py-2 font-display text-xs font-semibold uppercase tracking-wide text-zinc-400"
              }
            >
              {col.id === "pending_payment_verification"
                ? "🚨 "
                : col.id === "paused_for_budget_extension"
                  ? "⚠️ "
                  : col.id === "paused_for_captcha"
                    ? "🛑 "
                    : col.id === "rejected_by_sast"
                      ? "🔒 "
                      : ""}
              {col.label}{" "}
              <span className="text-zinc-500">({byStatus[col.id]?.length ?? 0})</span>
            </div>
            <div className="flex min-h-[200px] flex-col gap-2 p-2">
              {(byStatus[col.id] ?? []).map((lead) => (
                <Link
                  key={lead.id}
                  to={`/leads/${lead.id}`}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/lead-id", lead.id);
                  }}
                  className={
                    col.id === "pending_payment_verification"
                      ? "block border border-[#C5A059]/70 bg-[#112419] p-3 text-left ring-1 ring-[#C5A059]/40 transition-all duration-500 ease-out hover:border-[#D4AF37] hover:shadow-lg hover:shadow-[#C5A059]/10"
                      : col.id === "rejected_tos_violation" ||
                          col.id === "rejected_by_sast"
                        ? "block border border-[#1c3527] bg-[#112419] p-3 text-left opacity-70 transition-all duration-500 ease-out"
                        : "block border border-[#1c3527] bg-[#112419] p-3 text-left transition-all duration-500 ease-out hover:border-[#C5A059]/40 hover:shadow-lg hover:shadow-[#C5A059]/5"
                  }
                >
                  <p className="line-clamp-2 text-sm font-medium text-zinc-100">
                    {lead.title || "Untitled"}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {lead.source}
                    {lead.match_score != null && (
                      <> · match {(lead.match_score * 100).toFixed(0)}%</>
                    )}
                  </p>
                  {lead.match_score != null && lead.match_score >= 0.75 && (
                    <span className="mt-2 inline-block border border-[#C5A059]/30 bg-[#C5A059]/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#C5A059]">
                      High match
                    </span>
                  )}
                  {col.id === "pending_payment_verification" && (
                    <p className="mt-2 text-[10px] font-bold uppercase tracking-wide text-[#D4AF37]">
                      Action required · verify funds
                    </p>
                  )}
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}