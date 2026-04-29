import { useMemo, useState, useEffect } from "react";
import type { AppData } from "../lib/data";
import { THREAD_COLORS } from "../lib/threads";

interface Props {
  data: AppData;
  initialThread: string | null;
  onSelectKeyword: (kw: string) => void;
}

interface KeywordScore {
  id: string;
  lsHits: number;
  etHits: number;
  lsShare: number;     // share of thread-LS papers that mention this keyword
  etShare: number;
  delta: number;       // etShare - lsShare; positive => ET-leaning under this thread
}

const TOP_N = 15;
const MIN_HITS = 3;

export function CompareView({ data, initialThread, onSelectKeyword }: Props) {
  const tt = data.threadTimeline;
  const [thread, setThread] = useState<string | null>(initialThread ?? tt?.threads[0]?.id ?? null);

  useEffect(() => {
    if (initialThread && initialThread !== thread) setThread(initialThread);
  }, [initialThread]);

  const result = useMemo(() => {
    if (!tt || !data.paperTags || !data.keywordPapers || !thread) return null;

    const fieldByDoi = new Map<string, "ls" | "et">();
    for (const p of data.papers) fieldByDoi.set(p.doi, p.field === "LS" ? "ls" : "et");

    const lsDois = new Set<string>();
    const etDois = new Set<string>();
    for (const [doi, tids] of Object.entries(data.paperTags)) {
      if (!tids.includes(thread)) continue;
      const f = fieldByDoi.get(doi);
      if (f === "ls") lsDois.add(doi);
      else if (f === "et") etDois.add(doi);
    }

    const lsN = Math.max(lsDois.size, 1);
    const etN = Math.max(etDois.size, 1);

    const scored: KeywordScore[] = [];
    for (const [kw, papers] of Object.entries(data.keywordPapers)) {
      let lsHits = 0;
      for (const d of papers.ls) if (lsDois.has(d)) lsHits++;
      let etHits = 0;
      for (const d of papers.et) if (etDois.has(d)) etHits++;
      if (lsHits + etHits < MIN_HITS) continue;
      const lsShare = lsHits / lsN;
      const etShare = etHits / etN;
      scored.push({ id: kw, lsHits, etHits, lsShare, etShare, delta: etShare - lsShare });
    }

    const lsTop = [...scored].sort((a, b) => b.lsShare - a.lsShare).slice(0, TOP_N);
    const etTop = [...scored].sort((a, b) => b.etShare - a.etShare).slice(0, TOP_N);
    const distinctlyLs = [...scored].sort((a, b) => a.delta - b.delta).slice(0, TOP_N);
    const distinctlyEt = [...scored].sort((a, b) => b.delta - a.delta).slice(0, TOP_N);

    return { lsCount: lsDois.size, etCount: etDois.size, lsTop, etTop, distinctlyLs, distinctlyEt };
  }, [tt, data, thread]);

  if (!tt || !data.paperTags || !data.keywordPapers) {
    return (
      <div className="empty">
        Compare needs <code>paper_tags.json</code> + <code>keyword_papers.json</code>. Run <code>dlens export</code>.
      </div>
    );
  }

  return (
    <div className="compare-view">
      <div className="thread-pills">
        {tt.threads.map((t) => (
          <button
            key={t.id}
            className={`legend-chip ${thread === t.id ? "active" : ""}`}
            onClick={() => setThread(t.id)}
          >
            <span className="swatch" style={{ background: THREAD_COLORS[t.id] ?? "#888" }} />
            {t.display_name}
          </button>
        ))}
      </div>

      {result && (
        <>
          <div className="compare-summary muted">
            Thread papers — LS: <strong>{result.lsCount}</strong>, ET: <strong>{result.etCount}</strong>.
            {" "}Share = % of thread-papers in that field that mention the keyword.
          </div>
          <div className="compare-grid">
            <KwColumn
              title={`LS top — most-mentioned in this thread`}
              fieldClass="ls"
              rows={result.lsTop}
              kind="ls"
              onClick={onSelectKeyword}
            />
            <KwColumn
              title={`ET top — most-mentioned in this thread`}
              fieldClass="et"
              rows={result.etTop}
              kind="et"
              onClick={onSelectKeyword}
            />
            <KwColumn
              title="Distinctly LS — biggest LS-over-ET gap"
              fieldClass="ls"
              rows={result.distinctlyLs}
              kind="delta-ls"
              onClick={onSelectKeyword}
            />
            <KwColumn
              title="Distinctly ET — biggest ET-over-LS gap"
              fieldClass="et"
              rows={result.distinctlyEt}
              kind="delta-et"
              onClick={onSelectKeyword}
            />
          </div>
        </>
      )}
    </div>
  );
}

function KwColumn({
  title, fieldClass, rows, kind, onClick,
}: {
  title: string;
  fieldClass: "ls" | "et";
  rows: KeywordScore[];
  kind: "ls" | "et" | "delta-ls" | "delta-et";
  onClick: (kw: string) => void;
}) {
  return (
    <div className={`kw-col ${fieldClass}`}>
      <h3>{title}</h3>
      <ul>
        {rows.map((r) => {
          let primary = 0;
          let detail = "";
          if (kind === "ls") { primary = r.lsShare; detail = `${r.lsHits} papers`; }
          else if (kind === "et") { primary = r.etShare; detail = `${r.etHits} papers`; }
          else if (kind === "delta-ls") { primary = -r.delta; detail = `LS ${(r.lsShare*100).toFixed(0)}% / ET ${(r.etShare*100).toFixed(0)}%`; }
          else { primary = r.delta; detail = `ET ${(r.etShare*100).toFixed(0)}% / LS ${(r.lsShare*100).toFixed(0)}%`; }
          return (
            <li key={r.id} onClick={() => onClick(r.id)} title={`${r.lsHits} LS / ${r.etHits} ET papers`}>
              <span className="kw">{r.id}</span>
              <span className="w">{(primary * 100).toFixed(0)}%</span>
              <span className="detail">{detail}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
