# Feature Improvement Plan for BRUH Claude Terminal

## High-Impact Feature Additions

### 1. Conversation Memory / Multi-Turn Context
**Current gap:** Each Assist conversation turn is a completely independent one-shot request. The shell-side listener (`assist-listener.sh`) has no session or memory between turns.

**Proposed solution:**
- Maintain a per-conversation context file in `/config/.bruh_claude/sessions/{conversation_id}.json`
- Append each turn's user message + Claude response to the session file
- Pass the conversation history as context to Claude via `--resume` or by piping a structured prompt
- Add a configurable `max_conversation_turns` setting (default: 10) to limit context growth
- Auto-expire sessions after configurable idle timeout

**Impact:** Transforms Assist integration from a novelty into a genuinely useful conversational interface.

### 2. Stale File Cleanup / Orphan Request Garbage Collection
**Current gap:** If a request times out, the request file stays in the `requests/` directory forever. The add-on may eventually process it, writing a response that is never read. Files accumulate indefinitely.

**Proposed solution:**
- Add a periodic cleanup task (every 5 minutes) in both listeners
- Remove any `.json` files older than `2 * timeout` seconds
- Remove any `.json.tmp` files older than 60 seconds
- Add a `cleanup_stale_files()` function to `bridge.py` that runs on startup

**Impact:** Prevents disk space issues and stale request processing in long-running installations.

### 3. Task Status Tracking & Progress Events
**Current gap:** Tasks always report `"status": "completed"` even when `claude -p` fails. There's no way to track in-progress tasks.

**Proposed solution:**
- Write a `{task_id}.status.json` file with states: `queued`, `running`, `completed`, `failed`
- Set status to `running` before invoking Claude, `completed`/`failed` after
- Include exit code and stderr in the result on failure
- Fire distinct HA events: `bruh_claude_task_started`, `bruh_claude_task_completed`, `bruh_claude_task_failed`
- Add a `bruh_claude.get_task_status` service to query status

**Impact:** Enables HA automations to react to task lifecycle (e.g., notify on failure, retry logic).

### 4. Concurrency Limiter for Listener Processes
**Current gap:** Both listeners spawn unlimited background `claude -p` processes. A flood of requests could exhaust system resources.

**Proposed solution:**
- Implement a semaphore using a simple counter file or `flock`-based approach
- Default max concurrent tasks: 3 for assist, 2 for automation
- Queue excess requests with a configurable max queue depth
- Add `max_concurrent_assist` and `max_concurrent_tasks` config options

**Impact:** Prevents resource exhaustion on low-memory HA devices (RPi).

### 5. Notification Routing Fix + Flexible Notification
**Current gap:** The automation listener always calls `notify.persistent_notification` regardless of the `notify_entity` setting. The entity_id field is meaningless for persistent_notification.

**Proposed solution (beyond the bug fix):**
- Parse `notify_entity` to extract domain/service (e.g., `notify.mobile_app_phone` → service `notify/mobile_app_phone`)
- Support multiple notification targets (comma-separated)
- Add `notify_title` field for customizable notification titles
- Support for HA 2024+ `notify.send_message` action pattern

**Impact:** Makes task completion notifications actually work on mobile devices.

### 6. Health Status Entity
**Current gap:** No way to see from within HA whether the Claude Terminal add-on is healthy and responsive.

**Proposed solution:**
- Add a `binary_sensor.bruh_claude_status` entity to the custom integration
- The bridge periodically writes a heartbeat file, the entity polls it
- Show attributes: `last_heartbeat`, `active_tasks`, `active_conversations`, `uptime`
- Entity goes `unavailable` if heartbeat is stale (> 60 seconds)

**Impact:** Enables automations to check if Claude is available before sending requests.

### 7. Entity Dashboard / Device Integration
**Current gap:** The conversation entity has no `device_info`, so it doesn't group under a device in the HA UI.

**Proposed solution:**
- Add `_attr_device_info` to `BruhClaudeConversationEntity`
- Create a "BRUH Claude Terminal" device with manufacturer, model, SW version
- Group all entities (conversation, status sensor, future entities) under this device
- Pull version from manifest.json dynamically

**Impact:** Better UX in the HA UI — everything grouped under one device.

### 8. MCP Server Tool Expansion
**Current gap:** The MCP server provides basic entity/service/log access but lacks several useful capabilities.

**Proposed additions:**
- `get_areas()` — list all areas and their entities
- `get_automations_yaml()` — read raw automation YAML for editing
- `get_dashboard_config(dashboard_id)` — read Lovelace dashboard config
- `search_entities(query)` — fuzzy search entities by name/ID
- `get_entity_history(entity_id, hours)` — historical state data
- `get_addon_info(slug)` — info about installed add-ons
- `restart_addon(slug)` — restart a specific add-on

**Impact:** Dramatically increases Claude's ability to understand and modify the HA installation.

### 9. Webhook-Based IPC (Alternative to File Polling)
**Current gap:** File-based IPC with polling has inherent latency (0.5-5 seconds), race conditions, and orphan file issues.

**Proposed solution:**
- Add an optional lightweight HTTP server in the add-on (e.g., using Python's built-in `http.server`)
- The HA integration POSTs requests directly to the add-on's HTTP endpoint
- The add-on responds synchronously (for short requests) or returns a task ID for async work
- Keep file-based IPC as fallback for compatibility
- Add `ipc_mode: "webhook" | "file"` config option

**Impact:** Sub-second response times, eliminates all file-based race conditions, simpler architecture.

### 10. Backup Pruning & Rotation
**Current gap:** The auto-backup watcher commits every N minutes indefinitely. Git history grows without bound.

**Proposed solution:**
- Add `max_backup_count` config option (default: 100)
- After reaching the limit, squash older commits (keep last N)
- Add `ha-backup prune [keep-count]` CLI command
- Add `backup_retention_days` config option to auto-prune old backups
- Show backup statistics in `ha-backup history` (total size, commit count)

**Impact:** Prevents unbounded disk growth in long-running installations.

## Priority Order (Recommended Implementation Sequence)

1. **Notification Routing Fix** (#5) — Bug fix with high user impact
2. **Task Status Tracking** (#3) — Foundation for reliable automation integration
3. **Conversation Memory** (#1) — Highest user-visible feature improvement
4. **Stale File Cleanup** (#2) — Important for reliability
5. **Concurrency Limiter** (#4) — Important for RPi users
6. **Health Status Entity** (#6) — Useful diagnostic tool
7. **Device Integration** (#7) — Quick UX win
8. **MCP Server Expansion** (#8) — Incremental capability gains
9. **Backup Pruning** (#10) — Quality of life
10. **Webhook IPC** (#9) — Largest architectural change, do last
