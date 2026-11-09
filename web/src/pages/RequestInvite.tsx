// Public form: ask for an invite. POST /invite-requests emails the bot; an admin approves it on
// the Admin page and the person gets their sign-up link by email.
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, errorText } from "../api";
import { Alert } from "../components/ui";

export default function RequestInvite() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [website, setWebsite] = useState(""); // hidden from people; bots fill it in
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("POST", "/invite-requests", { name: name.trim(), email: email.trim(), note: note.trim(), website });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <div className="card space-y-4">
        <h1 className="text-xl font-semibold">Request an invite</h1>
        {done ? (
          <>
            <Alert kind="success">
              Thanks! If your request is approved, we'll email you a sign-up link at {email.trim()}.
            </Alert>
            <Link to="/" className="text-sm text-indigo-700 hover:underline">Back to the start page</Link>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <p className="text-sm text-slate-600">Literature Fetch is invite only. Tell us who you are and we'll get back to you.</p>
            {error && <Alert>{error}</Alert>}
            <div>
              <label className="label" htmlFor="name">Name</label>
              <input id="name" className="input" required maxLength={80} autoComplete="name"
                value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="email">Email</label>
              <input id="email" type="email" className="input" required autoComplete="email"
                value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="note">Who you are (optional)</label>
              <textarea id="note" rows={3} className="input" maxLength={500}
                placeholder="e.g. PhD student in the Wang lab, working on single-cell genomics"
                value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="hidden" aria-hidden="true">
              <label htmlFor="website">Website</label>
              <input id="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
            </div>
            <button type="submit" className="btn btn-primary w-full" disabled={busy}>
              {busy ? "Sending…" : "Request invite"}
            </button>
            <p className="text-sm">
              Already have a code? <Link to="/login?mode=signUp" className="text-indigo-700 hover:underline">Sign up</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
