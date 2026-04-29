import { useMemo } from "react";
import { ForceGraph } from "../components/ForceGraph";
import { AdjacencyPanel } from "../components/AdjacencyPanel";
import type { AppData } from "../lib/data";

interface Props {
  data: AppData;
  selected: string | null;
  onSelect: (kw: string | null) => void;
  regularize: boolean;
}

export function DualNetworkView({ data, selected, onSelect, regularize }: Props) {
  const { lsHighlight, etHighlight } = useMemo(() => {
    const ls = new Set<string>();
    const et = new Set<string>();
    if (selected) {
      const entry = data.keywordIndex[selected];
      if (entry?.fuzzy_links?.length) {
        for (const f of entry.fuzzy_links) {
          ls.add(f.id);
          et.add(f.id);
        }
      }
    }
    return { lsHighlight: ls, etHighlight: et };
  }, [selected, data.keywordIndex]);

  const lsTotal = data.journals.totals.ls;
  const etTotal = data.journals.totals.et;

  return (
    <>
      <div className="dual-network">
        <section>
          <h2 className="field-ls"><span className="field-tag">LS</span> Learning Sciences <span className="field-n">(n={lsTotal})</span></h2>
          <ForceGraph
            network={data.networkLs}
            selected={selected}
            onSelect={onSelect}
            highlightedIds={lsHighlight}
            fieldColor="var(--ls)"
            normalizeBy={regularize ? lsTotal : 1}
          />
        </section>
        <section>
          <h2 className="field-et"><span className="field-tag">ET</span> Educational Technology <span className="field-n">(n={etTotal})</span></h2>
          <ForceGraph
            network={data.networkEt}
            selected={selected}
            onSelect={onSelect}
            highlightedIds={etHighlight}
            fieldColor="var(--et)"
            normalizeBy={regularize ? etTotal : 1}
          />
        </section>
      </div>
      <AdjacencyPanel
        selected={selected}
        index={data.keywordIndex}
        onPick={onSelect}
        regularize={regularize}
        lsTotal={lsTotal}
        etTotal={etTotal}
      />
    </>
  );
}
