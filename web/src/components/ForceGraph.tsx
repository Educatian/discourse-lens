import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import type { FieldNetwork, GraphLink, GraphNode } from "../lib/data";

interface Props {
  network: FieldNetwork;
  selected: string | null;
  onSelect: (kw: string | null) => void;
  /** Crossfield neighbor lookup; node is "selected" via prop, but we also
   *  want to highlight nodes that the OTHER field has selected via fuzzy link.
   *  The parent passes a Set<string> of LOCAL ids that should glow. */
  highlightedIds: Set<string>;
  fieldColor: string;
  /** Divisor for node freq when computing radius. Pass field paper-total when
   *  regularize is on, 1 otherwise. Visual scale stays comparable across fields
   *  because rScale is recomputed from the per-graph extent. */
  normalizeBy: number;
}

interface SimNode extends GraphNode { x?: number; y?: number; fx?: number | null; fy?: number | null; }
interface SimLink extends GraphLink { source: SimNode | string; target: SimNode | string; }

const NODE_R_MIN = 3;
const NODE_R_MAX = 10;

export function ForceGraph({ network, selected, onSelect, highlightedIds, fieldColor, normalizeBy }: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  // Re-run simulation when nodes/links change. Normalize-by changes don't
  // re-run physics; only update the radius scale (handled in highlight effect).
  const layoutKey = useMemo(
    () => `${network.field}-${network.nodes.length}-${network.links.length}`,
    [network],
  );

  useEffect(() => {
    const svg = d3.select(ref.current!);
    svg.selectAll("*").remove();

    const { width, height } = (ref.current!.parentElement!.getBoundingClientRect());
    if (!network.nodes.length) return;

    const nodes: SimNode[] = network.nodes.map(n => ({ ...n }));
    const links: SimLink[] = network.links.map(l => ({ ...l }));

    const normalized = (f: number) => f / normalizeBy;
    const freqExtent = d3.extent(nodes, d => normalized(d.freq)) as [number, number];
    const rScale = d3.scaleSqrt().domain(freqExtent).range([NODE_R_MIN, NODE_R_MAX]);

    const sim = d3.forceSimulation<SimNode>(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links)
        .id(d => d.id)
        .distance(40)
        .strength(l => Math.max(0.2, Math.min(1, (l as any).weight ?? 0.5))))
      .force("charge", d3.forceManyBody().strength(-50))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide<SimNode>().radius(d => rScale(d.freq / normalizeBy) + 2))
      .alphaDecay(0.05);

    const root = svg.append("g");
    const linkSel = root.append("g").attr("class", "links")
      .selectAll<SVGLineElement, SimLink>("line")
      .data(links)
      .enter().append("line")
      .attr("class", "link")
      .attr("stroke-width", l => 0.4 + ((l as any).weight ?? 0.2) * 1.6);

    const nodeG = root.append("g").attr("class", "nodes")
      .selectAll<SVGGElement, SimNode>("g.node")
      .data(nodes, d => d.id)
      .enter().append("g")
      .attr("class", "node")
      .style("cursor", "pointer")
      .on("click", (_evt, d) => onSelect(d.id))
      .call(d3.drag<SVGGElement, SimNode>()
        .on("start", (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag",  (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end",   (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    nodeG.append("circle")
      .attr("r", d => rScale(d.freq / normalizeBy))
      .attr("fill", fieldColor);

    nodeG.append("title").text(d => `${d.id} (${d.freq})`);

    nodeG.append("text")
      .attr("x", d => rScale(d.freq / normalizeBy) + 3)
      .attr("y", 3)
      .text(d => d.id);

    sim.on("tick", () => {
      linkSel
        .attr("x1", l => (l.source as SimNode).x!)
        .attr("y1", l => (l.source as SimNode).y!)
        .attr("x2", l => (l.target as SimNode).x!)
        .attr("y2", l => (l.target as SimNode).y!);
      nodeG.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    // Settle quickly, then stop physics so highlight changes don't reshuffle layout.
    sim.alpha(1);
    let ticks = 0;
    const maxTicks = 240;
    while (sim.alpha() > 0.02 && ticks < maxTicks) { sim.tick(); ticks++; }
    sim.stop();
    // Final tick render
    linkSel
      .attr("x1", l => (l.source as SimNode).x!)
      .attr("y1", l => (l.source as SimNode).y!)
      .attr("x2", l => (l.target as SimNode).x!)
      .attr("y2", l => (l.target as SimNode).y!);
    nodeG.attr("transform", d => `translate(${d.x},${d.y})`);

    // Pan + zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 4])
      .on("zoom", (event) => root.attr("transform", event.transform.toString()));
    svg.call(zoom);

    return () => { sim.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey, fieldColor, normalizeBy]);

  // Apply highlight state without re-running simulation
  useEffect(() => {
    const svg = d3.select(ref.current!);
    if (!svg.node()) return;
    const neighborSet = new Set<string>();
    if (selected) {
      neighborSet.add(selected);
      for (const l of network.links) {
        const s = typeof l.source === "string" ? l.source : (l.source as GraphNode).id;
        const t = typeof l.target === "string" ? l.target : (l.target as GraphNode).id;
        if (s === selected) neighborSet.add(t);
        if (t === selected) neighborSet.add(s);
      }
    }
    svg.selectAll<SVGGElement, SimNode>("g.node")
      .classed("selected", d => d.id === selected)
      .classed("neighbor", d => !!selected && neighborSet.has(d.id) && d.id !== selected)
      .classed("dim", d => {
        if (!selected) return false;
        return !neighborSet.has(d.id) && !highlightedIds.has(d.id);
      });
    svg.selectAll<SVGLineElement, SimLink>("line.link")
      .classed("selected", l => {
        const s = typeof l.source === "string" ? l.source : (l.source as GraphNode).id;
        const t = typeof l.target === "string" ? l.target : (l.target as GraphNode).id;
        return !!selected && (s === selected || t === selected);
      })
      .classed("dim", l => {
        if (!selected) return false;
        const s = typeof l.source === "string" ? l.source : (l.source as GraphNode).id;
        const t = typeof l.target === "string" ? l.target : (l.target as GraphNode).id;
        return s !== selected && t !== selected;
      });
  }, [selected, highlightedIds, network]);

  return <svg ref={ref} className="force-graph" />;
}
