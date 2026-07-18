import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchAnalytics, type AnalyticsSummary } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function AnalyticsPage() {
  const { token } = useAuth();
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void fetchAnalytics(token)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    // Guard against an out-of-order response from a previous token overwriting state.
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) return <p className="text-red-400">{error}</p>;
  if (!data) return <p className="text-zinc-400">Loading analytics…</p>;

  return (
    <div className="space-y-8 animate-fade-in">
      <div>
        <h1 className="font-display text-2xl font-semibold text-zinc-100">Analytics</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Win-rate, response time, and revenue from your tracked pipeline.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Leads", data.total_leads],
          ["Proposals sent", data.proposals_sent],
          ["Win rate", `${(data.win_rate * 100).toFixed(0)}%`],
          [
            "Avg hrs to mark sent",
            data.avg_hours_to_mark_sent != null
              ? data.avg_hours_to_mark_sent.toFixed(1)
              : "—",
          ],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="border border-[#1c3527] bg-[#112419] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40 hover:shadow-lg hover:shadow-[#C5A059]/5"
          >
            <p className="font-display text-xs uppercase tracking-wide text-zinc-400">
              {label}
            </p>
            <p className="mt-2 font-display text-2xl text-[#C5A059]">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="h-72 border border-[#1c3527] bg-[#0d1b12] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
          <h2 className="mb-4 font-display text-sm font-semibold text-[#C5A059]">
            Revenue by month
          </h2>
          <ResponsiveContainer width="100%" height="85%">
            <BarChart data={data.revenue_by_month}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1c3527" />
              <XAxis dataKey="month" stroke="#6b7f70" fontSize={12} />
              <YAxis stroke="#6b7f70" fontSize={12} />
              <Tooltip
                contentStyle={{
                  background: "#0d1b12",
                  border: "1px solid #C5A059",
                  color: "#C5A059",
                }}
                cursor={{ fill: "rgba(28, 53, 39, 0.35)" }}
              />
              <Bar dataKey="revenue" fill="#C5A059" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="h-72 border border-[#1c3527] bg-[#0d1b12] p-4 transition-all duration-500 ease-out hover:border-[#C5A059]/40">
          <h2 className="mb-4 font-display text-sm font-semibold text-[#C5A059]">
            Revenue by category
          </h2>
          <ResponsiveContainer width="100%" height="85%">
            <BarChart data={data.revenue_by_category}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1c3527" />
              <XAxis dataKey="category" stroke="#6b7f70" fontSize={12} />
              <YAxis stroke="#6b7f70" fontSize={12} />
              <Tooltip
                contentStyle={{
                  background: "#0d1b12",
                  border: "1px solid #C5A059",
                  color: "#C5A059",
                }}
                cursor={{ fill: "rgba(28, 53, 39, 0.35)" }}
              />
              <Bar dataKey="revenue" fill="#b08d4a" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <p className="text-sm text-zinc-400">
        Won: {data.won} · Lost: {data.lost}
      </p>
    </div>
  );
}