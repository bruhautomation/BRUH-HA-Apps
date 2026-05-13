import { useEffect, useRef, useState } from "preact/hooks";

interface ComposerProps {
  onSend: (text: string) => void;
  onInterrupt: () => void;
  busy: boolean;
  disabled?: boolean;
}

export function Composer({ onSend, onInterrupt, busy, disabled }: ComposerProps) {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  // Autosize the textarea up to 8 lines, then scroll inside.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const max = parseFloat(getComputedStyle(ta).lineHeight) * 8;
    ta.style.height = Math.min(max, ta.scrollHeight) + "px";
  }, [text]);

  const submit = () => {
    const t = text.trim();
    if (!t || busy || disabled) return;
    onSend(t);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent) => {
    // Enter sends, Shift+Enter newlines, like every chat app.
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div class="composer">
      <textarea
        ref={taRef}
        class="composer-input"
        placeholder={disabled ? "Connecting…" : "Message Claude…"}
        value={text}
        onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
        onKeyDown={onKeyDown}
        rows={1}
        disabled={disabled}
        autocomplete="off"
        autocapitalize="off"
        spellcheck={false}
      />
      {busy ? (
        <button type="button" class="composer-btn stop" onClick={onInterrupt}>
          Stop
        </button>
      ) : (
        <button
          type="button"
          class="composer-btn send"
          onClick={submit}
          disabled={!text.trim() || disabled}
        >
          Send
        </button>
      )}
    </div>
  );
}
