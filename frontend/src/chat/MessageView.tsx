import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fmtInt, fmtMs, fmtUsd, type AppConfig, type ChatMessage, type ImageRef } from "../api";
import { pdfPageUrl, useZoom } from "../components/ImageZoom";
import FeedbackBar from "./FeedbackBar";

const MAX_IMAGES = 6;
const CITE_RE = /\[(\d+(?:\s*[,;]\s*\d+)*)\]/g;

interface Props {
  message: ChatMessage;
  active: boolean;
  config: AppConfig | null;
  onSelect: () => void;
  onCite: (n: number) => void;
  onFeedback: (fb: ChatMessage["feedback"]) => void;
}

const STAGES = { rewrite: "Kérdés értelmezése…", search: "Keresés az útmutatókban…", answer: "Válasz írása…" };

/** "[1, 3]" -> két kattintható jelvény: markdown-linkké alakítjuk, a link-renderer jelvényt rajzol belőle. */
function withCiteLinks(text: string): string {
  return text.replace(CITE_RE, (_, nums: string) =>
    nums
      .split(/[,;]/)
      .map((n) => `[${n.trim()}](#cite-${n.trim()})`)
      .join(""),
  );
}

function MessageView({ message: m, active, config, onSelect, onCite, onFeedback }: Props) {
  const zoom = useZoom();
  const md = useMemo(() => withCiteLinks(m.content), [m.content]);

  // a válasz alatti galéria: a HIVATKOZOTT források képei, a hivatkozás sorrendjében
  const gallery = useMemo(() => {
    const seen = new Set<number>();
    const out: { image: ImageRef; title: string; pdfUrl: string }[] = [];
    for (const n of m.cited) {
      const s = m.sources.find((x) => x.n === n);
      for (const im of s?.images ?? []) {
        if (seen.has(im.id) || out.length >= MAX_IMAGES) continue;
        seen.add(im.id);
        out.push({ image: im, title: s!.title, pdfUrl: pdfPageUrl(s!.document_id, im.page) });
      }
    }
    return out;
  }, [m.cited, m.sources]);

  if (m.role === "user") return <div className="msg user">{m.content}</div>;

  const u = m.usage;
  const done = !m.stage;
  return (
    <div className={`msg-wrap${active ? " active" : ""}`}>
      <div
        className={`msg bot${m.error ? " err" : ""}`}
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("a,button")) onSelect();
        }}
        title={m.sources.length ? "Kattints a forrásai megjelenítéséhez" : undefined}
      >
        {m.stage && !m.content && <div className="stage pulse">{STAGES[m.stage]}</div>}
        {m.content && (
          <div className="md">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => {
                  if (href?.startsWith("#cite-")) {
                    const n = Number(href.slice(6));
                    return (
                      <button className="cite" onClick={() => onCite(n)} title={`${n}. forrás megnyitása a bal panelen`}>
                        {n}
                      </button>
                    );
                  }
                  return (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  );
                },
              }}
            >
              {md}
            </ReactMarkdown>
            {m.stage === "answer" && <span className="caret" aria-hidden />}
          </div>
        )}
        {m.error && <div className="err-text">{m.error}</div>}
        {gallery.length > 0 && (
          <div className="gallery">
            {gallery.map((g, i) => (
              <button key={g.image.id} className="gallery-item" onClick={() => zoom(gallery, i)}
                      title="Kattints a nagyításhoz">
                <img src={g.image.url} alt={g.image.caption ?? g.image.description ?? "kép"} loading="lazy" />
                <span>{g.image.caption ?? (g.image.page ? `${g.image.page}. oldal` : "")}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {done && !m.error && (
        <div className="msg-foot">
          {u && (
            <span
              className="usage"
              title={(u.by_purpose ?? [])
                .map((p) => `${p.purpose} (${p.model}): ${p.prompt_tokens}+${p.completion_tokens} token, ${fmtUsd(p.cost_usd)}`)
                .join("\n")}
            >
              {fmtMs(u.total_ms)} · első token {fmtMs(u.ttft_ms)} · {fmtInt(u.prompt_tokens + u.completion_tokens)} token ·{" "}
              {fmtUsd(u.cost_usd)}
            </span>
          )}
          {config && <FeedbackBar message={m} reasons={config.feedback_reasons} onSaved={onFeedback} />}
        </div>
      )}
    </div>
  );
}

export default memo(MessageView);
