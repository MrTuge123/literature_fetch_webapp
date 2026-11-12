import { describe, expect, it } from "vitest";
import type { GraphNode, PaperGraph } from "./api";
import { NEWER_COLOR, OLDER_COLOR, dateColor, layout, parseDay, radius } from "./graph";

function node(id: string, extra: Partial<GraphNode> = {}): GraphNode {
  return {
    id, label: id, title: `Paper ${id}`, link: null, journal: null, date: "2026-11-02", sent: true,
    this_week: false, relevance: 7, has_refs: true, summary: null, ...extra,
  };
}

const graph: PaperGraph = {
  date: "2026-11-09", papers: 1, with_refs: 1, linked: 2, more: 0,
  nodes: [node("a", { this_week: true, date: "2026-11-09" }), node("b"), node("c"), node("lonely")],
  edges: [
    { source: "a", target: "b", shared: 6, direct: false },
    { source: "a", target: "c", shared: 2, direct: false },
  ],
};

const dist = (p: { x: number; y: number }, q: { x: number; y: number }) => Math.hypot(p.x - q.x, p.y - q.y);

describe("paper graph", () => {
  it("reads dates as local days, not UTC midnight", () => {
    const d = parseDay("2026-11-09");
    expect([d.getFullYear(), d.getMonth(), d.getDate()]).toEqual([2026, 10, 9]);
  });

  it("colours the oldest date light and the newest dark", () => {
    expect(dateColor("2026-10-05", "2026-10-05", "2026-11-09")).toBe(OLDER_COLOR);
    expect(dateColor("2026-11-09", "2026-10-05", "2026-11-09")).toBe(NEWER_COLOR);
    expect(dateColor("2026-11-09", "2026-11-09", "2026-11-09")).toBe(NEWER_COLOR);
  });

  it("draws more relevant papers bigger", () => {
    expect(radius({ relevance: 9 })).toBeGreaterThan(radius({ relevance: 5 }));
    expect(radius({ relevance: null })).toBe(radius({ relevance: 5 }));
  });

  it("places every paper, strongly linked ones closest, the same way each time", () => {
    const { nodes, edges, viewBox } = layout(graph);
    const at = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(nodes.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
    expect(edges.map((e) => [e.source.id, e.target.id])).toEqual([["a", "b"], ["a", "c"]]);
    expect(dist(at.a, at.b)).toBeLessThan(dist(at.a, at.c));
    expect(dist(at.a, at.c)).toBeLessThan(dist(at.a, at.lonely));
    expect(layout(graph).viewBox).toBe(viewBox);
    const [, , w, h] = viewBox.split(" ").map(Number);
    expect(w).toBeGreaterThanOrEqual(520);
    expect(h).toBeGreaterThanOrEqual(300);
  });
});
