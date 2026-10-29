// Invite codes (admins only; the API checks the token's cognito:groups too).
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Invite } from "../api";
import { Alert, Loading, Section } from "../components/ui";

const signUpLink = (code: string) => `${window.location.origin}/login?invite=${code}`;

function status(i: Invite) {
  if (i.used_by) return <span className="text-slate-500">used by {i.used_by}</span>;
  if (new Date(i.expires_at) < new Date()) return <span className="text-slate-400">expired</span>;
  return <span className="text-green-700">unused</span>;
}

export default function Admin() {
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(1);
  const [days, setDays] = useState(14);
  const [note, setNote] = useState("");
  const [made, setMade] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<{ invites: Invite[] }>("GET", "/admin/invites")
      .then((r) => setInvites([...r.invites].sort((a, b) => b.expires_at.localeCompare(a.expires_at))))
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ codes: string[] }>("POST", "/admin/invites", { count, days, note });
      setMade(r.codes);
      setNote("");
      load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Admin</h1>
      {error && <Alert>{error}</Alert>}

      <Section title="New invite codes" hint="Each code allows one sign-up.">
        <form onSubmit={create} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label" htmlFor="count">How many</label>
            <input id="count" type="number" min={1} max={20} className="input w-24" value={count}
              onChange={(e) => setCount(Number(e.target.value))} />
          </div>
          <div>
            <label className="label" htmlFor="days">Valid (days)</label>
            <input id="days" type="number" min={1} max={60} className="input w-24" value={days}
              onChange={(e) => setDays(Number(e.target.value))} />
          </div>
          <div className="flex-1">
            <label className="label" htmlFor="note">Who it's for</label>
            <input id="note" className="input" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <button className="btn btn-primary" disabled={busy}>Create</button>
        </form>
        {made.length > 0 && (
          <Alert kind="success">
            <p className="mb-1">Send each person their link:</p>
            <ul className="space-y-1">
              {made.map((c) => (
                <li key={c} className="flex flex-wrap items-center gap-2">
                  <code className="font-mono">{signUpLink(c)}</code>
                  <button type="button" className="text-xs underline" onClick={() => navigator.clipboard.writeText(signUpLink(c))}>
                    copy
                  </button>
                </li>
              ))}
            </ul>
          </Alert>
        )}
      </Section>

      <Section title="All invite codes">
        {!invites ? (
          <Loading />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr><th className="py-2 pr-4">Code</th><th className="pr-4">For</th><th className="pr-4">Expires</th><th>Status</th></tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.code} className="border-t border-slate-100">
                    <td className="py-2 pr-4 font-mono">{i.code}</td>
                    <td className="pr-4">{i.note}</td>
                    <td className="pr-4">{new Date(i.expires_at).toLocaleDateString()}</td>
                    <td>{status(i)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
