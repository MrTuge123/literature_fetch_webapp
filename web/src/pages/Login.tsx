// Sign in, sign up (with an invite code), confirm the email code, and reset a forgotten password.
import {
  confirmResetPassword,
  confirmSignUp,
  resendSignUpCode,
  resetPassword,
  signIn,
  signUp,
} from "aws-amplify/auth";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router";
import { useAuth } from "../auth";
import { Alert, Loading } from "../components/ui";
import { PASSWORD_RULE, passwordProblem } from "../password";

type Mode = "signIn" | "signUp" | "confirm" | "forgot" | "reset";

// Cognito wraps the pre-sign-up trigger's message: "PreSignUp failed with error <ours>."
function cleanError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  return msg.replace(/^PreSignUp failed with error\s*/i, "").replace(/\.\.$/, ".");
}

export default function Login() {
  const { status, refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const from = (location.state as { from?: string } | null)?.from ?? "/settings";

  const [mode, setMode] = useState<Mode>(params.get("invite") || params.get("mode") === "signUp" ? "signUp" : "signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState(params.get("invite") ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "loading") return <Loading />;
  if (status === "signedIn") return <Navigate to={from} replace />;

  function go(next: Mode, message: string | null = null) {
    setMode(next);
    setError(null);
    setInfo(message);
    setCode("");
  }

  async function finishSignIn() {
    await refresh();
    navigate(from, { replace: true });
  }

  async function run(e: FormEvent, action: () => Promise<void>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(cleanError(err));
    } finally {
      setBusy(false);
    }
  }

  const username = email.trim().toLowerCase();

  const onSignIn = (e: FormEvent) =>
    run(e, async () => {
      const r = await signIn({ username, password });
      if (r.isSignedIn) return finishSignIn();
      if (r.nextStep.signInStep === "CONFIRM_SIGN_UP") {
        await resendSignUpCode({ username });
        return go("confirm", "Your email isn't confirmed yet: we sent a new code.");
      }
      if (r.nextStep.signInStep === "RESET_PASSWORD") return go("forgot", "Please reset your password.");
      setError(`Unexpected sign-in step: ${r.nextStep.signInStep}`);
    });

  const onSignUp = (e: FormEvent) =>
    run(e, async () => {
      const problem = passwordProblem(password);
      if (problem) throw new Error(problem);
      if (!invite.trim()) throw new Error("Enter your invite code.");
      const r = await signUp({
        username,
        password,
        options: {
          userAttributes: { email: username },
          clientMetadata: { invite: invite.trim().toUpperCase() }, // checked by api/presignup.py
        },
      });
      if (r.nextStep.signUpStep === "CONFIRM_SIGN_UP") go("confirm", `We emailed a 6-digit code to ${username}.`);
      else go("signIn", "Account created: sign in.");
    });

  const onConfirm = (e: FormEvent) =>
    run(e, async () => {
      await confirmSignUp({ username, confirmationCode: code.trim() });
      if (password) {
        const r = await signIn({ username, password });
        if (r.isSignedIn) return finishSignIn();
      }
      go("signIn", "Email confirmed: sign in.");
    });

  const onForgot = (e: FormEvent) =>
    run(e, async () => {
      await resetPassword({ username });
      go("reset", `If ${username} has an account, we emailed it a code.`);
    });

  const onReset = (e: FormEvent) =>
    run(e, async () => {
      const problem = passwordProblem(password);
      if (problem) throw new Error(problem);
      await confirmResetPassword({ username, confirmationCode: code.trim(), newPassword: password });
      const r = await signIn({ username, password });
      if (r.isSignedIn) return finishSignIn();
      go("signIn", "Password changed: sign in.");
    });

  const emailField = (
    <div>
      <label className="label" htmlFor="email">Email</label>
      <input id="email" type="email" className="input" autoComplete="email" required
        value={email} onChange={(e) => setEmail(e.target.value)} />
    </div>
  );
  const passwordField = (label: string, autoComplete: string, hint?: string) => (
    <div>
      <label className="label" htmlFor="password">{label}</label>
      <input id="password" type="password" className="input" autoComplete={autoComplete} required
        value={password} onChange={(e) => setPassword(e.target.value)} />
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
  const codeField = (
    <div>
      <label className="label" htmlFor="code">Code from the email</label>
      <input id="code" inputMode="numeric" className="input" autoComplete="one-time-code" required
        value={code} onChange={(e) => setCode(e.target.value)} />
    </div>
  );
  const submit = (text: string) => (
    <button type="submit" className="btn btn-primary w-full" disabled={busy}>
      {busy ? "Working…" : text}
    </button>
  );
  const link = (text: string, next: Mode) => (
    <button type="button" className="text-indigo-700 hover:underline" onClick={() => go(next)}>
      {text}
    </button>
  );

  const titles: Record<Mode, string> = {
    signIn: "Sign in",
    signUp: "Create your account",
    confirm: "Confirm your email",
    forgot: "Reset your password",
    reset: "Choose a new password",
  };

  return (
    <div className="mx-auto max-w-sm">
      <div className="card space-y-4">
        <h1 className="text-xl font-semibold">{titles[mode]}</h1>
        {info && <Alert kind="info">{info}</Alert>}
        {error && <Alert>{error}</Alert>}

        {mode === "signIn" && (
          <form onSubmit={onSignIn} className="space-y-4">
            {emailField}
            {passwordField("Password", "current-password")}
            {submit("Sign in")}
            <div className="flex justify-between text-sm">
              {link("Forgot password?", "forgot")}
              {link("Have an invite? Sign up", "signUp")}
            </div>
          </form>
        )}

        {mode === "signUp" && (
          <form onSubmit={onSignUp} className="space-y-4">
            <div>
              <label className="label" htmlFor="invite">Invite code</label>
              <input id="invite" className="input font-mono uppercase" required maxLength={16}
                value={invite} onChange={(e) => setInvite(e.target.value)} />
            </div>
            {emailField}
            {passwordField("Password", "new-password", PASSWORD_RULE)}
            {submit("Sign up")}
            <p className="text-sm">Already have an account? {link("Sign in", "signIn")}</p>
          </form>
        )}

        {mode === "confirm" && (
          <form onSubmit={onConfirm} className="space-y-4">
            {!email && emailField}
            {codeField}
            {submit("Confirm")}
            <button type="button" className="text-sm text-indigo-700 hover:underline" disabled={busy}
              onClick={async () => {
                try {
                  await resendSignUpCode({ username });
                  setInfo("Sent a new code.");
                } catch (err) {
                  setError(cleanError(err));
                }
              }}>
              Send a new code
            </button>
          </form>
        )}

        {mode === "forgot" && (
          <form onSubmit={onForgot} className="space-y-4">
            {emailField}
            {submit("Email me a code")}
            <p className="text-sm">{link("Back to sign in", "signIn")}</p>
          </form>
        )}

        {mode === "reset" && (
          <form onSubmit={onReset} className="space-y-4">
            {codeField}
            {passwordField("New password", "new-password", PASSWORD_RULE)}
            {submit("Change password")}
          </form>
        )}
      </div>
    </div>
  );
}
