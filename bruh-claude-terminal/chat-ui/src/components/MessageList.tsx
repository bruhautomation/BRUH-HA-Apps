import { useEffect, useRef } from "preact/hooks";
import type { Turn } from "~/lib/chatState";
import { ToolBlock } from "./ToolBlock";

function renderTextBlock(text: string) {
  // Render markdown-style fenced code blocks specially so they get a copy
  // button. Everything else is plain text with preserved newlines. Keeping
  // this dependency-free for v1; a real markdown renderer can go in v2.
  const parts: Array<{ kind: "text" | "code"; lang?: string; body: string }> = [];
  const re = /```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ kind: "text", body: text.slice(last, m.index) });
    parts.push({ kind: "code", lang: m[1] || "", body: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ kind: "text", body: text.slice(last) });
  if (parts.length === 0) parts.push({ kind: "text", body: text });
  return parts.map((p, i) =>
    p.kind === "code" ? (
      <CodeBlock key={i} lang={p.lang!} body={p.body} />
    ) : (
      <span key={i} class="text-body">{p.body}</span>
    ),
  );
}

function CodeBlock({ lang, body }: { lang: string; body: string }) {
  const onCopy = () => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(body).catch(() => {
        // Silent — toast UI lives in v2.
      });
    }
  };
  return (
    <div class="code-block">
      <div class="code-head">
        <span class="code-lang">{lang || "code"}</span>
        <button type="button" class="code-copy" onClick={onCopy}>Copy</button>
      </div>
      <pre><code>{body}</code></pre>
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  return (
    <div class={`turn turn-${turn.role}${turn.status === "streaming" ? " streaming" : ""}`}>
      <div class="turn-bubble">
        {turn.blocks.map((b, i) => {
          if (b.kind === "text") {
            return <div key={i} class="block-text">{renderTextBlock(b.text)}</div>;
          }
          if (b.kind === "tool_use") {
            return <ToolBlock key={b.id} block={b} />;
          }
          if (b.kind === "note") {
            return <div key={i} class="block-note">{b.text}</div>;
          }
          return null;
        })}
        {turn.status === "streaming" && turn.blocks.length === 0 ? (
          <div class="streaming-indicator">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function MessageList({ turns }: { turns: Turn[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const userPinnedRef = useRef(false);

  // Auto-scroll on new turns, but only if the user hasn't manually scrolled
  // up to read history. The check is: are we within 40px of the bottom?
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (!userPinnedRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [turns]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    userPinnedRef.current = !atBottom;
  };

  return (
    <div class="message-list" ref={scrollRef} onScroll={onScroll}>
      {turns.length === 0 ? (
        <div class="empty-state">
          <h2>BRUH Claude</h2>
          <p>Ask Claude anything about your Home Assistant config.</p>
        </div>
      ) : (
        turns.map((t) => <TurnView key={t.id} turn={t} />)
      )}
    </div>
  );
}
