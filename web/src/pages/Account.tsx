import { updatePassword } from "aws-amplify/auth";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, errorText } from "../api";
import { useAuth } from "../auth";
import { Alert, Loading, Section } from "../components/ui";
import { PASSWORD_RULE, passwordProblem } from "../password";

type Msg = { kind: "error" | "success"; text: string } | null;

export default function Account() {
  const { me, refreshMe, signOut } = useAuth();
  const navigate = useNavigate();
  const [pauseMsg, setPauseMsg] = useState<Msg>(null);
  const [pwMsg, setPwMsg] = useState<Msg>(null);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmEmail, setConfirmEmail] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!me) return <Loading />;

  // Pausing is part of the saved settings, so it re-saves them with paused flipped.
  async function togglePause() {
    if (!me?.settings) return;
    setBusy(true);
    setPauseMsg(null);
    try {
      await api("PUT", "/me/preferences", { ...me.settings, paused: !me.paused });
      await refreshMe();
      setPauseMsg({ kind: "success", text: me.paused ? "Digests resumed." : "Digests paused." });
    } catch (e) {
      setPauseMsg({ kind: "error", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    setPwMsg(null);
    const problem = passwordProblem(newPw);
    if (problem) return setPwMsg({ kind: "error", text: problem });
    setBusy(true);
    try {
      await updatePassword({ oldPassword: oldPw, newPassword: newPw });
      setOldPw("");
      setNewPw("");
      setPwMsg({ kind: "success", text: "Password changed." });
    } catch (err) {
      setPwMsg({ kind: "error", text: errorText(err) });
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount() {
    setBusy(true);
    setDeleteError(null);
    try {
      await api("DELETE", "/me");
      await signOut().catch(() => undefined); // the Cognito user is already gone
      navigate("/", { replace: true });
    } catch (e) {
      setDeleteError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Account</h1>

      <Section title="Signed in as">
        <p className="text-sm">
          {me.email}
          {me.admin && <span className="ml-2 rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">admin</span>}
        </p>
      </Section>

      <Section title="Weekly digest" hint="Pausing keeps your settings; resume any time.">
        {me.settings ? (
          <div className="flex items-center gap-3">
            <span className="text-sm">{me.paused ? "Paused" : "Active"}</span>
            <button className="btn" onClick={togglePause} disabled={busy}>
              {me.paused ? "Resume digests" : "Pause digests"}
            </button>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Save your settings first.</p>
        )}
        {pauseMsg && <Alert kind={pauseMsg.kind}>{pauseMsg.text}</Alert>}
      </Section>

      <Section title="Change password">
        <form onSubmit={changePassword} className="grid gap-3 sm:max-w-sm">
          <input type="password" className="input" placeholder="Current password" autoComplete="current-password"
            value={oldPw} onChange={(e) => setOldPw(e.target.value)} required />
          <input type="password" className="input" placeholder="New password" autoComplete="new-password"
            value={newPw} onChange={(e) => setNewPw(e.target.value)} required />
          <p className="hint -mt-2">{PASSWORD_RULE}</p>
          <button className="btn w-fit" disabled={busy}>Change password</button>
          {pwMsg && <Alert kind={pwMsg.kind}>{pwMsg.text}</Alert>}
        </form>
      </Section>

      <Section title="Delete account" hint="Removes your login, settings, Slack webhook and digest history. This can't be undone.">
        <div className="grid gap-3 sm:max-w-sm">
          <input className="input" placeholder={`type ${me.email} to confirm`} value={confirmEmail}
            onChange={(e) => setConfirmEmail(e.target.value)} />
          <button className="btn btn-danger w-fit" disabled={busy || confirmEmail.trim().toLowerCase() !== me.email.toLowerCase()}
            onClick={deleteAccount}>
            Delete my account
          </button>
          {deleteError && <Alert>{deleteError}</Alert>}
        </div>
      </Section>
    </div>
  );
}
