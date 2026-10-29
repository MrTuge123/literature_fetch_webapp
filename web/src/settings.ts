// The settings form: its Zod schema (client-side checks) and conversion to/from the API's
// UserSettings (api/settings.py). The server checks everything again with Pydantic.
import { z } from "zod";

export const SOURCES = [
  { key: "pubmed", label: "PubMed" },
  { key: "europepmc", label: "Europe PMC" },
  { key: "openalex", label: "OpenAlex" },
  { key: "semantic_scholar", label: "Semantic Scholar" },
  { key: "arxiv", label: "arXiv" },
] as const;
export type SourceKey = (typeof SOURCES)[number]["key"];

// ----- what the API sends and accepts -----

export type ApiSettings = {
  name: string;
  query: string | null;
  topic: string | null;
  interest: string | null;
  sources: Partial<Record<SourceKey, { enabled: boolean; query: string | null }>>;
  journals: string[];
  days_back: number;
  max_papers: number;
  ranking: {
    preferred_authors: string[];
    preferred_journals: string[];
    key_words: string[];
    min_relevance: number;
    min_author_h_index: number;
    min_journal_citedness: number;
  };
  delivery: { slack: boolean; email: boolean; chinese_summary: boolean };
  paused: boolean;
};

// ----- the form -----

const words = (most: number) =>
  z.array(z.string().trim().min(1).max(200, "at most 200 characters each")).max(most, `at most ${most}`);
const int = (min: number, max: number) =>
  z.number({ error: "enter a number" }).int("whole numbers only").min(min, `at least ${min}`).max(max, `at most ${max}`);
const source = z.object({ enabled: z.boolean(), query: z.string().max(4000) });

export const formSchema = z
  .object({
    name: z.string().trim().min(1, "required").max(80, "at most 80 characters"),
    mode: z.enum(["topic", "query"]), // form only: which of topic / query is used
    topic: z.string().max(500, "at most 500 characters"),
    query: z.string().max(4000, "at most 4000 characters"),
    interest: z.string().max(1000, "at most 1000 characters"),
    sources: z.object({
      pubmed: source,
      europepmc: source,
      openalex: source,
      semantic_scholar: source,
      arxiv: source,
    }),
    journals: words(50),
    days_back: int(1, 60),
    max_papers: int(1, 10),
    ranking: z.object({
      preferred_authors: words(30),
      preferred_journals: words(30),
      key_words: words(30),
      min_relevance: int(0, 10),
      min_author_h_index: int(0, 200),
      min_journal_citedness: z.number({ error: "enter a number" }).min(0, "at least 0").max(100, "at most 100"),
    }),
    delivery: z.object({ slack: z.boolean(), email: z.boolean(), chinese_summary: z.boolean() }),
    paused: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (v.mode === "topic" && !v.topic.trim())
      ctx.addIssue({ code: "custom", path: ["topic"], message: "describe your topic" });
    if (v.mode === "query" && !v.query.trim())
      ctx.addIssue({ code: "custom", path: ["query"], message: "enter a query" });
    if (!Object.values(v.sources).some((s) => s.enabled))
      ctx.addIssue({ code: "custom", path: ["sources"], message: "switch on at least one source" });
  });

export type FormValues = z.infer<typeof formSchema>;

export function defaultForm(name = ""): FormValues {
  const off = () => ({ enabled: false, query: "" });
  return {
    name,
    mode: "topic",
    topic: "",
    query: "",
    interest: "",
    sources: { pubmed: { enabled: true, query: "" }, europepmc: off(), openalex: off(), semantic_scholar: off(), arxiv: off() },
    journals: [],
    days_back: 7,
    max_papers: 5,
    ranking: {
      preferred_authors: [],
      preferred_journals: [],
      key_words: [],
      min_relevance: 0,
      min_author_h_index: 0,
      min_journal_citedness: 0,
    },
    delivery: { slack: false, email: true, chinese_summary: false },
    paused: false,
  };
}

export function fromApi(s: ApiSettings | null, fallbackName = ""): FormValues {
  const f = defaultForm(fallbackName);
  if (!s) return f;
  const sources = { ...f.sources };
  for (const { key } of SOURCES) {
    const got = s.sources[key];
    sources[key] = got ? { enabled: got.enabled, query: got.query ?? "" } : { enabled: false, query: "" };
  }
  return {
    name: s.name,
    mode: s.query ? "query" : "topic",
    topic: s.topic ?? "",
    query: s.query ?? "",
    interest: s.interest ?? "",
    sources,
    journals: s.journals,
    days_back: s.days_back,
    max_papers: s.max_papers,
    ranking: { ...s.ranking },
    delivery: { ...s.delivery },
    paused: s.paused,
  };
}

const orNull = (s: string) => (s.trim() ? s.trim() : null);

export function toApi(f: FormValues): ApiSettings {
  const sources: ApiSettings["sources"] = {};
  for (const { key } of SOURCES) {
    sources[key] = { enabled: f.sources[key].enabled, query: orNull(f.sources[key].query) };
  }
  return {
    name: f.name.trim(),
    topic: f.mode === "topic" ? orNull(f.topic) : null, // the API wants exactly one of the two
    query: f.mode === "query" ? orNull(f.query) : null,
    interest: orNull(f.interest),
    sources,
    journals: f.journals,
    days_back: f.days_back,
    max_papers: f.max_papers,
    ranking: { ...f.ranking },
    delivery: { ...f.delivery },
    paused: f.paused,
  };
}
