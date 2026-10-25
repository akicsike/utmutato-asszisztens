import { useEffect, useState } from "react";
import { adminFetch, AuthError, getSecret, setSecret } from "./adminApi";
import AnalyticsTab from "./AnalyticsTab";
import DocumentsTab from "./DocumentsTab";
import EvalTab from "./EvalTab";
import FeedbackTab from "./FeedbackTab";
import MonitoringTab from "./MonitoringTab";

const TABS = [
  { id: "analytics", label: "Analitika" },
  { id: "docs", label: "Dokumentumok" },
  { id: "feedback", label: "Visszajelzések" },
  { id: "monitoring", label: "Monitoring" },
  { id: "eval", label: "Mérések" },
] as const;
type TabId = (typeof TABS)[number]["id"];

function initialTab(): TabId {
  const h = window.location.hash.slice(1);
  return (TABS.find((t) => t.id === h)?.id ?? "analytics") as TabId;
}

export default function AdminApp() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [tab, setTab] = useState<TabId>(initialTab);

  useEffect(() => {
    if (!getSecret()) return setAuthed(false);
    adminFetch("/api/admin/documents")
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
  }, []);

  const onAuthError = (e: unknown) => {
    if (e instanceof AuthError) {
      setSecret(null);
      setAuthed(false);
    }
  };

  return (
    <div className="app admin">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>📘</span>
          <span>Útmutató-asszisztens</span>
          <span className="badge">Admin</span>
        </div>
        {authed && (
          <nav className="tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={tab === t.id}
                className={tab === t.id ? "on" : ""}
                onClick={() => {
                  setTab(t.id);
                  history.replaceState(null, "", `#${t.id}`);
                }}
              >
                {t.label}
              </button>
            ))}
          </nav>
        )}
        <div className="topbar-right">
          <a className="btn btn-ghost" href="/">Chat</a>
          {authed && (
            <button className="btn btn-ghost" onClick={() => { setSecret(null); setAuthed(false); }}>
              Kilépés
            </button>
          )}
        </div>
      </header>
      {authed === null ? (
        <div className="page-loading">Betöltés…</div>
      ) : !authed ? (
        <Login onOk={() => setAuthed(true)} />
      ) : (
        <main className="admin-main">
          {tab === "analytics" && <AnalyticsTab onAuthError={onAuthError} />}
          {tab === "docs" && <DocumentsTab onAuthError={onAuthError} />}
          {tab === "feedback" && <FeedbackTab onAuthError={onAuthError} />}
          {tab === "monitoring" && <MonitoringTab onAuthError={onAuthError} />}
          {tab === "eval" && <EvalTab onAuthError={onAuthError} />}
        </main>
      )}
    </div>
  );
}

function Login({ onOk }: { onOk: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="login panel"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setErr(null);
        setSecret(value);
        try {
          await adminFetch("/api/admin/documents");
          onOk();
        } catch (ex) {
          setSecret(null);
          setErr((ex as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h1>Admin belépés</h1>
      <p className="muted">Az admin jelszó a szerver <code>.env</code> fájljában van (ADMIN_SECRET).</p>
      <input type="password" autoFocus value={value} onChange={(e) => setValue(e.target.value)}
             placeholder="Admin jelszó" autoComplete="current-password" />
      {err && <div className="fb-err">{err}</div>}
      <button className="btn btn-primary" disabled={!value || busy}>Belépés</button>
    </form>
  );
}
