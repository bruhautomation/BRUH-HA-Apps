import { useEffect, useRef, useState } from "preact/hooks";
import {
  appendUserTurn,
  initialState,
  reduce,
  type ChatState,
} from "~/lib/chatState";
import type { WireEvent } from "~/lib/events";
import { WSClient, wsUrl, type WSStatus } from "~/lib/ws";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";

export function Chat() {
  const [state, setState] = useState<ChatState>(initialState);
  const [wsStatus, setWsStatus] = useState<WSStatus>("connecting");
  const clientRef = useRef<WSClient | null>(null);

  useEffect(() => {
    const client = new WSClient({
      url: wsUrl("/ws/chat"),
      onEvent: (ev: WireEvent) => setState((s) => reduce(s, ev)),
      onStatus: (st) => setWsStatus(st),
    });
    clientRef.current = client;
    client.start();
    return () => client.stop();
  }, []);

  const onSend = (text: string) => {
    setState((s) => appendUserTurn(s, text));
    clientRef.current?.send({ type: "user", content: text });
  };

  const onInterrupt = () => {
    clientRef.current?.send({ type: "interrupt" });
  };

  const busy = state.status === "thinking";
  const connected = wsStatus === "open";

  return (
    <div class="chat-shell">
      <header class="chat-header">
        <div class="chat-title">BRUH Claude</div>
        <div class="chat-meta">
          {state.sessionId ? (
            <span class="session-id" title={state.sessionId}>
              {state.sessionId.slice(0, 8)}
            </span>
          ) : null}
          <span class={`ws-pill ws-${wsStatus}`}>
            {wsStatus === "open" ? "connected" :
             wsStatus === "connecting" ? "connecting…" :
             wsStatus === "closed" ? "reconnecting…" : wsStatus}
          </span>
        </div>
      </header>
      {state.lastError ? (
        <div class="banner banner-error">{state.lastError}</div>
      ) : null}
      <MessageList turns={state.turns} />
      <Composer
        onSend={onSend}
        onInterrupt={onInterrupt}
        busy={busy}
        disabled={!connected}
      />
    </div>
  );
}
