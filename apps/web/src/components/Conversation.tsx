import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { CornerDownLeft } from "lucide-react";

import type { AskResult, DiaryRow, Moment } from "../lib/api";
import { answerRoute, clock } from "../lib/format";

export interface Turn {
  key: string;
  question: string;
  note?: string;
  result?: Pick<AskResult, "answer" | "kind" | "moment" | "evidence" | "latency_ms" | "degraded" | "read_as">;
  error?: string;
}

interface Props {
  turns: Turn[];
  onAsk: (q: string) => void;
  busy: boolean;
  placeholder?: string;
  suggestions?: string[];
  context?: ReactNode;
  renderMoment?: (m: Moment) => ReactNode;
  renderEvidenceTime?: (r: DiaryRow) => ReactNode;
  empty?: ReactNode;
}

export function Conversation({ turns, onAsk, busy, placeholder, suggestions = [], context, renderMoment, renderEvidenceTime, empty }: Props) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    onAsk(q);
  };

  return (
    <div className="convo">
      <div className="convo-log">
        {turns.length === 0 && empty}
        {turns.map((t) => (
          <article key={t.key} className="turn">
            <p className="turn-q">{t.question}</p>
            {t.note && <p className="turn-note">{t.note}</p>}
            {t.result?.read_as && <p className="turn-note">Read as “{t.result.read_as}”</p>}
            {t.error && <p className="turn-error">{t.error}</p>}
            {!t.result && !t.error && <p className="turn-wait"><span />Searching the diary</p>}
            {t.result && (
              <>
                <p className="turn-a">{t.result.answer}</p>
                {t.result.moment && renderMoment?.(t.result.moment)}
                <footer className="turn-meta">
                  <span>{t.result.degraded ? "Diary only · language model offline" : answerRoute[t.result.kind] ?? t.result.kind}</span>
                  <span>{(t.result.latency_ms / 1000).toFixed(1)} s</span>
                </footer>
                {t.result.evidence.length > 0 && (
                  <details className="turn-evidence">
                    <summary>From the diary ({t.result.evidence.length})</summary>
                    <ul>
                      {t.result.evidence.map((r, i) => (
                        <li key={i}>
                          {renderEvidenceTime ? renderEvidenceTime(r) : <time>{clock(r.start)}</time>}
                          <span>{r.verb} {r.object}{r.where ? ` → ${r.where}` : ""}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}
          </article>
        ))}
        <div ref={end} />
      </div>
      <div className="convo-foot">
        {suggestions.length > 0 && (
          <div className="suggest">
            {suggestions.map((s) => <button key={s} disabled={busy} onClick={() => onAsk(s)}>{s}</button>)}
          </div>
        )}
        {context && <div className="convo-context">{context}</div>}
        <form className="ask-box" onSubmit={submit}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder ?? "Ask about what you did"}
                 aria-label="Your question" autoComplete="off" />
          <button type="submit" disabled={busy || !text.trim()} aria-label="Ask"><CornerDownLeft size={15} /></button>
        </form>
      </div>
    </div>
  );
}
