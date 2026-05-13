import { useState } from "preact/hooks";
import type { UIBlock } from "~/lib/chatState";

type ToolUse = Extract<UIBlock, { kind: "tool_use" }>;

function summarizeInput(name: string, input: Record<string, unknown>): string {
  // Heuristic one-line preview keyed off the most common Claude Code tools.
  // Falls back to "{n} fields" for unknown tools so users still get a hint.
  if (name === "Bash" && typeof input.command === "string") {
    return input.command;
  }
  if (name === "Read" && typeof input.file_path === "string") {
    return input.file_path;
  }
  if (
    (name === "Edit" || name === "Write" || name === "NotebookEdit") &&
    typeof input.file_path === "string"
  ) {
    return input.file_path;
  }
  if (name === "Grep" && typeof input.pattern === "string") {
    return input.pattern;
  }
  if (name === "Glob" && typeof input.pattern === "string") {
    return input.pattern;
  }
  if (name === "WebFetch" && typeof input.url === "string") {
    return input.url;
  }
  if (name === "WebSearch" && typeof input.query === "string") {
    return input.query;
  }
  const keys = Object.keys(input);
  return keys.length ? `${keys.length} fields` : "(no input)";
}

export function ToolBlock({ block }: { block: ToolUse }) {
  const [expanded, setExpanded] = useState(false);
  const summary = summarizeInput(block.name, block.input);
  const hasResult = !!block.result;
  const isError = block.result?.isError ?? false;

  return (
    <div class={`tool-block${isError ? " tool-error" : ""}`}>
      <button
        class="tool-header"
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
      >
        <span class="tool-name">{block.name}</span>
        <span class="tool-summary">{summary}</span>
        <span class="tool-status">
          {hasResult ? (isError ? "error" : "done") : "running…"}
        </span>
        <span class="tool-caret">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded ? (
        <div class="tool-body">
          <div class="tool-input">
            <div class="tool-label">Input</div>
            <pre>{JSON.stringify(block.input, null, 2)}</pre>
          </div>
          {hasResult ? (
            <div class="tool-result">
              <div class="tool-label">{isError ? "Error" : "Result"}</div>
              <pre>{block.result!.content}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
