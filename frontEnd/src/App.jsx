import { useRivalSession } from "./hooks/useRivalSession";
import Dashboard from "./DashBoard";
import "./App.css";

export default function App() {
  const auth = useRivalSession();
  if (auth.loading) return <main className="welcome"><div className="brand"><span className="brand-mark">R</span>RivalSense</div><p role="status">Restoring your workspace…</p></main>;
  if (auth.session) return <Dashboard key={auth.session.user.id} {...auth} />;
  return <main className="welcome">
    <div className="welcome-grid" aria-hidden="true" />
    <div className="brand"><span className="brand-mark">R</span> RivalSense<span className="brand-caption">WEB INTELLIGENCE</span></div>
    <section className="welcome-card">
      <span className="eyebrow"><span className="live-dot" /> RESEARCH WITH EVIDENCE</span>
      <h1>A clearer view.<br /><em>A smarter next move.</em></h1>
      <p>Ask a real question. Explore competitor prices. Make decisions with information you can trace back to the web.</p>
      <button className="primary google-button" onClick={auth.signIn}><span className="google-g">G</span> Continue with Google <span>↗</span></button>
      {auth.error && <p className="error" role="alert">{auth.error}</p>}
      <div className="welcome-features"><span>↗ Live web research</span><span>◎ Cited sources</span><span>◫ Product intelligence</span></div>
      <small>Existing Supabase Google sign-in · Provider keys stay on the server</small>
    </section>
    <footer>Built for people who ask better questions.<span>Powered by Context.dev</span></footer>
  </main>;
}
