import { describe, expect, it } from "vitest";
import { defaultForm, formSchema, fromApi, toApi, type ApiSettings } from "./settings";

const saved: ApiSettings = {
  name: "Tiger",
  query: null,
  topic: "single-cell genomics",
  interest: "methods papers",
  sources: { pubmed: { enabled: true, query: null }, arxiv: { enabled: true, query: "cat:q-bio.GN" } },
  journals: ["Nature"],
  days_back: 7,
  max_papers: 5,
  ranking: {
    preferred_authors: [],
    preferred_journals: ["Cell"],
    key_words: ["scRNA-seq"],
    min_relevance: 5,
    min_author_h_index: 0,
    min_journal_citedness: 0,
  },
  delivery: { slack: false, email: true, chinese_summary: false },
  paused: false,
};

describe("settings form", () => {
  it("round-trips the API's settings", () => {
    const form = fromApi(saved);
    expect(form.mode).toBe("topic");
    expect(form.sources.europepmc.enabled).toBe(false);
    const back = toApi(form);
    expect(back.topic).toBe("single-cell genomics");
    expect(back.query).toBeNull();
    expect(back.sources.arxiv).toEqual({ enabled: true, query: "cat:q-bio.GN" });
    expect(back.sources.openalex).toEqual({ enabled: false, query: null });
    expect(back.ranking).toEqual(saved.ranking);
  });

  it("sends only the chosen one of topic and query", () => {
    const form = { ...fromApi(saved), mode: "query" as const, query: "  cancer AND immunotherapy " };
    const out = toApi(form);
    expect(out.topic).toBeNull();
    expect(out.query).toBe("cancer AND immunotherapy");
  });

  it("checks the form like the server does", () => {
    expect(formSchema.safeParse(fromApi(saved)).success).toBe(true);
    const empty = defaultForm("Tiger");
    const r = formSchema.safeParse(empty);
    expect(r.success).toBe(false);
    expect(r.error?.issues.map((i) => i.path.join("."))).toContain("topic");

    const noSources = fromApi(saved);
    for (const s of Object.values(noSources.sources)) s.enabled = false;
    expect(formSchema.safeParse(noSources).error?.issues.map((i) => i.path.join("."))).toContain("sources");

    expect(formSchema.safeParse({ ...fromApi(saved), max_papers: 11 }).success).toBe(false);
    expect(formSchema.safeParse({ ...fromApi(saved), days_back: Number.NaN }).success).toBe(false);
  });
});
