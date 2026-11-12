// "Connections to your earlier papers" on Past digests: one digest's papers and the earlier papers
// they share references with (GET /me/graph). Hover a paper to see its links; click it for details.
import { useEffect, useMemo, useState } from "react";
import { api, errorText, type PaperGraph as Graph } from "../api";
import { NEWER_COLOR, OLDER_COLOR, dateColor, formatDay, layout, type PlacedEdge, type PlacedNode } from "../graph";
import { Alert, Loading } from "./ui";

const RING = "#db2777"; // pink-600: this digest's papers
const NO_REFS = { fill: "#e2e8f0", stroke: "#94a3b8" }; // slate-200 / slate-400

export default function PaperGraph({ date }: { date: string }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Graph>("GET", `/me/graph?date=${encodeURIComponent(date)}`)
      .then(setGraph)
      .catch((e) => setError(errorText(e)));
  }, [date]);

  if (error) return <Alert>Couldn't load the connections: {error}</Alert>;
  if (!graph) return <Loading text="Loading connections…" />;
  return <PaperGraphView graph={graph} />;
}

export function PaperGraphView({ graph }: { graph: Graph }) {
  const { nodes, edges, viewBox } = useMemo(() => layout(graph), [graph]);
  const [hover, setHover] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const dates = nodes.map((n) => n.date).sort();
  const [oldest, newest] = [dates[0], dates[dates.length - 1]];
  const focus = hover ?? selected;
  const near = useMemo(() => {
    if (!focus) return null;
    const ids = new Set([focus]);
    for (const e of edges) {
      if (e.source.id === focus) ids.add(e.target.id);
      if (e.target.id === focus) ids.add(e.source.id);
    }
    return ids;
  }, [focus, edges]);
  const shown = nodes.length - graph.papers;
  const picked = nodes.find((n) => n.id === selected);

  return (
    <div className="space-y-3">
      <div>
        <h3 className="font-medium">Connections to your earlier papers</h3>
        <p className="text-sm text-slate-600">
          {graph.linked
            ? `These ${graph.papers} papers share references with ${graph.linked} earlier ${graph.linked === 1 ? "paper" : "papers"} in your history.`
            : "None of these papers share references with earlier papers in your history yet."}
          {graph.with_refs < graph.papers && ` (${graph.with_refs} of ${graph.papers} have reference data so far.)`}
          {graph.more > 0 && ` Showing the ${shown} most strongly linked.`}
        </p>
      </div>

      {edges.length > 0 && (
        <>
          {/* On a phone the graph keeps a readable size and scrolls sideways in its box */}
          <div className="overflow-x-auto rounded-md border border-slate-100 bg-slate-50/50">
            <svg
              viewBox={viewBox}
              className="h-auto max-h-[560px] w-full min-w-[560px] select-none"
              role="group"
              aria-label="Graph of papers linked by shared references"
              onClick={() => setSelected(null)}
            >
              {edges.map((e, i) => {
                const lit = !focus || e.source.id === focus || e.target.id === focus;
                return (
                  <line
                    key={i}
                    x1={e.source.x}
                    y1={e.source.y}
                    x2={e.target.x}
                    y2={e.target.y}
                    stroke={e.direct ? "#334155" : focus && lit ? "#6366f1" : "#94a3b8"}
                    strokeWidth={e.direct ? 2.2 : 0.8 + 0.45 * Math.min(e.shared, 8)}
                    strokeOpacity={lit ? (focus ? 0.9 : 0.55) : 0.08}
                  />
                );
              })}
              {nodes.map((n) => (
                <Node
                  key={n.id}
                  node={n}
                  color={dateColor(n.date, oldest, newest)}
                  dim={near !== null && !near.has(n.id)}
                  selected={n.id === selected}
                  onHover={setHover}
                  onSelect={(id) => setSelected(id === selected ? null : id)}
                />
              ))}
            </svg>
          </div>
          <Legend />
          {picked ? (
            <Details node={picked} edges={edges} onSelect={setSelected} />
          ) : (
            <p className="text-xs text-slate-500">Hover over a paper to see its links; click it for details.</p>
          )}
        </>
      )}
    </div>
  );
}

