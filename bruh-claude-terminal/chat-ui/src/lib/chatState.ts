// In-memory chat state. A flat list of Turns is the entire model; everything
// else (streaming buffer, tool-use linkage) is collapsed into a Turn so the
// renderer can map 1:1 over Turns and not worry about cross-turn refs.
//
// Design choice: ignore the server-replayed `user` events. We render user
// turns optimistically when the user hits send, because that's the latency
// we care about. Replayed user events from --replay-user-messages would
// cause double-render; if a future feature needs them we can detect dupes
// by content + monotonic counter.

import type { WireEvent } from "./events";

export type UIBlock =
  | { kind: "text"; text: string }
  | {
      kind: "tool_use";
      id: string;
      name: string;
      input: Record<string, unknown>;
      result?: { content: string; isError: boolean };
    }
  | { kind: "note"; text: string };

export interface Turn {
  id: string;
  role: "user" | "assistant";
  blocks: UIBlock[];
  status: "streaming" | "done";
  ts: number;
}

export interface ChatState {
  turns: Turn[];
  sessionId: string | null;
  permissionMode: string | null;
  cwd: string | null;
  status: "idle" | "thinking" | "error";
  lastError: string | null;
}

export function initialState(): ChatState {
  return {
    turns: [],
    sessionId: null,
    permissionMode: null,
    cwd: null,
    status: "idle",
    lastError: null,
  };
}

let _turnSeq = 0;
function newTurnId(): string {
  _turnSeq += 1;
  return `t${Date.now().toString(36)}-${_turnSeq}`;
}

export function appendUserTurn(state: ChatState, text: string): ChatState {
  const turn: Turn = {
    id: newTurnId(),
    role: "user",
    blocks: [{ kind: "text", text }],
    status: "done",
    ts: Date.now(),
  };
  return { ...state, turns: [...state.turns, turn], status: "thinking" };
}

/** Find or create the currently-streaming assistant turn. */
function withStreamingAssistant(
  state: ChatState,
  mut: (turn: Turn) => Turn,
): ChatState {
  const last = state.turns[state.turns.length - 1];
  if (last && last.role === "assistant" && last.status === "streaming") {
    const updated = mut(last);
    return { ...state, turns: [...state.turns.slice(0, -1), updated] };
  }
  const fresh: Turn = {
    id: newTurnId(),
    role: "assistant",
    blocks: [],
    status: "streaming",
    ts: Date.now(),
  };
  const updated = mut(fresh);
  return { ...state, turns: [...state.turns, updated] };
}

function appendTextDelta(turn: Turn, text: string): Turn {
  const last = turn.blocks[turn.blocks.length - 1];
  if (last && last.kind === "text") {
    const updated = { ...last, text: last.text + text };
    return { ...turn, blocks: [...turn.blocks.slice(0, -1), updated] };
  }
  return { ...turn, blocks: [...turn.blocks, { kind: "text", text }] };
}

function replaceBlocks(turn: Turn, blocks: UIBlock[]): Turn {
  return { ...turn, blocks };
}

function attachToolResult(
  turns: Turn[],
  toolUseId: string,
  result: { content: string; isError: boolean },
): Turn[] {
  // Walk backwards — tool results almost always belong to the most recent
  // assistant turn — but we scan all assistant turns so out-of-order
  // results from concurrent tool calls still land correctly.
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i];
    if (t.role !== "assistant") continue;
    const idx = t.blocks.findIndex(
      (b) => b.kind === "tool_use" && b.id === toolUseId,
    );
    if (idx >= 0) {
      const updated: UIBlock = { ...(t.blocks[idx] as Extract<UIBlock, { kind: "tool_use" }>), result };
      const blocks = [...t.blocks];
      blocks[idx] = updated;
      const next = [...turns];
      next[i] = { ...t, blocks };
      return next;
    }
  }
  return turns;
}

function normalizeToolResultContent(
  raw: string | Array<{ type: string; text?: string }>,
): string {
  if (typeof raw === "string") return raw;
  if (!Array.isArray(raw)) return JSON.stringify(raw);
  return raw
    .map((b) => (b.type === "text" && b.text ? b.text : JSON.stringify(b)))
    .join("\n");
}

export function reduce(state: ChatState, ev: WireEvent): ChatState {
  switch (ev.type) {
    case "session_ready": {
      return {
        ...state,
        sessionId: ev.session_id,
        cwd: ev.cwd,
        permissionMode: ev.permission_mode,
        status: "idle",
        lastError: null,
      };
    }

    case "session_closed": {
      const note = ev.stderr_tail && ev.stderr_tail.length
        ? `Session ended. Last stderr:\n${ev.stderr_tail.join("\n")}`
        : "Session ended.";
      return {
        ...state,
        status: "idle",
        turns: [
          ...state.turns,
          {
            id: newTurnId(),
            role: "assistant",
            blocks: [{ kind: "note", text: note }],
            status: "done",
            ts: Date.now(),
          },
        ],
      };
    }

    case "server_error": {
      return { ...state, status: "error", lastError: ev.error };
    }

    case "system": {
      // System init / metadata; just stash, don't render.
      return state;
    }

    case "user": {
      // Server-replayed user message. We've already rendered optimistically;
      // skip to avoid duplicates.
      return state;
    }

    case "stream_event": {
      const sub = ev.event?.type;
      if (sub === "content_block_delta") {
        const delta = ev.event.delta;
        if (delta?.type === "text_delta" && delta.text) {
          return withStreamingAssistant(state, (t) => appendTextDelta(t, delta.text!));
        }
        return state;
      }
      if (sub === "message_start") {
        // Ensure we have an assistant turn ready; explicit start matters
        // because the first delta might be a tool_use, not text.
        return withStreamingAssistant(state, (t) => t);
      }
      return state;
    }

    case "assistant": {
      // Canonical end-of-turn message. Replace the streaming turn's blocks
      // so the final state matches what's persisted to the session JSONL.
      const wireBlocks = ev.message?.content || [];
      const uiBlocks: UIBlock[] = [];
      for (const b of wireBlocks) {
        if (b.type === "text") {
          uiBlocks.push({ kind: "text", text: b.text });
        } else if (b.type === "tool_use") {
          uiBlocks.push({
            kind: "tool_use",
            id: b.id,
            name: b.name,
            input: b.input,
          });
        }
      }
      return withStreamingAssistant(state, (t) =>
        replaceBlocks(t, uiBlocks),
      );
    }

    case "tool_result": {
      const toolUseId = (ev as { tool_use_id?: string }).tool_use_id;
      const rawContent = (ev as { content?: string | Array<{ type: string; text?: string }> }).content;
      const isError = Boolean((ev as { is_error?: boolean }).is_error);
      if (!toolUseId) return state;
      const turns = attachToolResult(state.turns, toolUseId, {
        content: normalizeToolResultContent(rawContent ?? ""),
        isError,
      });
      return { ...state, turns };
    }

    case "result": {
      // Turn complete. Finalize whichever turn is still streaming.
      const last = state.turns[state.turns.length - 1];
      if (last && last.role === "assistant" && last.status === "streaming") {
        const updated: Turn = { ...last, status: "done" };
        return {
          ...state,
          turns: [...state.turns.slice(0, -1), updated],
          status: "idle",
        };
      }
      return { ...state, status: "idle" };
    }

    default:
      return state;
  }
}
