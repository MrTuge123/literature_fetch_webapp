import { useEffect, useState } from "react";
import { api, errorText, type Digest } from "../api";
import PaperGraph from "../components/PaperGraph";
import { Alert, Loading } from "../components/ui";
import { formatDay } from "../graph";

export default function Digests() {
  const [digests, setDigests] = useState<Digest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Digests opened so far: their graphs are loaded on first open and kept
  const [opened, setOpened] = useState<Set<string>>(new Set());

  useEffect(() => {
    api<{ digests: Digest[] }>("GET", "/me/digests")
      .then((r) => {
        setDigests(r.digests);
        if (r.digests.length) setOpened(new Set([r.digests[0].date]));
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!digests) return <Loading />;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Past digests</h1>
      {!digests.length && <p className="text-sm text-slate-500">No digests yet: your first one arrives on the next weekly run.</p>}
      {digests.map((d, i) => (
        <details
          key={d.date}
          className="card"
          open={i === 0}
          onToggle={(e) => {
            if (e.currentTarget.open) setOpened((prev) => (prev.has(d.date) ? prev : new Set(prev).add(d.date)));
          }}
        >
          <summary className="cursor-pointer font-medium">
            {formatDay(d.date)}
            <span className="ml-2 text-sm font-normal text-slate-500">{d.papers.length} papers</span>
          </summary>
          <ol className="mt-4 space-y-4">
            {d.papers.map((p, j) => (
              <li key={j} className="border-t border-slate-100 pt-3 first:border-0 first:pt-0">
                <div className="font-medium">
                  {p.link ? <a className="text-indigo-700 hover:underline" href={p.link} target="_blank" rel="noreferrer">{p.title}</a> : p.title}
                </div>
                <div className="text-xs text-slate-500">
                  {[p.journal, p.relevance != null ? `relevance ${p.relevance}/10` : null].filter(Boolean).join(" · ")}
                </div>
                {p.summary && <p className="mt-1 whitespace-pre-line text-sm text-slate-700">{p.summary}</p>}
              </li>
            ))}
          </ol>
          {opened.has(d.date) && (
            <div className="mt-6 border-t border-slate-200 pt-4">
              <PaperGraph date={d.date} />
            </div>
          )}
        </details>
      ))}
    </div>
  );
}
