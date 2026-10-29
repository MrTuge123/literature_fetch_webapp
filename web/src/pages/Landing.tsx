import { Link } from "react-router";
import { useAuth } from "../auth";

export default function Landing() {
  const { status } = useAuth();
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight">New papers in your field, every week</h1>
        <p className="max-w-2xl text-slate-600">
          Literature Fetch searches PubMed, Europe PMC, OpenAlex, Semantic Scholar and arXiv for your topic, has an
          AI model rank the results by how well they match your interests, and sends you the best few with short
          summaries — to Slack, email, or both.
        </p>
        <div className="flex gap-3">
          {status === "signedIn" ? (
            <Link to="/settings" className="btn btn-primary">Your settings</Link>
          ) : (
            <>
              <Link to="/login" className="btn btn-primary">Sign in</Link>
              <Link to="/login?mode=signUp" className="btn">Sign up with an invite code</Link>
            </>
          )}
        </div>
      </section>
      <section className="grid gap-4 sm:grid-cols-3">
        {[
          ["1. Describe your topic", "In plain English, or as an advanced boolean query. Preview what it finds before saving."],
          ["2. Tune the ranking", "Preferred authors, journals and key words; a minimum relevance score."],
          ["3. Get your digest", "Once a week, the top papers with a summary of each. Past digests stay here."],
        ].map(([title, text]) => (
          <div key={title} className="card">
            <h2 className="mb-1 font-semibold">{title}</h2>
            <p className="text-sm text-slate-600">{text}</p>
          </div>
        ))}
      </section>
      <p className="text-xs text-slate-500">Invite only: ask the lab admin for a code.</p>
    </div>
  );
}
