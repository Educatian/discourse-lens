import { useMemo } from "react";
import type { AppData } from "../lib/data";
import { THREAD_COLORS } from "../lib/threads";

interface Props {
  data: AppData;
  onPickThread: (id: string) => void;
}

interface Summary {
  id: string;
  display_name: string;
  definition?: string;
  lsCount: number;
  etCount: number;
  lsShare: number;
  etShare: number;
  bias: number;          // etShare - lsShare; positive => ET-leaning
  biasLo?: number;
  biasHi?: number;
  pPerm?: number;
  trend: number;         // last-3-yrs share - first-3-yrs share (across both fields)
}

export function DiscourseView({ data, onPickThread }: Props) {
  const tt = data.threadTimeline;
  const summaries = useMemo<Summary[]>(() => {
    if (!tt) return [];
    const lsTotal = tt.totals_per_year.ls.reduce((a, b) => a + b, 0) || 1;
    const etTotal = tt.totals_per_year.et.reduce((a, b) => a + b, 0) || 1;
    return tt.threads.map((t) => {
      const lsByYr = tt.series.ls[t.id] ?? [];
      const etByYr = tt.series.et[t.id] ?? [];
      const lsCount = lsByYr.reduce((a, b) => a + b, 0);
      const etCount = etByYr.reduce((a, b) => a + b, 0);
      const lsShare = lsCount / lsTotal;
      const etShare = etCount / etTotal;

      // Trend: combined share in last 3 vs first 3 years
      const n = tt.years.length;
      const headIdx = [0, 1, 2];
      const tailIdx = [n - 3, n - 2, n - 1];
      const headTotal =
        headIdx.reduce((a, i) => a + (tt.totals_per_year.ls[i] || 0) + (tt.totals_per_year.et[i] || 0), 0) || 1;
      const tailTotal =
        tailIdx.reduce((a, i) => a + (tt.totals_per_year.ls[i] || 0) + (tt.totals_per_year.et[i] || 0), 0) || 1;
      const headCount = headIdx.reduce((a, i) => a + (lsByYr[i] || 0) + (etByYr[i] || 0), 0);
      const tailCount = tailIdx.reduce((a, i) => a + (lsByYr[i] || 0) + (etByYr[i] || 0), 0);
      const trend = tailCount / tailTotal - headCount / headTotal;

      const biasInf = tt.bias?.[t.id];
      return {
        id: t.id,
        display_name: t.display_name,
        definition: t.definition,
        lsCount, etCount, lsShare, etShare,
        bias: biasInf?.delta ?? (etShare - lsShare),
        biasLo: biasInf?.delta_lo,
        biasHi: biasInf?.delta_hi,
        pPerm: biasInf?.p_perm,
        trend,
      };
    }).sort((a, b) => (b.lsCount + b.etCount) - (a.lsCount + a.etCount));
  }, [tt]);

  if (!tt) {
    return (
      <div className="empty">
        Discourse threads waiting for <code>dlens tag</code> + <code>dlens export</code>. Refresh after.
      </div>
    );
  }

  const maxShare = Math.max(...summaries.flatMap((s) => [s.lsShare, s.etShare]), 0.001);

  return (
    <div className="discourse-view">
      <div className="discourse-meta">
        <span className="muted">
          {tt.stats?.n_tagged ?? 0} of {tt.stats?.n_records ?? 0} papers carry at least one thread
          {" · "}sorted by total volume{" · "}share = papers tagged within field
        </span>
      </div>
      <div className="discourse-grid">
        {summaries.map((s) => (
          <ThreadCard key={s.id} s={s} maxShare={maxShare} onPick={() => onPickThread(s.id)} />
        ))}
      </div>
    </div>
  );
}

function ThreadCard({ s, maxShare, onPick }: { s: Summary; maxShare: number; onPick: () => void }) {
  const sig = (p?: number) =>
    p == null ? "" : p < 0.001 ? "***" : p < 0.01 ? "**" : p < 0.05 ? "*" : "ns";
  const ciStr =
    s.biasLo != null && s.biasHi != null
      ? `[${(s.biasLo * 100).toFixed(1)}, ${(s.biasHi * 100).toFixed(1)}]`
      : "";
  const pLabel = s.pPerm != null
    ? (s.pPerm < 0.001 ? "p<.001" : `p=${s.pPerm.toFixed(3)}`)
    : "";
  // CI crosses zero -> not statistically distinguishable; mark as "evenly engaged"
  const ciStraddlesZero = s.biasLo != null && s.biasHi != null && s.biasLo <= 0 && s.biasHi >= 0;
  const biasLabel =
    ciStraddlesZero
      ? "evenly engaged"
      : s.bias > 0
        ? `ET-leaning +${(s.bias * 100).toFixed(1)}pp`
        : `LS-leaning +${(-s.bias * 100).toFixed(1)}pp`;
  const trendLabel = s.trend > 0.02 ? "↑ rising" : s.trend < -0.02 ? "↓ fading" : "→ steady";
  return (
    <div className="thread-card" onClick={onPick} role="button">
      <div className="thread-card-header">
        <span className="swatch big" style={{ background: THREAD_COLORS[s.id] ?? "#888" }} />
        <h3>{s.display_name}</h3>
      </div>
      {s.definition && <p className="thread-def">{s.definition}</p>}
      <div className="thread-stats">
        <StatRow label="LS" color="var(--ls)" count={s.lsCount} share={s.lsShare} max={maxShare} />
        <StatRow label="ET" color="var(--et)" count={s.etCount} share={s.etShare} max={maxShare} />
      </div>
      <div className="thread-meta">
        <span className={`bias ${ciStraddlesZero ? "neutral" : s.bias > 0 ? "et" : "ls"}`} title={`95% CI in pp: ${ciStr || "(no CI)"}; permutation test ${pLabel || "n/a"} ${sig(s.pPerm)}`}>{biasLabel}</span>
        <span className={`trend ${s.trend > 0 ? "up" : s.trend < 0 ? "down" : "flat"}`}>{trendLabel}</span>
      </div>
      {ciStr && (
        <div className="thread-ci muted">
          95% CI: {ciStr}pp · {pLabel} <span className={`sig sig-${sig(s.pPerm)}`}>{sig(s.pPerm)}</span>
        </div>
      )}
    </div>
  );
}

function StatRow({ label, color, count, share, max }: { label: string; color: string; count: number; share: number; max: number }) {
  return (
    <div className="stat-row">
      <span className="field-label" style={{ color }}>{label}</span>
      <span className="count">{count}</span>
      <div className="bar"><div className="bar-fill" style={{ width: `${(share / max) * 100}%`, background: color }} /></div>
      <span className="share">{(share * 100).toFixed(1)}%</span>
    </div>
  );
}
