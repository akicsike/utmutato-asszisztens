import { useCallback, useEffect, useRef, useState } from "react";
import { api, fromRaw, streamChat, type AppConfig, type ChatMessage, type Conversation } from "../api";
import ConversationDrawer from "./ConversationDrawer";
import MessageView from "./MessageView";
import SourcesPanel from "./SourcesPanel";
import { useDictation } from "./useDictation";

const CONV_KEY = "utmutato.conversation";

function storedConversation(): string | null {
  try {
    return localStorage.getItem(CONV_KEY);
  } catch {
    return null;
  }
}

function storeConversation(id: string | null) {
  try {
    if (id) localStorage.setItem(CONV_KEY, id);
    else localStorage.removeItem(CONV_KEY);
  } catch {
    /* privát mód */
  }
}

export default function ChatApp() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(storedConversation);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [flash, setFlash] = useState<{ n: number; key: number } | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [mobileTab, setMobileTab] = useState<"chat" | "sources">("chat");
  const [loadError, setLoadError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickRef = useRef(true);
  const [dictError, setDictError] = useState<string | null>(null);
  const dictation = useDictation({
    onText: setInput,
    onError: (msg) => {
      setDictError(msg);
      setTimeout(() => setDictError(null), 6000);
    },
  });

  const refreshConversations = useCallback(() => {
    api.conversations().then((r) => setConversations(r.conversations)).catch(() => {});
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch((e) => setLoadError(String(e.message ?? e)));
    refreshConversations();
  }, [refreshConversations]);

  // a mentett beszélgetés betöltése (oldalfrissítés után is megmarad)
  useEffect(() => {
    if (!conversationId || messages.length) return;
    api
      .conversation(conversationId)
      .then((r) => {
        const msgs = r.messages.map(fromRaw);
        setMessages(msgs);
        setActiveId([...msgs].reverse().find((m) => m.role === "assistant")?.id ?? null);
      })
      .catch(() => {
        setConversationId(null);
        storeConversation(null);
      });
    // csak induláskor / váltáskor
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // automatikus görgetés, ha a felhasználó az alján van
  useEffect(() => {
    const el = listRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const patch = (id: string, fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? fn(m) : m)));

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    dictation.abort(); // küldéskor a diktálás leáll, a késve érkező szöveg nem kerül vissza a mezőbe
    setInput("");
    setBusy(true);
    stickRef.current = true;
    let userId = `u-${Date.now()}`;
    let botId = `a-${Date.now()}`;
    const empty = { sources: [], cited: [], usage: null, error: null };
    setMessages((ms) => [
      ...ms,
      { id: userId, role: "user", content: question, ...empty },
      { id: botId, role: "assistant", content: "", ...empty, stage: "rewrite" },
    ]);
    setActiveId(botId);
    setMobileTab("chat");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat(
        { message: question, conversation_id: conversationId },
        (ev) => {
          switch (ev.type) {
            case "meta": {
              const [oldU, oldB] = [userId, botId];
              userId = ev.user_message_id;
              botId = ev.message_id;
              setMessages((ms) =>
                ms.map((m) => (m.id === oldU ? { ...m, id: userId } : m.id === oldB ? { ...m, id: botId } : m)),
              );
              setActiveId(botId);
              if (ev.conversation_id !== conversationId) {
                setConversationId(ev.conversation_id);
                storeConversation(ev.conversation_id);
              }
              break;
            }
            case "plan":
              patch(botId, (m) => ({ ...m, stage: "search", searchQuery: ev.query }));
              break;
            case "sources":
              patch(botId, (m) => ({ ...m, sources: ev.sources, stage: "answer" }));
              break;
            case "delta":
              patch(botId, (m) => ({ ...m, content: m.content + ev.text, stage: "answer" }));
              break;
            case "done":
              patch(botId, (m) => ({ ...m, cited: ev.cited, usage: ev.usage, stage: null }));
              break;
            case "error":
              patch(botId, (m) => ({ ...m, error: ev.message, stage: null }));
              break;
          }
        },
        ctrl.signal,
      );
    } catch (e) {
      const aborted = (e as Error).name === "AbortError";
      patch(botId, (m) => ({ ...m, stage: null, error: aborted ? "Megszakítva." : `Hálózati hiba: ${(e as Error).message}` }));
    } finally {
      setBusy(false);
      abortRef.current = null;
      refreshConversations();
      inputRef.current?.focus();
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setConversationId(null);
    storeConversation(null);
    setMessages([]);
    setActiveId(null);
    setDrawer(false);
    inputRef.current?.focus();
  }

  function openConversation(id: string) {
    if (busy) return;
    setMessages([]);
    setActiveId(null);
    setConversationId(id);
    storeConversation(id);
    setDrawer(false);
  }

  const active = messages.find((m) => m.id === activeId) ?? null;
  const onCite = (msgId: string, n: number) => {
    setActiveId(msgId);
    setFlash({ n, key: Date.now() });
    setMobileTab("sources");
  };

  return (
    <div className="app">
      <header className="topbar">
        <button className="btn btn-ghost" onClick={() => setDrawer(true)} title="Korábbi beszélgetések">
          ☰ <span className="hide-sm">Beszélgetések</span>
        </button>
        <div className="brand">
          <span className="logo" aria-hidden>📘</span>
          <span>Útmutató-asszisztens</span>
        </div>
        <div className="topbar-right">
          <button className="btn" onClick={newChat} disabled={busy && !abortRef.current}>
            ＋ <span className="hide-sm">Új beszélgetés</span>
          </button>
          <a className="btn btn-ghost" href="/admin" title="Admin felület">Admin</a>
        </div>
      </header>

      <div className="mobile-tabs" role="tablist">
        <button role="tab" aria-selected={mobileTab === "chat"} className={mobileTab === "chat" ? "on" : ""}
                onClick={() => setMobileTab("chat")}>Chat</button>
        <button role="tab" aria-selected={mobileTab === "sources"} className={mobileTab === "sources" ? "on" : ""}
                onClick={() => setMobileTab("sources")}>
          Források{active?.sources.length ? ` (${active.sources.length})` : ""}
        </button>
      </div>

      <main className={`layout show-${mobileTab}`}>
        <aside className="col-sources">
          <SourcesPanel message={active} flash={flash} />
        </aside>

        <section className="col-chat panel">
          <div
            className="messages"
            ref={listRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
          >
            {messages.length === 0 && (
              <Welcome config={config} error={loadError} onPick={(q) => send(q)} />
            )}
            {messages.map((m) => (
              <MessageView
                key={m.id}
                message={m}
                active={m.id === activeId}
                config={config}
                onSelect={() => {
                  setActiveId(m.id);
                  setMobileTab("sources");
                }}
                onCite={(n) => onCite(m.id, n)}
                onFeedback={(fb) => patch(m.id, (x) => ({ ...x, feedback: fb }))}
              />
            ))}
          </div>

          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              maxLength={2000}
              placeholder={dictation.listening ? "Hallgatlak… beszélj magyarul, a gombbal állítsd le."
                : "Kérdezz egy eszköz használatáról… (Enter: küldés, Shift+Enter: új sor)"}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              autoFocus
            />
            {dictation.supported && (
              <button
                type="button"
                className={`btn btn-mic${dictation.listening ? " on" : ""}`}
                onClick={() => dictation.toggle(input)}
                disabled={busy}
                aria-pressed={dictation.listening}
                aria-label={dictation.listening ? "Diktálás leállítása" : "Diktálás (magyar)"}
                title={dictation.listening ? "Diktálás leállítása" : "Diktálás (magyar) – Chrome / Edge"}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"
                     strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="2" width="6" height="12" rx="3" />
                  <path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8" />
                </svg>
              </button>
            )}
            {busy ? (
              <button type="button" className="btn btn-stop" onClick={() => abortRef.current?.abort()}>
                ■ Leállítás
              </button>
            ) : (
              <button type="submit" className="btn btn-primary" disabled={!input.trim()}>
                Küldés ➤
              </button>
            )}
          </form>
          {dictError && <div className="dict-error" role="alert">{dictError}</div>}
          <div className="disclaimer">
            Az asszisztens csak a feltöltött útmutatókból válaszol, de tévedhet – fontos lépés előtt nézd meg a
            hivatkozott oldalt.
          </div>
        </section>
      </main>

      <ConversationDrawer
        open={drawer}
        conversations={conversations}
        currentId={conversationId}
        onClose={() => setDrawer(false)}
        onOpen={openConversation}
        onNew={newChat}
        onRename={async (id, title) => {
          await api.renameConversation(id, title);
          refreshConversations();
        }}
        onDelete={async (id) => {
          await api.deleteConversation(id);
          if (id === conversationId) newChat();
          refreshConversations();
        }}
      />
    </div>
  );
}

function Welcome({ config, error, onPick }: { config: AppConfig | null; error: string | null; onPick: (q: string) => void }) {
  return (
    <div className="welcome">
      <div className="msg bot">
        <p>
          <b>Szia!</b> A feltöltött használati útmutatókból válaszolok: használat, beállítás, tisztítás,
          karbantartás, hibaelhárítás. A válasz számozott hivatkozásaira kattintva bal oldalt látod a pontos
          útmutató-részletet, és a PDF-et is megnyithatod az adott oldalon.
        </p>
      </div>
      {error && <div className="msg bot err">A szerver nem érhető el: {error}</div>}
      {config && (
        <>
          <div className="examples">
            {config.examples.map((q) => (
              <button key={q} className="chip" onClick={() => onPick(q)}>
                {q}
              </button>
            ))}
          </div>
          {config.devices.length > 0 && (
            <details className="devices">
              <summary>{config.devices.length} útmutató érhető el</summary>
              <ul>
                {config.devices.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
