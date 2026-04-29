import type { KeywordIndex } from "../lib/data";

interface Props {
  selected: string | null;
  index: KeywordIndex;
  onPick: (kw: string) => void;
  regularize: boolean;
  lsTotal: number;
  etTotal: number;
}

function fmtCount(n: number, total: number, regularize: boolean): string {
  if (!regularize) return String(n);
  if (total <= 0) return String(n);
  return `${(n / total * 1000).toFixed(1)}/k`;
}

export function AdjacencyPanel({ selected, index, onPick, regularize, lsTotal, etTotal }: Props) {
  if (!selected) {
    return (
      <div className="adjacency">
        <div className="col empty">
          Click a keyword in either network to see how each field surrounds it.
        </div>
      </div>
    );
  }
  const entry = index[selected];
  if (!entry) {
    return (
      <div className="adjacency">
        <div className="col empty">No data for "{selected}".</div>
      </div>
    );
  }
  const lsList = entry.ls.neighbors.slice(0, 12);
  const etList = entry.et.neighbors.slice(0, 12);
  const onlyLs = entry.ls.freq > 0 && entry.et.freq === 0;
  const onlyEt = entry.et.freq > 0 && entry.ls.freq === 0;

  return (
    <div className="adjacency">
      <div className="col ls">
        <h3>LS neighbors {entry.ls.freq ? `(in ${fmtCount(entry.ls.freq, lsTotal, regularize)} papers)` : "(not in LS)"}</h3>
        <ul>
          {lsList.map((n) => (
            <li key={"ls-" + n.id} onClick={() => onPick(n.id)}>
              <span>{n.id}</span><span className="w">{n.weight.toFixed(2)}</span>
            </li>
          ))}
          {lsList.length === 0 && <li><span style={{ color: "var(--muted)" }}>—</span></li>}
        </ul>
      </div>
      <div className="col center">
        <h3>keyword</h3>
        <div className="keyword">{selected}</div>
        <div className="meta">
          {regularize
            ? `LS=${fmtCount(entry.ls.freq, lsTotal, true)} · ET=${fmtCount(entry.et.freq, etTotal, true)} (per 1k)`
            : `LS=${entry.ls.freq} · ET=${entry.et.freq} (raw)`}
        </div>
        {(onlyLs || onlyEt) && entry.fuzzy_links.length > 0 && (
          <div className="meta" style={{ marginTop: "0.75rem" }}>
            <strong>Fuzzy links</strong> ({onlyLs ? "ET candidates" : "LS candidates"}):
            <ul style={{ paddingLeft: "1rem" }}>
              {entry.fuzzy_links.slice(0, 5).map((f) => (
                <li key={"fz-" + f.id} onClick={() => onPick(f.id)}>
                  <span>{f.id}</span><span className="w">{f.score.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="col et">
        <h3>ET neighbors {entry.et.freq ? `(in ${fmtCount(entry.et.freq, etTotal, regularize)} papers)` : "(not in ET)"}</h3>
        <ul>
          {etList.map((n) => (
            <li key={"et-" + n.id} onClick={() => onPick(n.id)}>
              <span>{n.id}</span><span className="w">{n.weight.toFixed(2)}</span>
            </li>
          ))}
          {etList.length === 0 && <li><span style={{ color: "var(--muted)" }}>—</span></li>}
        </ul>
      </div>
    </div>
  );
}
