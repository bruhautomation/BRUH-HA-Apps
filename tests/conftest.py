"""Run the suite as if no Claude CLI is installed, which is what CI is.

Several routes start a background sign-in check (`validate_auth`), and a
test that drives one without stubbing the engine reaches `_claude_argv`.
On CI's runners there is no `claude` on PATH, so the spawn fails at once.
In a Claude Code cloud session there is one (`/opt/node22/bin/claude`), so
the same test started a real CLI and the next test that needed a run-queue
seat waited on it: `test_memory_cleanup`'s presses took 87s and 23s instead
of a third of a second, and some runs hung outright.

It is set before EVERY test rather than once at import, because the chat
tests set `BRAIN_CLAUDE_BIN` to their own fake and pop it in teardown,
which took a once-only default away for every test after them. A test that
wants a CLI still sets the variable itself; this only fills it when empty.
"""

import os
from pathlib import Path

import warnings

import pytest

NO_CLI = "/nonexistent/claude-not-installed-in-tests"


@pytest.fixture(autouse=True)
def _no_real_claude_cli():
    os.environ.setdefault("BRAIN_CLAUDE_BIN", NO_CLI)
    yield


# ---------------------------------------------------------------------------
# The `slow` mark, applied here rather than in each file
# ---------------------------------------------------------------------------
#
# `-m "not slow"` is the fast local run, and a mark nothing carries is a
# filter that filters nothing. These are the tests measured at half a second
# or more under four xdist workers (2026-10-08) — nearly all of them spawn a
# subprocess, stand up a real server or hold a lock, which is the waiting
# that makes the serial suite six minutes of wall clock for two of CPU; the
# rest walk the whole source tree. Listed here, by node id, rather than as
# decorators scattered over sixty files, so one place says what the fast run
# leaves out, and a file another change is editing need not be touched to
# mark it. An entry is a file, a class or a single test; a class or file
# where at least half the tests are slow is named whole.
#
# A renamed test would drop out of this list silently, so
# tests/test_slow_marks.py holds every entry to a file, class and function
# that exists. Skipping these is a way to iterate, never a pass: CI runs
# them.
SLOW = (
    "test_ai_task_and_llm_api.py::TestTheAITaskEntity::test_an_answer_that_does_not_fit_is_an_error_never_data",
    "test_assist_worker_pool.py::test_hang_produces_timeout_message",
    "test_atomic_write.py::TestConcurrency",
    "test_brain_addon.py::TestCredentialBackupRestore::test_the_shell_and_the_panel_answer_the_same_question_alike",
    "test_brain_addon.py::TestEditJournal::test_the_size_cap_runs_whenever_the_journal_is_on",
    "test_brain_addon.py::TestTurnBudgets::test_every_study_session_is_one_journal_row",
    "test_brain_findings_watcher.py::TestTheWholeListIsMirrored::test_a_full_store_fits_the_reader",
    "test_bright_claude_director.py::TestNobodyListeningIsItsOwnFailure::test_a_claimed_task_that_never_answers_blames_the_right_thing",
    "test_bright_director_check.py::TestTheLinksAreWalkedInOrder::test_claimed_and_silent_is_a_different_link_than_unclaimed",
    "test_bright_live.py",
    "test_bright_media_source.py::TestResolvingIsNotServing",
    "test_bright_panel_routes.py::TestTheBriefIsReadable::test_reading_the_brief_runs_nothing",
    "test_bright_party.py::TestPartyLoop::test_the_queue_plays_through_with_per_track_anchors",
    "test_bright_party.py::TestPartyTransport::test_previous_goes_back_a_track",
    "test_bright_playback.py::TestThePartyEndsOnce",
    "test_bruh_print_atomic_write.py",
    "test_bruh_print_panel.py::TestTheCalibrationLabelItself::test_it_draws_without_a_complaint_on_every_stock_in_the_catalog",
    "test_chat_context.py::TestTheHook",
    "test_chat_terminal.py::ChatSessionCase::test_a_current_cli_is_stopped_by_asking",
    "test_chat_terminal.py::ChatSessionCase::test_an_older_cli_is_stopped_by_killing_and_resuming",
    "test_chat_terminal.py::ChatSessionCase::test_pressing_stop_is_not_a_failed_run",
    "test_chat_terminal.py::TestChatRoutes::test_the_snapshot_says_what_sending_will_do",
    "test_chat_terminal.py::TestManySessions::test_the_abandoned_answer_lands_in_its_own_transcript",
    "test_code_scanning.py",
    "test_deep_review.py::TestOnlyAPressReachesIt",
    "test_device_types.py::TestShowingAnEntityAsAnotherKind::test_a_core_that_will_not_say_is_refused_rather_than_written_unchecked",
    "test_devloop.py",
    "test_dictated_sentence.py::TestTheSentenceIsKept::test_a_routine_nobody_dictated_keeps_the_old_line",
    "test_discuss_registry.py::TestDiscussLeavesABusyChatAnswering",
    "test_doctor_deep.py::TestAutomationTaskStage::test_claimed_and_never_answered_is_a_different_sentence",
    "test_doctor_deep.py::TestChatStage::test_a_turn_that_never_ends_is_a_timeout_not_a_crash",
    "test_entry_edit_fuzz.py",
    "test_esphome.py::TestTheDashboardProtocol::test_logs_run_until_stopped_and_one_command_at_a_time",
    "test_esphome.py::TestTheDeviceBuilder::test_logs_stop_with_stop_stream",
    "test_esphome.py::TestTheMcpTools",
    "test_esphome.py::TestTheOldDashboardStillWorks::test_logs_run_until_stopped_and_one_command_at_a_time",
    "test_facts_store.py::TestRetrievalCostsAFractionOfTheDocument::test_the_block_is_small_and_complete",
    "test_file_ownership.py::TestTheCli::test_it_sends_whole_paths_and_prints_each_answer",
    "test_file_ownership.py::TestTheEditHook",
    "test_file_ownership.py::TestTheShellHook",
    "test_findings.py::TestFindingsStore::test_pruning_drops_settled_before_open",
    "test_ha_service_gates.py::TestWhoMayRunATask::test_a_non_admin_may_ask_a_read_only_question",
    "test_house.py::TestTheModelCanAskWhatHasBeenMeasured",
    "test_insights_addon.py::TestClaudeClient::test_a_real_run_over_a_real_pty_stores_a_usable_token",
    "test_insights_addon.py::TestClaudeClient::test_setup_flow_watchdog_fires_on_silent_hang",
    "test_intent_registry.py::TestTheAcceptReadsTheRegistry",
    "test_mcp_history_query.py",
    "test_memory_extract.py::TestTheHookGetsOutOfTheWay::test_it_exits_at_once_and_the_child_carries_on",
    "test_memory_learning.py::test_a_held_lock_exits_busy_rather_than_claiming_success",
    "test_memory_learning.py::test_a_timed_out_pass_says_so_instead_of_blaming_the_login",
    "test_memory_learning.py::test_confirm_goes_through_the_panel",
    "test_memory_learning.py::test_real_contention_is_still_reported_as_contention",
    "test_memory_learning.py::test_reject_goes_through_the_panel_and_carries_the_reason",
    "test_memory_learning.py::test_the_panel_is_the_authority_on_what_is_open",
    "test_minecraft_bridge.py::TestHaIntegrationBridge",
    "test_minecraft_install_plugin.py",
    "test_minecraft_scripts.py::TestBedrockSupport",
    "test_minecraft_services.py::TestTheBridgeAsksThePanelForAddons",
    "test_minecraft_world_manager.py::TestWorldManagerSwitch",
    "test_music_assistant.py::TestTheMcpTools",
    "test_numbers_agree.py::TestNoCheckSaysPressWrong::test_no_string_literal_says_press_wrong",
    "test_onboarding.py::TestTheOpeningSyllabusIsLighter",
    "test_panel_edits.py::TestManualConsolidation::test_a_second_press_joins_the_pass_instead_of_starting_one",
    "test_panel_edits.py::TestManualConsolidation::test_the_button_returns_before_the_pass_does",
    "test_proposal_accept.py::TestAWrittenFileIsNotARunningAutomation",
    "test_proposal_accept.py::TestAcceptingFourScenes::test_it_waits_for_every_scene_not_just_the_first",
    "test_proposal_accept.py::TestOneOffIntents::test_an_automation_core_still_has_after_the_reload_is_kept",
    "test_proposal_accept.py::TestUndoReversesAllThree::test_a_reload_that_fails_on_the_way_back_is_not_a_success",
    "test_reports.py::TestBrainReportScript",
    "test_resident.py::TestTheLedger::test_the_cheap_tier_never_stops_on_the_ledger",
    "test_resident_loop.py::TestTheLedgerRations::test_the_cheap_tier_is_never_stopped_by_the_ledger",
    "test_restart_notice.py::TestOneNoticeAndThePanelKnows::test_after_the_restart_there_is_nothing_to_say",
    "test_store_locking.py::TestRejectionsReachTheCardPrompt::test_it_stays_capped_over_the_union",
    "test_store_locking.py::TestTheConsolidatorTakesIt",
    "test_store_locking.py::TestTheLockKeepsTheAppend::test_nothing_appended_under_the_lock_is_lost",
    "test_store_locking.py::TestTheQueueTakesItsOwnLock::test_a_real_appender_survives_the_modules_own_writes",
    "test_store_locking.py::TestTheRealShellLibraryTakesTheSameLock",
    "test_store_locking.py::TestTheUnlockedReadModifyWriteLosesTheAppend::test_the_old_recipe_is_the_bug",
    "test_todo_list.py::TestTheFourthEnding::test_a_list_that_is_full_leaves_the_finding_alone",
    "test_todo_list.py::TestTheStore::test_the_cap_refuses_rather_than_making_room",
    "test_triage.py::TestEveryProducerFilesThroughTheGate::test_no_call_site_in_the_panel_can_file_past_the_gate",
    "test_triage_retired.py::TestTheDrainIsGone",
    "test_usage_tracker.py::TestTheTrackerRenewsTheCredentialItself",
    "test_voice_context.py::TestAWideAgentAskedByANonAdmin::test_an_admin_keeps_the_agents_level",
)


