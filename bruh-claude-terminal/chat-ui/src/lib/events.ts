// Types for the NDJSON wire format claude-code emits over stream-json.
// Shapes are inferred from the headless SDK docs and verified by inspecting
// real stdout under --output-format stream-json --include-partial-messages.
// Anything we don't understand falls into `RawEvent` so the UI can still log it.

export interface SessionReady {
  type: "session_ready";
  session_id: string;
  cwd: string;
  permission_mode: string;
}

export interface SessionClosed {
  type: "session_closed";
  stderr_tail?: string[];
}

export interface ServerError {
  type: "server_error";
  error: string;
}

export interface SystemEvent {
  type: "system";
  subtype?: string;
  session_id?: string;
  model?: string;
  cwd?: string;
  tools?: string[];
  [k: string]: unknown;
}

export interface TextBlock {
  type: "text";
  text: string;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string | Array<{ type: string; text?: string }>;
  is_error?: boolean;
}

export type ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock;

export interface AssistantEvent {
  type: "assistant";
  message: {
    id?: string;
    role: "assistant";
    content: ContentBlock[];
    model?: string;
    stop_reason?: string | null;
    usage?: Record<string, number>;
  };
}

export interface UserEvent {
  type: "user";
  message: {
    role: "user";
    content: ContentBlock[] | string;
  };
}

export interface StreamEvent {
  type: "stream_event";
  event: {
    type: string;
    index?: number;
    delta?: { type: string; text?: string };
    content_block?: ContentBlock;
    [k: string]: unknown;
  };
}

export interface ResultEvent {
  type: "result";
  subtype?: string;
  duration_ms?: number;
  is_error?: boolean;
  result?: string;
  usage?: Record<string, number>;
  total_cost_usd?: number;
}

export interface RawEvent {
  type: "raw" | string;
  [k: string]: unknown;
}

export type WireEvent =
  | SessionReady
  | SessionClosed
  | ServerError
  | SystemEvent
  | AssistantEvent
  | UserEvent
  | StreamEvent
  | ResultEvent
  | RawEvent;

// Client → server message shapes (what we send into the WS).
export interface ClientUserMessage {
  type: "user";
  content: string;
}

export interface ClientInterrupt {
  type: "interrupt";
}

export interface ClientInit {
  type: "init";
  session_id?: string;
  cwd?: string;
  model?: string;
  permission_mode?: "default" | "acceptEdits" | "plan" | "bypassPermissions";
}

export type ClientMessage = ClientInit | ClientUserMessage | ClientInterrupt;
