// Layout and colours of the paper graph on Past digests (GET /me/graph, digest/graph.py).
// Kept apart from the component so it can be tested without a browser.
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdge, GraphNode, PaperGraph } from "./api";

export type PlacedNode = GraphNode & SimulationNodeDatum & { x: number; y: number; r: number };
export type PlacedEdge = { source: PlacedNode; target: PlacedNode; shared: number; direct: boolean };
export type Layout = { nodes: PlacedNode[]; edges: PlacedEdge[]; viewBox: string };

type SimEdge = SimulationLinkDatum<PlacedNode> & Omit<GraphEdge, "source" | "target">;

const OLDER = [199, 210, 254]; // indigo-200
const NEWER = [55, 48, 163]; // indigo-800
export const OLDER_COLOR = `rgb(${OLDER.join(", ")})`;
export const NEWER_COLOR = `rgb(${NEWER.join(", ")})`;
const MIN_WIDTH = 520; // so a small graph isn't blown up to fill the page
const MIN_HEIGHT = 300;

/** "2026-11-09" as a local date. (new Date("2026-11-09") is midnight UTC: the day before in the Americas.) */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatDay(iso: string, dateStyle: "long" | "medium" = "long"): string {
  return parseDay(iso).toLocaleDateString(undefined, { dateStyle });
}

/** Circle size: bigger for papers judged more relevant (unscored counts as 5). */
export function radius(n: Pick<GraphNode, "relevance">): number {
  return 7 + Math.max(0, Math.min(n.relevance ?? 5, 10)) * 0.9;
}

/** Light for the oldest date on the graph, dark for the newest. */
export function dateColor(iso: string, oldest: string, newest: string): string {
  const span = parseDay(newest).getTime() - parseDay(oldest).getTime();
  const t = span > 0 ? (parseDay(iso).getTime() - parseDay(oldest).getTime()) / span : 1;
  return `rgb(${OLDER.map((o, i) => Math.round(o + (NEWER[i] - o) * t)).join(", ")})`;
}

/** Where every paper goes: a force layout run to rest (no animation), so the same graph always
 * looks the same. Strong links pull papers close; this digest's papers sit near the middle. */
export function layout(g: PaperGraph): Layout {
  // No x/y yet: d3 starts them on a fixed spiral and fills them in
  const nodes = g.nodes.map((n) => ({ ...n, r: radius(n) })) as PlacedNode[];
  const links: SimEdge[] = g.edges.map((e) => ({ ...e }));
  const strength = (l: SimEdge) => (l.direct ? 8 : Math.min(l.shared, 8));
  forceSimulation<PlacedNode>(nodes)
    .force("link", forceLink<PlacedNode, SimEdge>(links).id((d) => d.id).distance((l) => 120 - 7 * strength(l)))
    .force("charge", forceManyBody().strength(-320))
    .force("collide", forceCollide<PlacedNode>().radius((d) => d.r + 18))
    // Pulled harder up and down than sideways: wider than tall, like the page
    .force("x", forceX<PlacedNode>(0).strength((d) => (d.this_week ? 0.08 : 0.025)))
    .force("y", forceY<PlacedNode>(0).strength((d) => (d.this_week ? 0.16 : 0.09)))
    .stop()
    .tick(300);

  // Bounds, with room for the labels under the circles
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const n of nodes) {
    const half = Math.max(n.r, n.label.length * 3.4);
    x0 = Math.min(x0, n.x - half);
    x1 = Math.max(x1, n.x + half);
    y0 = Math.min(y0, n.y - n.r - 6);
    y1 = Math.max(y1, n.y + n.r + 18);
  }
  const pad = 12;
  let [w, h] = [x1 - x0 + 2 * pad, y1 - y0 + 2 * pad];
  let [left, top] = [x0 - pad, y0 - pad];
  if (w < MIN_WIDTH) [left, w] = [left - (MIN_WIDTH - w) / 2, MIN_WIDTH];
  if (h < MIN_HEIGHT) [top, h] = [top - (MIN_HEIGHT - h) / 2, MIN_HEIGHT];

  return {
    nodes,
    edges: links.map((l) => ({
      source: l.source as PlacedNode,
      target: l.target as PlacedNode,
      shared: l.shared,
      direct: l.direct,
    })),
    viewBox: [left, top, w, h].map((v) => Math.round(v)).join(" "),
  };
}