def _is_slow(nodeid: str) -> bool:
    for entry in SLOW:
        if nodeid == entry or nodeid.startswith((entry + "::", entry + "[")):
            return True
    return False


def pytest_collection_modifyitems(config, items):
    for item in items:
        # Node ids are relative to the rootdir, where pytest.ini lives.
        nodeid = item.nodeid
        if nodeid.startswith("tests/"):
            nodeid = nodeid[len("tests/"):]
        if _is_slow(nodeid):
            item.add_marker(pytest.mark.slow)


# ---------------------------------------------------------------------------
# A test that writes to the real /data is reported, and BRAIN_STRICT_DATA=1
# makes it fail.
#
# Forty-eight panel modules default a path to /data at import time, and a
# test that forgets to point one at tmp_path writes there. On a root machine
# (a Claude Code cloud session, a developer's container) the write succeeds
# and the test passes; on CI's unprivileged runner /data cannot be created
# and the same test is a PermissionError. The pattern stayed hidden for as
# long as the suite ran serially: one early test file patched a module's path
# and never restored it, and every later test in the process wrote to that
# tmp path by inheritance. Under xdist the inheriting file lands on another
# worker and the default comes back, which is what turned six tests red on
# the first parallel CI run. So the real /data is watched around every test,
# shallowly (its entries, their sizes and mtimes), and a test that changed it
# is named with the remedy, whichever machine it ran on.
#
# Named as a WARNING by default rather than a failure, because the first
# strict run counted 579 such tests: nearly all of them through the panel's
# accounting side channels (the run journal, the usage nudge, the decision
# trail, run_sources, the delivery ledger), which every route writes and
# which are wrapped to never raise, so on CI the write fails silently and
# the test passes. Failing 579 tests over a path nobody asked them about
# would be a red suite with no change in what it proves. The honest fix is
# one data root the panel reads (a BRAIN_DATA_DIR every one of the 48
# modules honours, set here before any of them is imported); until then the
# count is on every run's warnings summary, `BRAIN_STRICT_DATA=1` turns each
# into a failure, and the six paths that are NOT wrapped (the knowledge
# ledger, the onboarding state, the card token) are patched in the tests
# that reach them.
# ---------------------------------------------------------------------------

