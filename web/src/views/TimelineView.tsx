import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import type { ThreadTimeline } from "../lib/data";
import { THREAD_COLORS } from "../lib/threads";

type Mode = "raw" | "share";

interface Props {
  timeline: ThreadTimeline;
}

export function TimelineView({ timeline }: Props) {
  const [mode, setMode] = useState<Mode>("share");
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <div className="timeline-view">
      <div className="timeline-toolbar">
        <span className="muted">
          {timeline.stats?.n_tagged ?? 0} papers tagged via{" "}
          {timeline.model ?? "(model unknown)"}
        </span>
        <div className="toggle-group">
          <button
            className={mode === "share" ? "active" : ""}
            onClick={() => setMode("share")}
            title="Share within field-year (per-1k-papers normalized)"
          >
            share
          </button>
          <button
            className={mode === "raw" ? "active" : ""}
            onClick={() => setMode("raw")}
            title="Raw paper counts"
          >
            raw count
          </button>
        </div>
      </div>

      <div className="timeline-grid">
        <FieldChart
          title="LS — Learning Sciences"
          field="ls"
          timeline={timeline}
          mode={mode}
          hovered={hovered}
          onHover={setHovered}
        />
        <FieldChart
          title="ET — Educational Technology"
          field="et"
          timeline={timeline}
          mode={mode}
          hovered={hovered}
          onHover={setHovered}
        />
      </div>

      <ThreadLegend
        threads={timeline.threads}
        hovered={hovered}
        onHover={setHovered}
      />
    </div>
  );
}

interface FieldChartProps {
  title: string;
  field: "ls" | "et";
  timeline: ThreadTimeline;
  mode: Mode;
  hovered: string | null;
  onHover: (id: string | null) => void;
}