function Node(props: {
  node: PlacedNode;
  color: string;
  dim: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const { node: n, color, dim, selected, onHover, onSelect } = props;
  const look = !n.has_refs
    ? { fill: NO_REFS.fill, stroke: NO_REFS.stroke, width: 1.5, dash: "3 2" }
    : n.sent
      ? { fill: color, stroke: "#fff", width: 1, dash: undefined }
      : { fill: "#fff", stroke: color, width: 2.5, dash: undefined }; // not sent: hollow
  return (
    <g
      transform={`translate(${n.x},${n.y})`}
      opacity={dim ? 0.2 : 1}
      className="cursor-pointer outline-none"
      role="button"
      tabIndex={0}
      aria-label={`${n.label}: ${n.title}`}
      onMouseEnter={() => onHover(n.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(n.id)}
      onBlur={() => onHover(null)}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(n.id);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(n.id);
        }
      }}
    >
      <title>{n.title}</title>
      {n.this_week && <circle r={n.r + 4} fill="none" stroke={RING} strokeWidth={2.5} />}
      {selected && <circle r={n.r + 8} fill="none" stroke="#0f172a" strokeWidth={1.2} strokeDasharray="2 2" />}
      <circle r={n.r} fill={look.fill} stroke={look.stroke} strokeWidth={look.width} strokeDasharray={look.dash} />
      <text
        y={n.r + 14}
        textAnchor="middle"
        fontSize={12}
        fontWeight={n.this_week ? 600 : 400}
        fill={n.this_week ? "#be185d" : "#334155"}
        stroke="#fff"
        strokeWidth={3}
        paintOrder="stroke"
      >
        {n.label}
      </text>
    </g>
  );
}

function Legend() {
  const dot = (fill: string, stroke: string, extra: Record<string, string | number> = {}) => (
    <svg width="16" height="16" viewBox="-8 -8 16 16" className="inline-block align-[-3px]" aria-hidden>
      <circle r="5.5" fill={fill} stroke={stroke} strokeWidth={2} {...extra} />
    </svg>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
      <span>{dot("#fff", RING)} this digest</span>
      <span>{dot(NEWER_COLOR, NEWER_COLOR)} sent to you</span>
      <span>{dot("#fff", NEWER_COLOR)} not sent, but rated relevant</span>
      <span>{dot(NO_REFS.fill, NO_REFS.stroke, { strokeDasharray: "3 2", strokeWidth: 1.5 })} no reference data yet</span>
      <span className="inline-flex items-center gap-1">
        older
        <span className="inline-block h-2 w-14 rounded" style={{ background: `linear-gradient(to right, ${OLDER_COLOR}, ${NEWER_COLOR})` }} />
        newer
      </span>
      <span>thicker line = more shared references; dark line = one cites the other</span>
    </div>
  );
}

function Details({ node: n, edges, onSelect }: { node: PlacedNode; edges: PlacedEdge[]; onSelect: (id: string) => void }) {
  const links = edges
    .filter((e) => e.source.id === n.id || e.target.id === n.id)
    .map((e) => ({ other: e.source.id === n.id ? e.target : e.source, shared: e.shared, direct: e.direct }))
    .sort((a, b) => Number(b.direct) - Number(a.direct) || b.shared - a.shared);
  const meta = [
    [n.journal, n.year].filter(Boolean).join(", "),
    n.sent ? `sent ${formatDay(n.date, "medium")}` : `not sent (found ${formatDay(n.date, "medium")})`,
    n.relevance != null ? `relevance ${n.relevance}/10` : null,
    n.has_refs ? null : "no reference data yet",
  ];
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <div className="font-medium">
        {n.link ? (
          <a className="text-indigo-700 hover:underline" href={n.link} target="_blank" rel="noreferrer">
            {n.title}
          </a>
        ) : (
          n.title
        )}
      </div>
      <div className="text-xs text-slate-500">{meta.filter(Boolean).join(" · ")}</div>
      {n.summary && !n.this_week && <p className="mt-1 whitespace-pre-line text-slate-700">{n.summary}</p>}
      {links.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slate-600">
          {links.map(({ other, shared, direct }) => (
            <li key={other.id}>
              <button type="button" className="font-medium text-indigo-700 hover:underline" onClick={() => onSelect(other.id)}>
                {other.label}
              </button>{" "}
              {[
                shared ? `${shared} shared reference${shared === 1 ? "" : "s"}` : null,
                direct ? (n.date >= other.date ? "this paper cites it" : "it cites this paper") : null,
              ]
                .filter(Boolean)
                .join(" · ")}
              <span className="text-slate-400"> · {other.title.length > 90 ? other.title.slice(0, 90) + "…" : other.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