_REAL_DATA = Path("/data")


class RealDataWrite(pytest.PytestWarning):
    """A test changed the real /data (see the note above)."""


def _data_snapshot():
    if not _REAL_DATA.exists():
        return None
    out = {}
    try:
        for entry in os.scandir(_REAL_DATA):
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            out[entry.name] = (st.st_size, st.st_mtime_ns)
            if entry.is_dir(follow_symlinks=False):
                try:
                    for sub in os.scandir(entry.path):
                        try:
                            sst = sub.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        out[entry.name + "/" + sub.name] = (sst.st_size, sst.st_mtime_ns)
                except OSError:
                    continue
    except OSError:
        return None
    return out


@pytest.fixture(autouse=True)
def _no_writes_to_the_real_data_dir():
    before = _data_snapshot()
    yield
    after = _data_snapshot()
    if before == after:
        return
    if before is None:
        changed = sorted((after or {}).keys()) or ["/data (created)"]
    else:
        changed = sorted(k for k in set(before) | set(after or {})
                         if before.get(k) != (after or {}).get(k))
    message = (
        "this test wrote to the real /data: " + ", ".join(changed[:8])
        + (" …" if len(changed) > 8 else "")
        + ". Point the module's path at tmp_path (its *_FILE / *_DIR constant or"
        " BRAIN_* variable) in this test's own setUp; passing by inheriting"
        " another test file's patch is what breaks under xdist and on CI,"
        " where /data cannot be created.")
    if os.environ.get("BRAIN_STRICT_DATA") == "1":
        pytest.fail(message, pytrace=False)
    warnings.warn(message, RealDataWrite, stacklevel=1)
