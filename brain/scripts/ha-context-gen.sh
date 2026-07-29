#!/usr/bin/with-contenv bashio

# ha-context-gen - Generate CLAUDE.md with Home Assistant system context
# This gives Claude Code immediate knowledge of your HA installation

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
HA_API="http://supervisor/core/api"
SUPERVISOR_API="http://supervisor"
OUTPUT_FILE="/config/CLAUDE.md"

# API helper
api_get() {
    local endpoint="$1"
    local url

    if [[ "$endpoint" == /api/* ]]; then
        url="${HA_API}${endpoint#/api}"
    else
        url="${SUPERVISOR_API}${endpoint}"
    fi

    curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "$url" 2>/dev/null
}

generate_context() {
    bashio::log.info "Generating Home Assistant context for Claude Code..."

    # Gather system information
    local ha_config
    ha_config=$(api_get "/api/config" 2>/dev/null || echo '{}')

    local ha_version
    ha_version=$(echo "$ha_config" | jq -r '.version // "(lookup failed)"')

    local ha_name
    ha_name=$(echo "$ha_config" | jq -r '.location_name // "(lookup failed)"')

    local ha_timezone
    ha_timezone=$(echo "$ha_config" | jq -r '.time_zone // "(lookup failed)"')

    local ha_unit_system
    ha_unit_system=$(echo "$ha_config" | jq -r '.unit_system.temperature // "(lookup failed)"')

    local ha_elevation
    ha_elevation=$(echo "$ha_config" | jq -r '.elevation // "(lookup failed)"')

    # Get components/integrations
    local components
    components=$(echo "$ha_config" | jq -r '.components[]? // empty' 2>/dev/null | sort)

    # Get all entity states
    local all_states
    all_states=$(api_get "/api/states" 2>/dev/null || echo '[]')

    # Count entities by domain
    local domain_counts
    domain_counts=$(echo "$all_states" | jq -r '
        [.[].entity_id] |
        map(split(".")[0]) |
        group_by(.) |
        map({domain: .[0], count: length}) |
        sort_by(-.count) |
        .[] |
        "  - \(.domain): \(.count) entities"
    ' 2>/dev/null || echo "  - Unable to retrieve entity counts")

    # Get areas (via template rendering)
    local areas
    areas=$(api_get "/api/states" 2>/dev/null | jq -r '
        [.[].attributes.friendly_name // empty] | unique | length
    ' 2>/dev/null || echo "unknown")

    # Get automations summary
    local automations
    automations=$(echo "$all_states" | jq -r '
        [.[] | select(.entity_id | startswith("automation."))] |
        map({
            id: .entity_id,
            name: (.attributes.friendly_name // .entity_id),
            state: .state,
            last_triggered: (.attributes.last_triggered // "never")
        })
    ' 2>/dev/null || echo '[]')

    local automation_count
    automation_count=$(echo "$automations" | jq 'length' 2>/dev/null || echo "0")

    local automation_list
    automation_list=$(echo "$automations" | jq -r '
        .[:20] | .[] | "  - \(.name) [\(.state)] (last: \(.last_triggered))"
    ' 2>/dev/null || echo "  - Unable to retrieve automations")

    # Get scripts summary
    local script_count
    script_count=$(echo "$all_states" | jq '[.[] | select(.entity_id | startswith("script."))] | length' 2>/dev/null || echo "0")

    # Get scenes summary
    local scene_count
    scene_count=$(echo "$all_states" | jq '[.[] | select(.entity_id | startswith("scene."))] | length' 2>/dev/null || echo "0")

    # Get input helpers
    local input_boolean_count
    input_boolean_count=$(echo "$all_states" | jq '[.[] | select(.entity_id | startswith("input_boolean."))] | length' 2>/dev/null || echo "0")

    local input_number_count
    input_number_count=$(echo "$all_states" | jq '[.[] | select(.entity_id | startswith("input_number."))] | length' 2>/dev/null || echo "0")

    local input_select_count
    input_select_count=$(echo "$all_states" | jq '[.[] | select(.entity_id | startswith("input_select."))] | length' 2>/dev/null || echo "0")

    # Get supervisor info.
    # NOTE on fallbacks: every jq `// "..."` default below uses a visible
    # "(lookup failed)" marker, never a plausible-looking value. A context
    # generator that silently degrades produces permanently wrong context,
    # because wrong context is indistinguishable from true context.
    local supervisor_info
    supervisor_info=$(api_get "/core/info" 2>/dev/null || echo '{}')

    # operating_system lives on /host/info, NOT /core/info — reading it
    # from the wrong endpoint is why CLAUDE.md said "OS: unknown" forever.
    local host_info
    host_info=$(api_get "/host/info" 2>/dev/null || echo '{}')

    local ha_os
    ha_os=$(echo "$host_info" | jq -r '.data.operating_system // "(lookup failed)"')

    local ha_machine
    ha_machine=$(echo "$supervisor_info" | jq -r '.data.machine // "(lookup failed)"')

    # Get installed add-ons
    local addons_info
    addons_info=$(api_get "/addons" 2>/dev/null || echo '{}')

    local addon_list
    addon_list=$(echo "$addons_info" | jq -r '
        .data.addons[]? |
        select(.installed == true or .state == "started") |
        "  - \(.name) v\(.version) [\(.state)]"
    ' 2>/dev/null || echo "  - Unable to retrieve add-on list")

    # Get important integration info
    local integration_list
    integration_list=$(echo "$components" | head -50 | while read -r comp; do
        echo "  - $comp"
    done)

    # Dashboard inventory (url_path/title/mode) via the MCP server module —
    # makes the correct update target obvious without a discovery
    # round-trip. Best-effort: emits a visible marker on failure.
    local dashboard_list
    dashboard_list=$(python3 - 2>/dev/null <<'PYEOF'
import sys
sys.path.insert(0, "/opt/ha-mcp-server")
try:
    from ha_mcp_server import list_dashboards
    result = list_dashboards()
    if not isinstance(result, dict) or "error" in result:
        raise RuntimeError(result)
    rows = ["  - url_path: (omit) — the default dashboard (auto-generated "
            "until first saved; saving takes manual control of it)"]
    for d in result.get("dashboards", []):
        rows.append("  - url_path: {} — {} (mode: {})".format(
            d.get("url_path"), d.get("title", "?"), d.get("mode", "?")))
    print("\n".join(rows))
except Exception:
    sys.exit(1)
PYEOF
) || dashboard_list="  - (lookup failed — use the list_dashboards MCP tool)"

    # Preserve user-authored notes between the marker comments across
    # regenerations — everything else in this file is overwritten.
    local user_notes=""
    if [ -f "$OUTPUT_FILE" ]; then
        user_notes=$(sed -n '/<!-- bruh:user-notes:start -->/,/<!-- bruh:user-notes:end -->/p' "$OUTPUT_FILE" 2>/dev/null | sed '1d;$d')
    fi
    if [ -z "$user_notes" ]; then
        user_notes="<!-- Anything inside this marked section survives regeneration.
     Add house rules, conventions, or standing instructions for Claude here. -->"
    fi

    # Learned home knowledge — maintained by `brain memory` and the consolidator.
    local memory_section=""
    local memory_file="/config/.brain/memory/memory.md"
    if [ -s "$memory_file" ]; then
        memory_section="## Learned Home Knowledge

> Maintained automatically by \`brain memory\` and the consolidator
> (facts from voice conversations, services, and other BRUH add-ons).
> View with \`brain memory list\`, edit with \`brain memory edit\`.

$(head -c 4096 "$memory_file")
"
    fi

    # Generate the CLAUDE.md file
    cat > "$OUTPUT_FILE" << CLAUDEMD
# CLAUDE.md - Auto-generated Home Assistant Context

> This file is auto-generated by BRain on startup.
> It provides Claude Code with context about your Home Assistant installation.
> Last updated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

## User Notes

<!-- bruh:user-notes:start -->
${user_notes}
<!-- bruh:user-notes:end -->

## System Overview

- **Home name**: ${ha_name}
- **HA version**: ${ha_version}
- **OS**: ${ha_os}
- **Machine**: ${ha_machine}
- **Timezone**: ${ha_timezone}
- **Unit system**: ${ha_unit_system}
- **Elevation**: ${ha_elevation}m

## Entity Summary

${domain_counts}

## Automations (${automation_count} total)

${automation_list}
$(if [ "$automation_count" -gt 20 ]; then echo "  ... and $((automation_count - 20)) more"; fi)

## Scripts: ${script_count} | Scenes: ${scene_count}

## Input Helpers

- Input booleans: ${input_boolean_count}
- Input numbers: ${input_number_count}
- Input selects: ${input_select_count}

## Installed Add-ons

${addon_list}

## Active Integrations (first 50)

${integration_list}

## Dashboards

${dashboard_list}

Dashboard rules:
- **Always pass \`url_path\`** (from \`list_dashboards\` or the inventory
  above) when reading or updating a dashboard. Only omit it when you truly
  mean the default dashboard, and confirm with the user first — saving to a
  never-saved default takes manual control of it permanently.
- **Never use raw Lovelace transport**: do not call \`lovelace/config\`,
  \`lovelace/config/save\`, or \`lovelace/config/delete\` over WebSocket or
  REST. Use \`get_dashboard\` (MCP) to read and \`brain.update_dashboard\`
  / \`brain.restore_dashboard\` to write — they validate and back up.
- **Never verify via \`.storage\`**: HA's delayed saves make
  \`/config/.storage\` stale for ~10s after a write. Verify a dashboard edit
  with \`get_dashboard\`, never by reading \`.storage\` content or mtimes.

${memory_section}

## Available Directories

- \`/config/\` - Home Assistant configuration (read-write)
$([ -d "/share" ] && echo '- `/share/` - Shared storage accessible by other add-ons (read-write)')
$([ -d "/media" ] && echo '- `/media/` - Media files for images, audio, video (read-write)')
$([ -d "/backup" ] && echo '- `/backup/` - Backup snapshots (read-only)')
$([ -d "/addon_configs" ] && echo '- `/addon_configs/` - Add-on config directories (read-write)')
$([ -n "${ADDONS_DIR:-}" ] && echo '- `/addons/` - Installed add-on files (read-write)')
$(
    # List any additional user-configured directories
    for env_var in $(env | grep '^ADDITIONAL_DIR_' | sort); do
        dir_path="${env_var#*=}"
        if [ -d "$dir_path" ]; then
            echo "- \\\`${dir_path}\\\` - User-configured directory (read-write)"
        fi
    done
)

## File Structure

The Home Assistant configuration lives in \`/config/\`. Key files:
- \`/config/configuration.yaml\` - Main configuration
- \`/config/automations.yaml\` - Automations
- \`/config/scripts.yaml\` - Scripts
- \`/config/scenes.yaml\` - Scenes
- \`/config/secrets.yaml\` - Secrets (DO NOT read or modify)
- \`/config/customize.yaml\` - Entity customizations

## CLI Tools

You have access to these CLI tools:
- \`ha-reload <target>\` - Reload HA config (automations, scripts, scenes, groups, core, all)
- \`ha-log [core|supervisor|addons]\` - View HA logs in real-time
- \`ha-backup [commit-message]\` - Manually trigger a config backup
- \`ha-context-gen\` - Regenerate this context file
- \`ha-yaml-check\` - Validate YAML configuration
- \`ha-addon <action> <slug>\` - Manage add-ons (list, info, restart, stop, start, logs, options)
- \`ha-entity <action> <id>\` - Get/set entity states (get, set, list, search)
- \`ha-service call <domain>.<service>\` - Call HA services
- \`ha-notify "msg"\` - Send notifications (persistent or mobile push)
- \`ha-share <action>\` - Cross-addon file sync via /share (push, pull, ls)
- \`brain memory <action>\` - Home memory (add, list, edit, forget, log, undo, hypotheses, confirm, reject)
- \`ha-share-login\` - Share your Claude login with other BRUH add-ons (--status, --revoke)
- \`ha-selftest\` - End-to-end diagnostic (MCP, auth, listeners, CLI smoke tests)
- \`persist-install apk|pip <packages>\` - Install persistent packages

## MCP Server

The Home Assistant MCP server is active. You can use it to:
- Get entity states in real-time
- Call HA services (turn on/off lights, trigger automations, etc.)
- List registries with \`get_registry\` (areas, floors, labels, devices, entities, integrations)
- View automation traces for debugging
- Check error logs
- Render Jinja2 templates
- Reload configurations after YAML edits

## Registry Management — BRUH Power Tools

For anything that would normally be clicked through Settings (or worse,
edited in \`/config/.storage\`), use the \`brain.*\` admin services.
They are validated, admin-gated, and go through HA's own registry APIs —
**always prefer them over editing \`.storage\` files, which must never be
modified by hand.**

Workflow: look up ids with the \`get_registry\` MCP tool, then call the
service with \`call_service\` (domain \`brain\`). Services marked (R)
return response data — pass \`return_response: true\` for those.

- Areas: \`create_area\` (R), \`delete_area\`, \`rename_area\`, \`set_area_aliases\`,
  \`add_device_to_area\`, \`remove_device_from_area\`, \`add_entity_to_area\`, \`remove_entity_from_area\`
- Floors: \`create_floor\` (R), \`delete_floor\`, \`rename_floor\`, \`add_area_to_floor\`, \`remove_area_from_floor\`
- Labels: \`create_label\` (R), \`delete_label\`, \`add_label\`, \`remove_label\`
  (\`add_label\`/\`remove_label\` take entity_id, device_id, and/or area_id lists)
- Entities: \`rename_entity\`, \`change_entity_id\`, \`enable_entity\`, \`disable_entity\`,
  \`hide_entity\`, \`unhide_entity\`, \`set_entity_aliases\` (voice names),
  \`set_entity_icon\` (omit icon to clear), \`delete_orphaned_entities\` (R, dry-run by
  default; optional entity_id list scopes the cleanup — always dry-run first,
  then delete with the reviewed entity_id list, never blind-delete all)
- Helpers: \`create_helper\` (R; helper_type ∈ input_boolean/input_number/
  input_select/input_text/input_datetime/counter/timer/schedule, plus an
  \`options\` object with the type's own fields e.g. min/max, options list,
  duration), \`delete_helper\` (UI-created helpers only)
- Devices: \`rename_device\`, \`enable_device\`, \`disable_device\`
- Integrations: \`enable_integration\`, \`disable_integration\`, \`reload_integration\` (config_entry_id)
- Zones: \`create_zone\`, \`update_zone\`, \`delete_zone\`
- Persons: \`create_person\` (R), \`delete_person\`,
  \`add_device_tracker_to_person\`, \`remove_device_tracker_from_person\`
- Blueprints: \`import_blueprint\` (R) — import from forum/GitHub/Gist URL
- Statistics: \`import_statistics\` (R) — backfill/repair long-term statistics
  (entity id → recorder stats; \`domain:object_id\` → external stats; hourly
  \`start\` timestamps; \`has_sum\` totals need \`sum\`, \`has_mean\` needs mean/min/max).
  DRY RUN BY DEFAULT — it reports the affected window and existing rows;
  only pass \`dry_run: false\` after reviewing, since imports overwrite
  history irreversibly
- Users: \`create_user\` (R; optional username+password together, pw ≥ 8 chars),
  \`delete_user\`, \`enable_user\`, \`disable_user\` (user_id from \`get_registry\`
  users; owner/system accounts can never be deleted or disabled)
- Diagnostics: \`find_orphaned_references\` (R) — automations/scripts/scenes
  that reference unknown entities; \`create_issue: true\` raises a repair
- Dashboards: \`update_dashboard\` (R), \`restore_dashboard\` (R) — edit a
  Lovelace dashboard by fetching its JSON with the \`get_dashboard\` MCP tool
  (\`list_dashboards\` enumerates them), modifying it, and saving back.
  \`url_path\` is REQUIRED (use the literal \`"default"\` for the default
  dashboard); pass \`view_index\` to replace one view instead of the whole
  config; \`dry_run: true\` previews the resolved target first; saving onto
  a never-saved dashboard needs \`take_control: true\`. The old config is
  backed up automatically, \`restore_dashboard\` undoes a bad edit, and
  \`reset_dashboard_config\` (R) reverts a dashboard to auto-generated —
  never use raw \`lovelace/config\` websocket commands for any of this. Also
  \`create_dashboard\` (R; url_path needs a hyphen), \`delete_dashboard\` (R,
  backs config up first), and \`add_dashboard_resource\` (R) /
  \`remove_dashboard_resource\` for custom-card modules.
  Never edit .storage/lovelace files.
- Repairs: \`create_repair_issue\` (R), \`remove_repair_issue\` — surface issues that
  need the user's attention in Settings > System > Repairs

Examples:
- Rename an entity: \`call_service\` domain=\`brain\` service=\`rename_entity\`
  data=\`{"entity_id": ["light.shelly_abc"], "name": "Kitchen Ceiling"}\`
- Create an area and capture its id: service=\`create_area\`
  data=\`{"name": "Guest Room", "floor_id": "upstairs"}\` with \`return_response: true\`
- Check for dead registry entries: service=\`delete_orphaned_entities\`
  data=\`{}\` with \`return_response: true\` (only deletes with \`{"dry_run": false}\`)

Cautions: \`delete_area\`/\`delete_floor\`/\`delete_label\` unassign, they don't
delete members. All destructive services accept \`dry_run: true\` (with
\`return_response\`) to preview the blast radius first — use it before any
non-trivial delete/disable. \`change_entity_id\` does NOT rewrite
automations/dashboards that reference the old id — its response lists the
affected automations/scripts/scenes; update them, then run
\`find_orphaned_references\`. Confirm with the user before disabling
devices/integrations/users or deleting anything non-trivial. For a
safe-mode restart use core \`homeassistant.restart\` with \`safe_mode: true\`.

## Important Notes

- **Always run \`ha-reload automations\` after editing automations.yaml**
- **Always run \`ha-reload scripts\` after editing scripts.yaml**
- **Never modify secrets.yaml directly**
- **YAML edits are auto-backed up via git** (if auto_backup is enabled)
- **Test templates** using the \`render_template\` MCP tool before using them in automations
CLAUDEMD

    bashio::log.info "Context file generated: $OUTPUT_FILE"
}

# Run generation
generate_context
