// The preferences form (React Hook Form + Zod), the Slack webhook, Preview and Send test.
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link } from "react-router";
import { api, errorText, type Me, type PreviewResult, type TestResult } from "../api";
import { useAuth } from "../auth";
import TagInput from "../components/TagInput";
import { Alert, Loading, Section } from "../components/ui";
import { SOURCES, formSchema, fromApi, toApi, type ApiSettings, type FormValues } from "../settings";

export default function Settings() {
  const { me, meError } = useAuth();
  if (!me) return meError ? <Alert>{meError}</Alert> : <Loading />;
  return <SettingsForm me={me} />;
}

type Notice = { kind: "error" | "success" | "info"; text: string; fields?: string[] } | null;

function SettingsForm({ me }: { me: Me }) {
  const { refreshMe } = useAuth();
  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    setValue,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: fromApi(me.settings, me.email.split("@")[0]),
  });
  const [notice, setNotice] = useState<Notice>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState<"preview" | "test" | null>(null);

  const mode = watch("mode");
  const minRelevance = watch("ranking.min_relevance");

  function fail(e: unknown) {
    const fields = e && typeof e === "object" && "fields" in e ? (e as { fields: string[] }).fields : [];
    setNotice({ kind: "error", text: errorText(e), fields });
  }

  const onSave = handleSubmit(async (values) => {
    setNotice(null);
    try {
      const r = await api<{ settings: ApiSettings }>("PUT", "/me/preferences", toApi(values));
      reset(fromApi(r.settings));
      await refreshMe();
      setNotice({ kind: "success", text: "Saved." });
    } catch (e) {
      fail(e);
    }
  });

  const onPreview = handleSubmit(async (values) => {
    setNotice(null);
    setPreview(null);
    setBusy("preview");
    try {
      setPreview(await api<PreviewResult>("POST", "/me/preview", toApi(values)));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  });

  async function onTest() {
    setNotice(null);
    setBusy("test");
    try {
      const r = await api<TestResult>("POST", "/me/test-delivery");
      const failed = Object.entries(r.failed).map(([k, v]) => `${k}: ${v}`);
      setNotice({
        kind: failed.length ? "error" : "success",
        text: `${r.sent.length ? `Sent to ${r.sent.join(" and ")}.` : "Nothing sent."}${failed.length ? ` Failed — ${failed.join("; ")}` : ""}`,
      });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  const err = (m?: string) => (m ? <p className="field-error">{m}</p> : null);

  return (
    <form onSubmit={onSave} className="space-y-6" noValidate>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Your digest settings</h1>
          <p className="text-sm text-slate-500">
            {me.settings ? "Changes apply from the next weekly digest." : "Nothing saved yet: fill this in and Save."}
          </p>
        </div>
      </div>

      {me.paused && (
        <Alert kind="info">
          Your digests are paused. Resume them on the <Link className="underline" to="/account">Account</Link> page.
        </Alert>
      )}

      <Section title="Topic" hint="What should the weekly search look for?">
        <div>
          <label className="label" htmlFor="name">Digest name</label>
          <input id="name" className="input" {...register("name")} />
          {err(errors.name?.message)}
        </div>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="radio" value="topic" {...register("mode")} /> Plain English
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" value="query" {...register("mode")} /> Advanced boolean query
          </label>
        </div>
        {mode === "topic" ? (
          <div>
            <label className="label" htmlFor="topic">Topic</label>
            <textarea id="topic" rows={2} className="input" placeholder="e.g. machine learning for single-cell RNA sequencing"
              {...register("topic")} />
            <p className="hint">An AI model turns this into a search query for each source.</p>
            {err(errors.topic?.message)}
          </div>
        ) : (
          <div>
            <label className="label" htmlFor="query">Boolean query</label>
            <textarea id="query" rows={3} className="input font-mono" placeholder='("single cell"[tiab] OR scRNA-seq) AND (deep learning OR transformer)'
              {...register("query")} />
            <p className="hint">PubMed syntax. Used as-is for PubMed and adapted for the other sources.</p>
            {err(errors.query?.message)}
          </div>
        )}
        <div>
          <label className="label" htmlFor="interest">What you care about most (optional)</label>
          <textarea id="interest" rows={2} className="input" placeholder="e.g. new computational methods, not clinical case reports"
            {...register("interest")} />
          <p className="hint">Helps the AI model score how relevant each paper is to you.</p>
          {err(errors.interest?.message)}
        </div>
      </Section>

      <Section title="Sources">
        <div className="space-y-3">
          {SOURCES.map(({ key, label }) => (
            <div key={key}>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" {...register(`sources.${key}.enabled`)} /> {label}
              </label>
              {watch(`sources.${key}.enabled`) && (
                <details className="ml-6 mt-1">
                  <summary className="cursor-pointer text-xs text-slate-500">Advanced: this source's own query</summary>
                  <input className="input mt-1 font-mono" placeholder={`leave empty to use your topic`}
                    {...register(`sources.${key}.query`)} />
                </details>
              )}
            </div>
          ))}
        </div>
        {err(errors.sources?.message)}
      </Section>

      <Section title="Filters">
        <div>
          <label className="label">Only these journals (optional)</label>
          <Controller control={control} name="journals"
            render={({ field }) => <TagInput value={field.value} onChange={field.onChange} max={50} placeholder="type a journal, press Enter" />} />
          <p className="hint">Leave empty for all journals.</p>
          {err(errors.journals?.message)}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="days_back">Look back (days)</label>
            <input id="days_back" type="number" min={1} max={60} className="input" {...register("days_back", { valueAsNumber: true })} />
            {err(errors.days_back?.message)}
          </div>
          <div>
            <label className="label" htmlFor="max_papers">Papers per digest</label>
            <input id="max_papers" type="number" min={1} max={10} className="input" {...register("max_papers", { valueAsNumber: true })} />
            {err(errors.max_papers?.message)}
          </div>
        </div>
      </Section>

      <Section title="Ranking" hint="Papers matching these get a boost.">
        {(
          [
            ["preferred_authors", "Preferred authors", "e.g. Regev A"],
            ["preferred_journals", "Preferred journals", "e.g. Nature Methods"],
            ["key_words", "Key words", "e.g. spatial transcriptomics"],
          ] as const
        ).map(([name, label, placeholder]) => (
          <div key={name}>
            <label className="label">{label}</label>
            <Controller control={control} name={`ranking.${name}`}
              render={({ field }) => <TagInput value={field.value} onChange={field.onChange} placeholder={placeholder} />} />
            {err(errors.ranking?.[name]?.message)}
          </div>
        ))}
        <div>
          <label className="label" htmlFor="min_relevance">Minimum relevance: {Number.isNaN(minRelevance) ? 0 : minRelevance} / 10</label>
          <input id="min_relevance" type="range" min={0} max={10} step={1} className="w-full"
            {...register("ranking.min_relevance", { valueAsNumber: true })} />
          <p className="hint">Papers the AI model scores below this are left out. 0 keeps everything.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="h_index">Minimum author h-index</label>
            <input id="h_index" type="number" min={0} max={200} className="input"
              {...register("ranking.min_author_h_index", { valueAsNumber: true })} />
            {err(errors.ranking?.min_author_h_index?.message)}
          </div>
          <div>
            <label className="label" htmlFor="citedness">Minimum journal citedness</label>
            <input id="citedness" type="number" min={0} max={100} step="0.1" className="input"
              {...register("ranking.min_journal_citedness", { valueAsNumber: true })} />
            {err(errors.ranking?.min_journal_citedness?.message)}
          </div>
        </div>
      </Section>

      <Section title="Delivery">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("delivery.email")} /> Email to {me.email}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" disabled={!me.has_webhook} {...register("delivery.slack")} /> Slack
          {!me.has_webhook && <span className="text-xs text-slate-500">(save a webhook below first)</span>}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...register("delivery.chinese_summary")} /> Add a Chinese summary
        </label>
        <Webhook me={me} onRemoved={() => setValue("delivery.slack", false)} />
      </Section>

      {notice && (
        <Alert kind={notice.kind}>
          {notice.text}
          {notice.fields && notice.fields.length > 1 && (
            <ul className="mt-1 list-disc pl-5">{notice.fields.map((f) => <li key={f}>{f}</li>)}</ul>
          )}
        </Alert>
      )}

      <div className="sticky bottom-0 -mx-4 flex flex-wrap gap-3 border-t border-slate-200 bg-slate-50/95 px-4 py-3">
        <button type="submit" className="btn btn-primary" disabled={isSubmitting || (!isDirty && !!me.settings)}>
          {isSubmitting ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn" onClick={onPreview} disabled={busy !== null}>
          {busy === "preview" ? "Searching… (up to 30 s)" : "Preview"}
        </button>
        <button type="button" className="btn" onClick={onTest} disabled={busy !== null || isDirty || !me.settings}
          title={isDirty || !me.settings ? "Save first" : "Send a short test message (3 a day)"}>
          {busy === "test" ? "Sending…" : "Send test"}
        </button>
        {isDirty && <span className="self-center text-xs text-amber-700">Unsaved changes</span>}
      </div>

      {preview && <PreviewBox result={preview} />}
    </form>
  );
}

function PreviewBox({ result }: { result: PreviewResult }) {
  return (
    <Section title={`Preview: ${result.count} papers found right now`}
      hint="Search only, before AI ranking and summaries; your digest picks the best of these.">
      <div className="flex flex-wrap gap-2 text-xs">
        {Object.entries(result.found).map(([source, n]) => (
          <span key={source} className={`rounded px-2 py-0.5 ${typeof n === "number" ? "bg-slate-100" : "bg-red-50 text-red-700"}`}>
            {source}: {n}
          </span>
        ))}
      </div>
      {result.examples.length ? (
        <ol className="list-decimal space-y-2 pl-5 text-sm">
          {result.examples.map((p, i) => (
            <li key={i}>
              {p.link ? <a className="text-indigo-700 hover:underline" href={p.link} target="_blank" rel="noreferrer">{p.title}</a> : p.title}
              {p.journal && <span className="text-slate-500"> — {p.journal}</span>}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-slate-500">Nothing found: try a broader topic or more days.</p>
      )}
    </Section>
  );
}

// The webhook URL is write-only: the API stores it in Parameter Store and never sends it back.
function Webhook({ me, onRemoved }: { me: Me; onRemoved: () => void }) {
  const { refreshMe } = useAuth();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Notice>(null);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      await refreshMe();
      setMsg({ kind: "success", text: ok });
      setUrl("");
    } catch (e) {
      setMsg({ kind: "error", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <p className="mb-2 font-medium">Slack webhook</p>
      {me.has_webhook ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-green-700">A webhook is saved.</span>
          <button type="button" className="btn py-1" disabled={busy}
            onClick={() => act(async () => { await api("DELETE", "/me/webhook"); onRemoved(); }, "Webhook removed; Slack is off.")}>
            Remove
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <input className="input flex-1" placeholder="https://hooks.slack.com/services/…" value={url} onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && e.preventDefault()} />
          <button type="button" className="btn" disabled={busy || !url.trim()}
            onClick={() => act(() => api("PUT", "/me/webhook", { url: url.trim() }), "Webhook saved: you can switch Slack on now.")}>
            Save webhook
          </button>
        </div>
      )}
      <p className="hint">
        Make one in Slack: Apps → Incoming Webhooks → Add to a channel. It's stored encrypted and never shown again.
      </p>
      {msg && <div className="mt-2"><Alert kind={msg.kind}>{msg.text}</Alert></div>}
    </div>
  );
}