function FieldChart({ title, field, timeline, mode, hovered, onHover }: FieldChartProps) {
  const ref = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(0);
  const [tip, setTip] = useState<{ x: number; y: number; year: number; threadId: string; value: number; total: number; lo?: number; hi?: number } | null>(null);

  // Track the SVG's actual rendered width via ResizeObserver. On first mount
  // inside a flex container the width is briefly 0; without this the chart
  // would draw with the fallback 520px and only fix itself on user interaction.
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setWidth(w);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const displayNameById = useMemo(
    () => Object.fromEntries(timeline.threads.map((t) => [t.id, t.display_name])),
    [timeline.threads]
  );

  const stacked = useMemo(() => {
    const years = timeline.years;
    const totals = timeline.totals_per_year[field];
    const series = timeline.series[field];
    const threadIds = timeline.threads.map((t) => t.id);

    // Per-year per-thread value: raw count, or share = count / total_in_year.
    type Row = { year: number; total: number } & Record<string, number>;
    const rows: Row[] = years.map((year, i) => {
      const total = totals[i] || 0;
      const r: Row = { year, total } as Row;
      for (const tid of threadIds) {
        const c = series[tid]?.[i] ?? 0;
        r[tid] = mode === "share" && total > 0 ? c / total : c;
      }
      return r;
    });

    const stack = d3.stack<Row>().keys(threadIds);
    const layers = stack(rows);
    return { rows, layers, threadIds, years };
  }, [timeline, field, mode]);

  useEffect(() => {
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const node = ref.current;
    if (!node) return;

    const W = width || node.clientWidth || 520;
    const H = 320;
    const margin = { top: 28, right: 16, bottom: 36, left: 48 };
    const innerW = W - margin.left - margin.right;
    const innerH = H - margin.top - margin.bottom;

    const g = svg
      .attr("viewBox", `0 0 ${W} ${H}`)
      .attr("width", "100%")
      .attr("height", H)
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const x = d3
      .scaleLinear()
      .domain(d3.extent(stacked.years) as [number, number])
      .range([0, innerW]);

    const yMax = d3.max(stacked.layers, (l) => d3.max(l, (p) => p[1])) ?? 1;
    const y = d3.scaleLinear().domain([0, yMax || 1]).nice().range([innerH, 0]);

    const area = d3
      .area<d3.SeriesPoint<{ year: number; total: number } & Record<string, number>>>()
      .x((d) => x(d.data.year))
      .y0((d) => y(d[0]))
      .y1((d) => y(d[1]))
      .curve(d3.curveMonotoneX);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickFormat(d3.format("d")).ticks(stacked.years.length));

    g.append("g").call(
      d3.axisLeft(y).ticks(5).tickFormat(mode === "share" ? d3.format(".0%") : d3.format("d"))
    );

    g.append("text")
      .attr("x", 0)
      .attr("y", -10)
      .attr("class", "chart-title")
      .text(title);

    const layers = g
      .selectAll<SVGPathElement, d3.Series<{ year: number; total: number } & Record<string, number>, string>>(".layer")
      .data(stacked.layers)
      .enter()
      .append("path")
      .attr("class", "layer")
      .attr("d", area)
      .attr("fill", (d) => THREAD_COLORS[d.key] ?? "#888")
      .attr("opacity", (d) => (hovered && hovered !== d.key ? 0.18 : 0.85))
      .attr("stroke", (d) => (hovered === d.key ? "#000" : "none"))
      .attr("stroke-width", 1.2);

    layers
      .on("mouseenter", function (_, d) {
        onHover(d.key);
      })
      .on("mouseleave", function () {
        onHover(null);
      });

    // Per-year hover guide: invisible bands that pick the closest year and show
    // every layer's value at that year.
    const rectW = innerW / Math.max(1, stacked.years.length - 1);
    g.selectAll(".year-band")
      .data(stacked.years)
      .enter()
      .append("rect")
      .attr("class", "year-band")
      .attr("x", (yr) => x(yr) - rectW / 2)
      .attr("y", 0)
      .attr("width", rectW)
      .attr("height", innerH)
      .attr("fill", "transparent")
      .on("mousemove", function (event, yr) {
        const i = stacked.years.indexOf(yr);
        const row = stacked.rows[i];
        const tid = hovered ?? stacked.threadIds[0];
        const [mx, my] = d3.pointer(event, node);
        // CI is computed in share-space; only show when in share mode
        const ci = timeline.series_ci?.[field];
        const lo = mode === "share" ? ci?.lo[tid]?.[i] : undefined;
        const hi = mode === "share" ? ci?.hi[tid]?.[i] : undefined;
        setTip({
          x: mx,
          y: my,
          year: yr,
          threadId: tid,
          value: row[tid],
          total: row.total,
          lo, hi,
        });
      })
      .on("mouseleave", () => setTip(null));
  }, [stacked, hovered, mode, onHover, title, width]);

  return (
    <div className="field-chart">
      <svg ref={ref} />
      {tip && (
        <div
          className="timeline-tooltip"
          style={{ left: tip.x + 12, top: tip.y + 12 }}
        >
          <div>
            <strong>{tip.year}</strong>
            <span
              className="tip-swatch"
              style={{ background: THREAD_COLORS[tip.threadId] ?? "#888" }}
            />
            {displayNameById[tip.threadId] ?? tip.threadId}
          </div>
          <div className="muted">
            {mode === "share"
              ? <>
                  {(tip.value * 100).toFixed(1)}% of {tip.total} papers
                  {tip.lo != null && tip.hi != null && (
                    <span className="ci"> · 95% CI [{(tip.lo*100).toFixed(1)}, {(tip.hi*100).toFixed(1)}]</span>
                  )}
                </>
              : `${Math.round(tip.value)} / ${tip.total} papers`}
          </div>
        </div>
      )}
    </div>
  );
}

interface LegendProps {
  threads: ThreadTimeline["threads"];
  hovered: string | null;
  onHover: (id: string | null) => void;
}

function ThreadLegend({ threads, hovered, onHover }: LegendProps) {
  return (
    <div className="thread-legend">
      {threads.map((t) => (
        <button
          key={t.id}
          className={`legend-chip ${hovered === t.id ? "active" : ""}`}
          onMouseEnter={() => onHover(t.id)}
          onMouseLeave={() => onHover(null)}
          title={t.definition}
        >
          <span
            className="swatch"
            style={{ background: THREAD_COLORS[t.id] ?? "#888" }}
          />
          {t.display_name}
        </button>
      ))}
    </div>
  );
}
