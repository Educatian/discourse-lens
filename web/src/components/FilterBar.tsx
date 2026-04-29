import { useMemo, useState, useEffect, useRef } from "react";
import type { AppData } from "../lib/data";

interface Props {
  data: AppData;
  selected: string | null;
  onSelect: (kw: string | null) => void;
  regularize: boolean;
  onRegularize: (v: boolean) => void;
}

export function FilterBar({ data, selected, onSelect, regularize, onRegularize }: Props) {
  const allKeywords = useMemo(() => Object.keys(data.keywordIndex).sort(), [data.keywordIndex]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  const matches = useMemo(() => {
    if (!q.trim()) return [] as string[];
    const lower = q.toLowerCase();
    const startsWith: string[] = [];
    const contains: string[] = [];
    for (const k of allKeywords) {
      if (k.startsWith(lower)) startsWith.push(k);
      else if (k.includes(lower)) contains.push(k);
      if (startsWith.length + contains.length > 30) break;
    }
    return [...startsWith, ...contains].slice(0, 12);
  }, [q, allKeywords]);

  // Close dropdown on outside click
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="filterbar">
      <div className="searchbox" ref={ref}>
        <input
          type="text"
          value={q}
          placeholder="search keyword (e.g. scaffolding)…"
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches[0]) {
              onSelect(matches[0]); setOpen(false); setQ("");
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        {open && matches.length > 0 && (
          <ul className="dropdown">
            {matches.map((m) => {
              const e = data.keywordIndex[m];
              return (
                <li key={m} onClick={() => { onSelect(m); setOpen(false); setQ(""); }}>
                  <span>{m}</span>
                  <span className="counts">
                    <span className="ls">L{e.ls.freq}</span> · <span className="et">E{e.et.freq}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <label className="toggle">
        <input
          type="checkbox"
          checked={regularize}
          onChange={(e) => onRegularize(e.target.checked)}
        />
        <span>regularize <span className="hint">(per 1k papers)</span></span>
      </label>
      {selected && (
        <button className="clear" onClick={() => onSelect(null)}>clear "{selected}"</button>
      )}
    </div>
  );
}
