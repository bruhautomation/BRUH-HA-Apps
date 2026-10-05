# brAIn UI redesign — design doc (approved 2026-10-05)

Source: https://claude.ai/artifact/J3zYHBARQFngnWHLQzyg9o — extracted as text; tables are rows of ` | `-separated cells. The owner approved implementing it, taking the doc's recommendation on every ⚠ capability decision.

brAIn UI redesign — design doc
 · 
Summary
Collapse brAIn from 4 top tabs, 8 sub-tabs, 4 list filters and a 6-section ⚙ into 3 tabs — Today, Ask, House — plus ⚙, with one decision card and 10 verbs.
The owner has four jobs. Every control below is judged against them:
Job
 | What the owner needs
 | Where it lives after this
 | 
See
 | What needs a decision, right now
 | Today, top of the screen
 | 
Decide
 | Make it in one press
 | The card's buttons
 | 
Trust
 | A one-line answer to "is brAIn working?"
 | Status line on Today; detail in ⚙ › Diagnostics
 | 
Ask
 | Ask brAIn anything
 | Ask tab, plus "Ask" on every card
 | 
What's wrong today, in one line each:
Decisions are spread over 7 surfaces. Findings, To-do, Proposals, Ideas, name tidying, update checks and house-book questions each have their own screen and verbs.
The product explains itself on every screen. Findings opens with 5 lines on how the buttons work; 3 of the 4 open cards carry "brAIn has not looked at this one yet, so it is shown as it was filed".
Hidden items have 3 homes and 3 restore verbs. Dismissed (37), Looked at (18) and Answered (89) sit beside Needs you (4), so the 4 that matter are a quarter of the chips.
The numbers disagree, which costs trust. The To-do badge said 2 while the list said 4; HA's To-do holds 5; facts are 99 in HA and 755 in the panel; the morning brief says 677 of 721 runs failed while Diagnostics says 224 ok.
Phone is an afterthought. At 385 px the first card starts below the fold: header, two tab rows, 7 lines of intro and 4 filter chips come first.
The proposal keeps every safety behaviour (permissions, protected entities, the action gate, Undo) and every capability except the eight marked ⚠ in Capability decisions.
What I walked
v2.12.0 of the add-on (integration still on 2.11.1), walked read-only on 5 Oct 2026 at 1190 px and 385 px. Nothing was pressed that changes the house or settings.
brAIn panel: Home › Findings (Needs you, Dismissed, Looked at, Answered), Insights, Ideas, To-do, Proposals; Ask (chat list, filters, a transcript); House › Knowledge, Activity, Upkeep; Help; ⚙ with all 6 sections expanded; a card's ⋯ menu and "Why brAIn thinks so".
Home Assistant: the brAIn integration page (13 devices, 23 entities), its sensors, the brAIn To-do list, Repairs, and the iframe insight card on the AI deployed dashboard.
Not reachable: the repo. This session has no access to it, so I could not read CLAUDE.md or the current tests/manual/measure-*.mjs. File names in the PR plan follow your brief; I'll confirm them against the repo before Pass 2.
First-time state: I didn't sign out to see it. It's inferred from the sign-in fields and the empty states (Ideas, Proposals).
The screens that drive most of this doc:
Proposed structure
Three tabs and ⚙. Today is for deciding, Ask is for asking, House is for reading what brAIn knows; ⚙ holds everything that tunes or inspects brAIn itself.
Today
 | Ask
 | House
 | ⚙
 | 
Status line, one queue of decisions, your list, and a History drawer
 | Your conversations with brAIn
 | Reports, what it knows, the house book, what happened
 | Account, usage, permissions, sources, memory, Diagnostics, Guide
 | 
How today's screens map onto it:
Today's screen
 | Goes to
 | Why
 | 
Home › Findings
 | Today › queue
 | It is the decision list
 | 
Home › To-do
 | Today › Your list
 | Accepted work sits under the decisions that made it
 | 
Home › Proposals
 | Today › queue (as "Suggestion" cards)
 | A proposal is a decision
 | 
Home › Ideas
 | House › Reports (a "Suggested" row)
 | It proposes a report, not a change to the house
 | 
Home › Insights
 | House › Reports
 | Reports are read, not decided
 | 
Upkeep › Names, rooms and aliases
 | Today › queue (one "Change ready" card)
 | Apply/Discard is a decision
 | 
Upkeep › Updates waiting
 | Today › queue (one card per assessed update)
 | "Is it safe tonight?" is a decision
 | 
Upkeep › House book
 | House › House book
 | Reference
 | 
Upkeep › Overnight health, Who can reach the house
 | ⚙ › Diagnostics
 | Their results already arrive as cards
 | 
House › Knowledge (brief)
 | Today › status line
 | The brief answers "is brAIn working, and what matters"
 | 
House › Knowledge (deep review)
 | House › Reports
 | It's a report
 | 
House › Knowledge (facts, teach)
 | House › What it knows
 | Reference
 | 
House › Knowledge (measurements, memory queue, memory doc)
 | ⚙ › Diagnostics / ⚙ › Memory
 | Mechanics
 | 
House › Activity
 | House › What happened
 | Reference
 | 
Help
 | ⚙ › Guide (opens the docs)
 | Not a daily job
 | 
One queue, one card
Findings, questions, suggestions and fixes ready to apply become one card type. Each card says what kind it is in its meta line, so the owner never has to learn which surface a thing lives on.
Kind
 | Primary
 | Secondary
 | In ⋯
 | 
Problem brAIn can fix
 | Apply
 | Snooze · Ignore
 | Ask · Recheck · Done
 | 
Problem you must fix
 | Add to list
 | Snooze · Ignore
 | Plan · Ask · Recheck · Done
 | 
Question (house book)
 | Send (inline answer field)
 | Snooze · Ignore
 | Ask
 | 
Suggestion (automation, scenes, names)
 | Apply
 | Snooze · Ignore
 | Ask
 | 
Update assessed
 | Add to list
 | Snooze · Ignore
 | Ask
 | 
Order: Urgent first (leak, alarm, water, a lock), then Problems, then Suggestions, newest first within each. The queue shows what fits on one screen (2–3 cards on desktop, 1 on a phone); "Show N more" reveals the rest.
Where hidden things live
One place: a History drawer at the bottom of Today, closed by default, with four filters. Every hidden item can be put back with the same verb, Restore.
Filter
 | What's in it
 | Today's equivalent
 | 
Snoozed
 | Back on a date, shown on the row
 | Dismissed
 | 
Ignored
 | Never raised again; Restore lifts the rule
 | Answered › Waved off, plus "Rules you set" in Knowledge
 | 
Done
 | Applied by brAIn, or done by you
 | Answered › Accepted / brAIn fixed it, To-do › Done
 | 
Set aside by brAIn
 | Raised by a check, judged not worth your time
 | Looked at
 | 
Duplicates collapse into one row with a count (the 6 "Cooling Time Yesterday" items become one row, "6 times since 15 Sep").
The first screen
Today, top to bottom:
Safety banner, only when something is urgent (leak, alarm, a change awaiting approval that touches a protected entity).
Status line: one sentence plus a dot. ● Watching · last look 9 min ago when healthy; ● Paused: Claude limit reached, back at 10:20 PM or ● Restart Home Assistant to finish updating brAIn when not. The morning brief, when there is one, is a "Read this morning's brief" link here.
The queue. Empty state: "Nothing needs you."
Your list (accepted to-dos plus your own), with an "Add" field.
History, closed.
A first-time owner sees the same screen with a 3-step setup card in place of the queue: Sign in → Choose what brAIn may change → First look (running). It disappears once the first look finishes.
Wireframes
One picture per screen, desktop on the left and phone on the right. Content is real data from your house; copy is final unless marked.
Today
The first card starts under one status line instead of 5 lines of intro, 4 chips and two panels. On a phone the tabs move to the bottom and the header shrinks to the logo, a status dot and ⚙.
Ask
The list holds only conversations you started. Tool calls fold into one line per reply, and any change brAIn wants to make still arrives as a card with Apply and what Undo restores.
House
One segmented control replaces Insights, Knowledge, Activity and the house-book half of Upkeep. Report cards show a headline and an age, nothing about tokens or pipelines; on a phone the segments become one styled select.
⚙
Eight named sections replace six collapsible ones with 15 "?" bubbles. Diagnostics gathers every counter, run log and self-test; its first row is the only one that can also surface on Today.
History (inside Today)
A drawer under Your list. Closed, it is one line, "History ▸". Open, it shows four filters (Snoozed · Ignored · Done · Set aside by brAIn) and one-line rows: title, a meta line such as "Snoozed until Wed" or "Applied 4 Oct", and one button, Restore (or Undo for applied changes). Same layout on a phone, full width.
Action vocabulary
Eight decision verbs on cards, seven utility verbs elsewhere. A button's label is one of these words and nothing else: no emoji or arrow glyphs, no tooltip needed.
Verb
 | What it does (≤ 5 words)
 | Used on
 | 
Apply
 | brAIn makes this change now
 | Fix cards, suggestions, name tidy
 | 
Plan
 | Draft a change, ask first
 | Problem cards brAIn can't fix yet
 | 
Add to list
 | You'll handle it
 | Problem and update cards
 | 
Snooze
 | Hide it; returns later
 | Every card
 | 
Ignore
 | Never raise this again
 | Every card
 | 
Done
 | It's handled; close it
 | Cards and list items
 | 
Restore
 | Put a hidden item back
 | History rows
 | 
Undo
 | Reverse what brAIn changed
 | Applied changes, toasts, History
 | 
Ask
 | Talk it through with brAIn
 | Cards, reports, Activity
 | 
Send
 | Send your message or answer
 | Chat, question cards, Teach
 | 
Recheck
 | Look again right now
 | Status line, ⚙ › Account
 | 
Run
 | Start this job now
 | Reports, ⚙ › Diagnostics
 | 
Save
 | Keep settings or a report
 | ⚙; "Save as report" in Ask
 | 
Share
 | Copy or put on dashboard
 | Reports, house book
 | 
Delete
 | Remove it for good (confirms once)
 | Conversations, facts, reports
 | 
Rules that go with it:
One primary button per card. Snooze and Ignore are always the secondary pair, in that order.
Undo appears for 30 days on everything Apply did, and its confirmation says what it will put back. That text is safety-critical and stays.
Ignore asks one optional question, "Why? (helps brAIn learn)", with "Ignore all like this" as a tick box. That replaces the separate "Stop raising these" item.
A destructive verb (Delete, Sign out) is never filled red at rest; it confirms once.
Buttons that don't fit today
Screen
 | Today's label
 | Becomes
 | 
Findings card
 | Fix it
 | Apply
 | 
Findings card
 | Add to list (two different tooltips for the same button)
 | Add to list (one meaning)
 | 
Findings card
 | Dismiss (it actually returns later)
 | Snooze
 | 
Findings card
 | Not a problem
 | Ignore
 | 
Findings ⋯
 | I've already fixed it
 | Done
 | 
Findings ⋯
 | Work out what to change
 | Plan
 | 
Findings ⋯
 | Check again
 | Recheck
 | 
Findings ⋯
 | Talk about it
 | Ask
 | 
Findings ⋯
 | Say what to do
 | Ask (⚠ see Capability decisions)
 | 
Findings ⋯
 | Stop raising these
 | Ignore › "Ignore all like this"
 | 
Findings
 | Run checks now
 | Cut from the page; Recheck lives in the status line's menu
 | 
Findings card copy
 | "press Wrong and say so" (no Wrong button exists)
 | "press Ignore"
 | 
Dismissed
 | Bring it back now
 | Restore
 | 
Looked at
 | ↑ Bring it to the front
 | Restore
 | 
Answered
 | ↺ Let brAIn raise it again
 | Restore
 | 
To-do
 | ✓ Done
 | Done
 | 
To-do
 | ⌫ Off the list
 | Snooze or Ignore
 | 
Insights
 | Ask ✨ (second ask box)
 | Cut; Ask tab
 | 
Insights card
 | ✎ (Refine)
 | Ask
 | 
Insights card
 | ↗ (Share)
 | Share, in ⋯
 | 
Insights card
 | ⤢ (Expand)
 | Cut; the card opens on click
 | 
Insights card
 | ‹ Older run, Latest ▾
 | ⋯ › Past versions
 | 
Insights
 | ⚙ Problems chip
 | Cut; the status line covers it
 | 
Ideas
 | ✨ Suggest ideas
 | Run, in Reports › Suggested
 | 
Proposals
 | Design them
 | Ask (⚠)
 | 
Ask
 | Resume now
 | Cut; sending a message resumes
 | 
Ask
 | ✕ on every conversation (29)
 | Delete, in the row's ⋯
 | 
House › Knowledge
 | Run a deep review
 | Run
 | 
House › Knowledge
 | ✎ Edit markdown, ⬇ Export
 | ⚙ › Memory › Edit, Export
 | 
House › Knowledge
 | ⇪ File into memory now
 | Cut (⚠)
 | 
House › Knowledge
 | ✕ Forget this fact
 | Delete
 | 
House › Knowledge
 | See the run
 | Cut from the row; in the fact's detail
 | 
Activity
 | ✧ What does this add up to?
 | Ask
 | 
Upkeep
 | Rewrite it now, Suggest again, Run the check now, Review now
 | Run
 | 
Upkeep
 | Publish a link
 | Share
 | 
Upkeep
 | Apply 1 ticked / Discard
 | Apply / Ignore
 | 
Upkeep
 | Is it safe tonight?
 | Run (or automatic, ⚠)
 | 
⚙ Account
 | Check it now, Refresh
 | Recheck
 | 
⚙ Diagnostics
 | Measure the house now, Run deep check, Rehearse…
 | Run
 | 
⚙ Diagnostics
 | Copy selected, Copy all, Write a report now, Copy for a bug report
 | One "Export report" (Share)
 | 
Visual standard
Four type sizes, a 4 px spacing grid, one card, one status chip, one empty-state line. Everything is a CSS token in style.css, so a layout test can assert it.
Element
 | Standard
 | 
Type scale
 | 20/28 semibold — tab title, at most one per screen · 16/24 semibold — card title · 14/20 regular — body · 12/16 medium — meta. Sentence case everywhere; no letter-spaced capitals.
 | 
Spacing
 | 4 px base. Inside a card 16; between cards 12; between sections 24; page gutter 24 desktop, 16 phone.
 | 
Card
 | 1 px border, radius 12, white surface, no shadow, no coloured left bar. Meta line → title → up to 3 lines of body → "Details" disclosure → one button row.
 | 
Status chip
 | A 8 px dot plus one word: Urgent (red), Problem (amber), Tidy-up (grey), Suggestion (blue). One chip per card, in the meta line.
 | 
Item state
 | Plain meta text, never a chip: "Snoozed until Thu", "Applied 4 Oct · Undo", "Ignored".
 | 
Buttons
 | 36 px desktop, 44 px phone. Primary filled, secondary outline, tertiary text. One primary per card. Icon-only only for ⋯, close and send, each with an aria-label.
 | 
Empty state
 | One sentence, no explanation, at most one action: "Nothing needs you."
 | 
Controls
 | One styled select, one toggle, one slider. No native <select> or checkbox chrome.
 | 
Numbers
 | Rounded for reading, unit spaced: "−100 labels over 28 days", not "-100.233labels".
 | 
Long text
 | Clamp at 3 lines with "More"; never cut mid-word without an ellipsis.
 | 
Where today breaks it
Headings: "What's waiting on you", "Ideas for new cards", "What could be better", "What you're going to do", "What happened", "Upkeep" and "This morning" are each a different voice and weight; Insights and Ask have none.
Capital labels: PROBLEM, TIDY-UP, DEGRADED, BROKEN, NEEDS A DECISION, NOT LOOKED AT YET, NOT CHECKED FIRST, BRAIN CHECKED, YOU BROUGHT THIS BACK, HOW YOU'D FIX IT, HOW BRAIN WOULD FIX IT, BRAIN WOULD NOT MAKE THIS CHANGE ITSELF, ACCEPTED, WAVED OFF, BRAIN FIXED IT, NOT SHOWN, FROM A FINDING, ADDED 13 D AGO, THE ONE THING THIS MONTH, WORTH ASKING, WORKING WELL, COULD BE BETTER — 22 distinct uppercase labels.
Two severities at once: a card can carry both PROBLEM and TIDY-UP.
Card styles: Findings cards have a coloured left bar; Dismissed cards are greyed; Insights cards are borderless with filled stat tiles; Knowledge items are rules between paragraphs; Activity rows are 11 px list lines.
Icon buttons: on an Insights card ✎ is filled black, ↗ is outlined, ⤢ and ⋯ are bare.
Glyphs in labels: ✓ ⌫ ↺ ↑ ✨ ✦ ✧ ✎ ↗ ⤢ ⇪ ⬇ ⏰ ‹ ›, plus 60 emoji in the Help contents.
Native controls: 11 native selects (Proposals room, Insights "Latest" ×5, Knowledge sort and teacher, ⚙ subscription, data, model, thinking, refresh, conversations kept) and a native checkbox (Automatic insights).
Tooltip dependence: 15 "?" bubbles in ⚙ and long title text on most buttons (Add to list, Dismiss, Not a problem, Done, Off the list, Let brAIn raise it again, Run a deep review…).
Status colours: Session pill amber dot, "Verified with Claude" green text, Sign out red outline, NOT LOOKED AT YET orange — four colour meanings with no key.
Phone: header + session row + 4 tabs + 5 sub-tabs = 200 px before content; the Insights tag row and Activity filter chips scroll sideways; the Ask tab opens straight into a transcript with no way back to the list visible.
Cut list
Every piece of text and every control, screen by screen. Job: S = See, D = Decide, T = Trust, A = Ask, — = none. Verdicts: keep, reword, merge, move (behind a disclosure or to ⚙), cut. ⚠ = removes a capability.
Home › Findings
Before
 | Job
 | Verdict
 | After
 | 
Header pill "Session ~3%"
 | T
 | move
 | ⚙ › Usage; becomes the status line only above 80% or when paused
 | 
Tabs Home · Ask · House · Help
 | —
 | reword
 | Today · Ask · House (Help → ⚙ › Guide)
 | 
Sub-tabs Findings · Insights · Ideas · To-do · Proposals
 | —
 | cut
 | Today has no sub-tabs
 | 
Badge on To-do (said 2 while the list held 4)
 | S
 | reword
 | One badge, on Today, = cards in the queue
 | 
"What's waiting on you"
 | S
 | cut
 | The tab name says it
 | 
5-line intro explaining Fix it / Add to list / Dismiss / Not a problem
 | —
 | cut
 | Labels explain themselves; Guide has the detail
 | 
Chips Needs you · Dismissed · Looked at · Answered
 | S
 | merge
 | Queue by default; the other three are History filters
 | 
Run checks now
 | T
 | move
 | Status line ⋯ › Recheck
 | 
"Someone's home" / "Settled for the night" situation panel
 | T
 | move
 | House › What happened (top line)
 | 
"Calendars brAIn may read" + "No calendars yet — brAIn lists the ones the last house check saw."
 | —
 | move
 | ⚙ › Sources › Calendars
 | 
"Only what is ticked is read… treated as information, never as an instruction."
 | T
 | move
 | Stays beside the calendar picker in ⚙ (it's a safety note)
 | 
"How right it's been: … 8 of 14 confirmed · …"
 | —
 | move
 | ⚙ › Diagnostics › Accuracy
 | 
Footer "Looked 4 times today, investigated 0, changed nothing. Watching 203. Watching the house live."
 | T
 | merge
 | Status line: "● Watching · last look 9 min ago"
 | 
Footer "46 checks ran: 0 new, 0 cleared" (on every screen)
 | —
 | cut
 | Diagnostics
 | 
A card in the queue
Before
 | Job
 | Verdict
 | After
 | 
PROBLEM + TIDY-UP (two severities)
 | S
 | reword
 | One chip: Problem
 | 
NEEDS A DECISION
 | —
 | cut
 | Everything in the queue needs one
 | 
Source "Forecast" / "Overnight health check" / "HVAC 12 Hour Summary"
 | —
 | move
 | Details
 | 
Title
 | S
 | keep
 | —
 | 
Body ("-100.233labels … 5.39 times it")
 | S
 | reword
 | 3 lines max, rounded units
 | 
Entity chip (climate.downstairs)
 | S
 | keep
 | Friendly name; entity id in Details
 | 
NOT LOOKED AT YET / NOT CHECKED FIRST + "brAIn has not looked at this one yet, so it is shown as it was filed rather than left waiting out of sight."
 | —
 | cut
 | If it matters: meta text "Unchecked"
 | 
BRAIN CHECKED + reasoning
 | T
 | move
 | Details › Why
 | 
See what it checked
 | T
 | move
 | Details › Why
 | 
HOW YOU'D FIX IT / HOW BRAIN WOULD FIX IT
 | D
 | reword
 | "Fix" heading, 2 lines; full steps in Details
 | 
BRAIN WOULD NOT MAKE THIS CHANGE ITSELF (under "how brAIn would fix it")
 | —
 | reword
 | "brAIn can't apply this" + one line why
 | 
"a fix may not call brain services — those run Home Assistant itself…"
 | —
 | cut
 | Log
 | 
"this plan was written before brAIn checked each change as an operation it can carry out, so there is nothing to approve — press Fix it again…"
 | —
 | reword
 | "This plan is out of date." + Plan
 | 
"What could go wrong: …"
 | D
 | keep
 | Visible on any Apply card — safety-critical
 | 
"Why brAIn thinks so" (often just "minor")
 | —
 | merge
 | One "Details" disclosure
 | 
Add to list · Dismiss · Not a problem · ⋯(6)
 | D
 | reword
 | Primary · Snooze · Ignore · ⋯(≤3)
 | 
⏰ Back in 2 days
 | S
 | reword
 | "Snoozed until Wed"
 | 
Dismissed · Looked at · Answered
Before
 | Job
 | Verdict
 | After
 | 
Three filters on the main screen
 | —
 | merge
 | History drawer: Snoozed · Ignored · Done · Set aside by brAIn
 | 
Full cards for every hidden item (37 in Dismissed)
 | —
 | reword
 | One-line rows, duplicates grouped ("6 times since 15 Sep")
 | 
"Problems the house checks raised that brAIn looked into and decided were not worth your time…"
 | —
 | cut
 | Filter name says it
 | 
NOT SHOWN / ACCEPTED / WAVED OFF / BRAIN FIXED IT / YOU BROUGHT THIS BACK
 | S
 | reword
 | Meta text: "Set aside", "On your list", "Ignored", "Applied", "Restored"
 | 
"You said: …" on answered questions
 | S
 | keep
 | —
 | 
Bring it back now · ↑ Bring it to the front · ↺ Let brAIn raise it again
 | D
 | merge
 | Restore
 | 
Home › Insights → House › Reports
Before
 | Job
 | Verdict
 | After
 | 
"Checks ran 3:37 AM · 46 ran · next 9:37 AM · Baselines rebuilt … · Memory filed 15 h ago, 13 waiting · 207 Claude runs"
 | —
 | cut
 | Diagnostics
 | 
"1 problem since yesterday ⚙ Problems"
 | T
 | cut
 | Status line
 | 
Ask box + "Every answer becomes a card. Say 'learn about…'…"
 | A
 | merge
 | Ask tab; "Save as report" on an answer
 | 
16 tag chips (#did-the-house-get-put-to, #lev-kaz-how-the-night…)
 | —
 | cut
 | A search field when there are more than 8 reports
 | 
Card ✎ ↗ ⤢ ⋯ ‹ Latest▾
 | —
 | reword
 | Ask · ⋯ (Share, Past versions, Run, Delete)
 | 
"Analysed 15 h ago · 4 readings live · 8 min ago · the findings list changed; memory was updated; a measurement was rebuilt · next tomorrow · 51.4k tokens"
 | —
 | reword
 | "Updated 15 h ago"
 | 
Home › Ideas, To-do, Proposals
Before
 | Job
 | Verdict
 | After
 | 
Ideas intro ("Nothing here is generating anything — an idea costs nothing until you take it…")
 | —
 | cut
 | —
 | 
Ideas empty state (2 sentences + "Last looked 6 d ago · 2 proposed…")
 | —
 | cut
 | Row hidden when empty
 | 
✨ Suggest ideas
 | —
 | move
 | Reports › Suggested › Run
 | 
To-do intro ("Findings you've accepted as real work… free to find it again")
 | —
 | cut
 | —
 | 
To do · 4 / Done · 5 chips
 | S
 | merge
 | Your list; Done → History
 | 
FROM A FINDING · ADDED 13 D AGO
 | —
 | reword
 | "Added 13 days ago" meta
 | 
Add field "Something else that needs doing…"
 | D
 | keep
 | "Add to your list…"
 | 
Proposals intro (5 lines on replays, automations.yaml, Undo)
 | —
 | cut
 | Details on each suggestion card keeps "Writes one automation; Undo removes it"
 | 
Proposals "Design scenes for [room ▾] Design them"
 | —
 | move
 | Ask (⚠)
 | 
Proposals empty state ("brAIn proposes a change once it has watched you… on 6 separate days…")
 | —
 | cut
 | Guide
 | 
Ask
Before
 | Job
 | Verdict
 | After
 | 
Run-type chips Chats 31 · Automation 3 · Cards 15 · Doctor 3 · Fixes 7 · Memory 117 · Resident 150 · Upkeep 6 · Voice 55
 | —
 | move
 | ⚙ › Diagnostics › Runs; Ask lists your chats only (⚠)
 | 
✕ on every row
 | —
 | move
 | Row ⋯ › Delete
 | 
Select conversations icon
 | —
 | cut
 | —
 | 
Tool-call rows (Bash, ToolSearch, mcp__home-assistant__get_history, Thinking, Background task finished)
 | T
 | move
 | One "Worked through 14 steps" disclosure per reply
 | 
"Your next message resumes this conversation with its context" + Resume now
 | —
 | cut
 | Sending resumes
 | 
Chat options · Full-screen terminal
 | —
 | keep
 | In ⋯
 | 
"Discussing: …" titles
 | S
 | reword
 | The card title, linked back to its card
 | 
House › Knowledge → House › What it knows
Before
 | Job
 | Verdict
 | After
 | 
"This morning" brief
 | T
 | move
 | Today › status line link
 | 
Deep review + "About 167k tokens — roughly 11% of a five-hour session… An estimate: what the last 1 review on this house cost."
 | A
 | move
 | Reports › Deep review; Run shows "~11% of a session"
 | 
"OCT 4 · OPUS · 167K TOKENS"
 | —
 | reword
 | "4 Oct"
 | 
"What brAIn has measured" (7 measurements, "Built quietly, over days… Nothing here costs a Claude run.")
 | —
 | move
 | ⚙ › Diagnostics › Measurements
 | 
"How brAIn's memory works" (3 paragraphs)
 | —
 | cut
 | Guide
 | 
Memory document + ✎ Edit markdown + ⬇ Export
 | —
 | move
 | ⚙ › Memory
 | 
Waiting to be filed queue + ⇪ File into memory now + ✕ ×13
 | —
 | move
 | ⚙ › Memory; manual filing cut (⚠)
 | 
Teach box
 | A
 | keep
 | "Tell brAIn something…" + Send
 | 
Facts list: search, sort ▾, "Anyone taught it" ▾, All · The house · Rooms · Devices · Rules you set
 | S
 | reword
 | Search + Rooms · Devices · House; Rules → History › Ignored
 | 
Per fact ✕ + See the run
 | —
 | reword
 | Row ⋯ › Delete; source in the row's detail
 | 
House › Activity → House › What happened
Before
 | Job
 | Verdict
 | After
 | 
Intro ("Not every state change… no Claude run, nothing spent. Tap a row…")
 | —
 | cut
 | —
 | 
Everything 14045 · Automation 664 · Script 35 · Scene 53 · Person 38 · No cause recorded 13255
 | S
 | reword
 | One "Caused by" select, no counts
 | 
‹ Earlier · Last 24 hours · Later ›
 | S
 | keep
 | —
 | 
✧ What does this add up to?
 | A
 | reword
 | Ask
 | 
Group intros ("Home Assistant itself stopping and starting…")
 | —
 | cut
 | Group name only
 | 
House › Upkeep
Before
 | Job
 | Verdict
 | After
 | 
Intro ("Each button spends one Claude run; nothing in Home Assistant changes until you tick it…")
 | —
 | cut
 | —
 | 
House book + Rewrite it now + Publish a link
 | S
 | move
 | House › House book · Run · Share
 | 
"Every sentence names what it came from; codes and passwords are left out."
 | T
 | keep
 | One line under Share (it's what a sitter sees)
 | 
Names, rooms and aliases table + Suggest again · Apply 1 ticked · Discard · 2 suggestions brAIn refused · Undo
 | D
 | move
 | Today › one "Tidy 12 names" card: Apply · Snooze · Ignore; refused rows in Details
 | 
Updates waiting + Is it safe tonight?
 | D
 | move
 | Today › one card per update once assessed (⚠ automatic run)
 | 
Overnight health check + Run the check now
 | T
 | move
 | ⚙ › Diagnostics
 | 
Who can reach the house + Review now ("1 security finding open on Findings" — it was dismissed)
 | T
 | move
 | ⚙ › Diagnostics; its findings are cards
 | 
Help
Before
 | Job
 | Verdict
 | After
 | 
A top tab
 | —
 | move
 | ⚙ › Guide
 | 
64-item contents with an emoji each
 | —
 | reword
 | 8 groups, no emoji
 | 
Hero "Your house already has nerves. Now give it a brAIn."
 | —
 | cut
 | Marketing; README
 | 
"Back up Home Assistant first" box
 | T
 | keep
 | First-run setup card and Guide
 | 
⚙ Settings
Before
 | Job
 | Verdict
 | After
 | 
Claude account: "Signed in here — … Saved Sep 14… Stored by this panel, in the add-on's own storage." + 3 storage-path ticks
 | T
 | reword
 | "Signed in · checked 3:36 AM" + Recheck; paths in Details
 | 
Sign in again · Check it now · Sign out (red)
 | —
 | reword
 | Recheck · Sign out (neutral, confirms)
 | 
"brAIn re-checks a stored credential every few hours… which is why it is a button and not a timer."
 | —
 | cut
 | —
 | 
Share login with other add-ons + /config/.brain/secrets/claude_auth.json (0600) + backups warning
 | T
 | reword
 | Toggle + one line: "Shared logins are stored in backups."
 | 
Insights: Automatic insights, subscription, budget slider, "This session right now", data mode, 💡 token tips
 | —
 | merge
 | ⚙ › Usage & schedule; tips cut
 | 
Terminal & chat: Let brAIn act without asking + "Protected entities are refused through brAIn's own tools, not every shell command."
 | T
 | keep
 | ⚙ › Permissions; the caveat stays verbatim
 | 
Ask tab opens as, Conversations kept open at once
 | —
 | move
 | ⚙ › Permissions › Advanced
 | 
Generation defaults (8 fields, "the same settings as the Configuration tab", "Only log_level stays Configuration-tab-only…")
 | —
 | move
 | ⚙ › Usage & schedule › Advanced; sync explanations cut
 | 
Cameras
 | —
 | keep
 | ⚙ › Sources › Cameras
 | 
Advanced › Diagnostics (19 rows: daemons, shadow checks, action gate counters…)
 | T
 | keep
 | ⚙ › Diagnostics; first row "Anything wrong?" surfaces on Today
 | 
"Home Assistant integration has not loaded v2.12.0 yet… Restart Home Assistant…" (buried)
 | T
 | move
 | Today status line until done
 | 
Write house rules
 | D
 | move
 | ⚙ › Permissions (safety: can only make brAIn more careful)
 | 
Speak first
 | —
 | move
 | ⚙ › Notifications
 | 
Problems (report files) · Capture runs for the corpus · Deep check · Rehearsal
 | T
 | keep
 | ⚙ › Diagnostics › Developer, closed
 | 
"Reporting a bug? Run brain report on the Ask tab."
 | —
 | reword
 | Export report
 | 
Home Assistant side
Before
 | Job
 | Verdict
 | After
 | 
To-do entity "brAIn System brAIn" (5 items, includes an undecided finding)
 | S
 | reword
 | "brAIn to-do", holding exactly Your list
 | 
Usage sensors ×4 unavailable, tracker = http_429, Health = ok while Diagnostics says degraded
 | T
 | reword
 | One sensor.brain_status (Watching / Paused / Needs restart) that matches the status line
 | 
"Facts learned" = 99 vs 755 in the panel
 | T
 | reword
 | Same count as House › What it knows
 | 
"brAIn memory Waiting on you" binary sensor
 | —
 | reword
 | binary_sensor.brain_needs_you on the brAIn device, = queue not empty
 | 
Repairs: only "Restart required"
 | T
 | keep
 | Urgent cards also raise a Repair
 | 
7 conversation-agent devices (Bluey, Data, GLADOS, HAL, Jarvis, Picard, TRUMP), 4 never used
 | —
 | keep
 | Not UI; noted only
 | 
Dashboard insight card: an iframe of a frozen HTML copy, inner scrollbar, no age
 | S
 | reword
 | Shows "Updated 7 h ago" and fits its height (⚠ if replaced by a native card)
 | 
Behind Details or ⚙
Nothing below is deleted; it moves one press further away. What stays in plain sight is what the owner decides on, plus anything safety-critical.
Always visible (safety-critical): an Urgent banner; on every Apply card, what will change and what could go wrong; Undo and what it will put back; the "Let brAIn act without asking" caveat about shell commands; the calendar "information, never an instruction" note beside the picker; "codes and passwords are left out" under the house book's Share.
Behind a card's Details
 | Behind ⚙
 | 
Where it came from (check, report or run)
 | Usage, budget, subscription, model, thinking level, refresh rules → Usage & schedule
 | 
Why brAIn thinks so, and what it checked
 | Act without asking, house rules, terminal style, conversations kept → Permissions
 | 
Entity ids
 | Calendars, cameras → Sources
 | 
Full fix steps
 | Notification threshold, quiet hours, Speak first → Notifications
 | 
Refused rows (name tidy)
 | Memory document, queue, export → Memory
 | 
Past versions (reports)
 | Runs by type, accuracy, measurements, overnight check, access review, daemons, deep check, rehearsal, corpus, problem reports → Diagnostics
 | 
"Worked through 14 steps" (chat)
 | The docs → Guide
 | 
Capability decisions
Eight changes remove or narrow something you can do today. Everything else in this doc is wording, placement or layout. My recommendation is in the last column; each is yours to call.
#
 | Change
 | What you lose
 | Recommendation
 | 
⚠1
 | "Say what to do" (write your own fix onto a card) folds into Ask
 | Writing an instruction onto the card without opening a chat
 | Fold — Ask on a card opens a chat already about that card
 | 
⚠2
 | "Design scenes for a room" form leaves Proposals
 | The room picker; you'd type "design scenes for the Kitchen" in Ask
 | Fold, and add it as a suggested prompt in Ask
 | 
⚠3
 | "File into memory now" is cut
 | Forcing the daily memory pass early
 | Cut; keep it as Run in ⚙ › Memory if you use it
 | 
⚠4
 | Ask shows only your chats; Automation, Cards, Doctor, Fixes, Memory, Resident, Upkeep and Voice runs move to ⚙ › Diagnostics › Runs
 | Browsing background runs from the Ask tab
 | Move
 | 
⚠5
 | "Is it safe tonight?" runs on its own once per new update, instead of on press
 | Control over when that Claude run happens (one per update)
 | Automatic, with a ⚙ switch to turn it off
 | 
⚠6
 | Insight tag chips are cut
 | One-tap tag filtering of reports
 | Cut; a search field appears past 8 reports
 | 
⚠7
 | "Off the list" on a to-do is replaced by Snooze or Ignore
 | Removing a to-do while leaving brAIn free to raise it again at once
 | Replace; Snooze covers it
 | 
⚠8
 | The dashboard insight card becomes a native Lovelace card
 | Nothing, if done well; it's a new component
 | Defer: only add "Updated 7 h ago" and fix the height now
 | 
Not on this list on purpose: permissions, protected entities, the action gate, house rules, Undo, and "What could go wrong" are unchanged in behaviour and stay visible.
Implementation plan
Eleven PRs, ordered so each one ships alone and the first two fix trust before anything moves. Every PR updates tests/manual/measure-*.mjs to assert the standard (including that cut text stays cut), updates the docs, and carries before/after screenshots at 1190 px and 390 px.
#
 | PR
 | Scope
 | Tests assert
 | ⚠
 | 
1
 | Numbers that agree
 | One source for every count: Today badge = queue length; HA To-do = Your list only; facts sensor = panel count; run totals and health use the same journal; "restart required" and "paused" reach the status line. Fix "press Wrong", unit formatting, mid-word truncation.
 | Badge equals list length on every tab; no /\d[a-z]/ unit gluing; truncated text ends with …
 | —
 | 
2
 | Action vocabulary
 | Rename every button per the table; Dismiss → Snooze with "until" date; one Restore; ⋯ down to ≤3 items; Ignore's optional reason + "Ignore all like this"; strip glyphs and tooltip prose from labels.
 | Every visible button label is in the vocabulary list; no title longer than 40 chars on buttons; no glyph prefixes
 | 1, 7
 | 
3
 | Visual tokens
 | Type scale, spacing, card, status chip, buttons, styled select/toggle/slider, empty-state component in style.css. No layout moves yet.
 | Computed font sizes ∈ {12,14,16,20}; paddings ∈ 4 px grid; zero native <select>; one primary per card
 | —
 | 
4
 | Card copy
 | One severity chip; cut NOT LOOKED AT YET / NOT CHECKED FIRST prose; Why + what it checked + entity ids + source into one Details; "brAIn can't apply this" replaces the contradiction; "What could go wrong" stays visible.
 | Banned-phrase list absent from DOM outside Details; card body ≤ 3 lines; "What could go wrong" visible on Apply cards
 | —
 | 
5
 | History drawer
 | Snoozed · Ignored · Done · Set aside by brAIn as one-line rows; group duplicates; Rules you set move here.
 | 4 filters, 0 on the main view; duplicate subjects render once with a count
 | —
 | 
6
 | Today
 | Rename Home → Today; status line; one queue for findings, questions, suggestions, name tidy and update cards; Your list; remove sub-tabs; first-run setup card; brief link.
 | No sub-tab bar; first card top ≤ 240 px at 1190 and ≤ 360 px at 390; empty state is one line
 | 5
 | 
7
 | Ask
 | Your chats only; tool calls collapse into "Worked through N steps"; cut Resume now; Ask on a card opens a chat about it; "Save as report".
 | Run-type chips absent; tool rows hidden by default; no "Resume" text
 | 1, 2, 4
 | 
8
 | House
 | Reports (insights, deep review, Suggested), What it knows (facts + Tell brAIn), House book, What happened. Measurements and memory mechanics leave.
 | Three intro paragraphs absent; no token counts on cards; tag chips absent
 | 6
 | 
9
 | ⚙ restructure
 | Account · Usage & schedule · Permissions · Sources · Notifications · Memory · Diagnostics · Guide; Help tab removed; Diagnostics gets Runs and Accuracy.
 | Section count = 8; zero "?" bubbles; Sign out not red at rest; safety caveats present
 | 3, 5
 | 
10
 | Phone
 | Bottom tab bar, 56 px header with status dot and ⚙, 44 px targets, no sideways-scrolling chip rows, Ask opens on the list.
 | At 390 px: header ≤ 56 px; no element wider than the viewport; targets ≥ 44 px
 | —
 | 
11
 | Home Assistant side
 | sensor.brain_status, binary_sensor.brain_needs_you, To-do renamed "brAIn to-do"; Urgent cards raise a Repair; dashboard card shows its age and fits.
 | Entity names and states match the panel (an integration test, not measure-*)
 | 8 (deferred)
 | 
Open question before Pass 2: I need the repo connected to this session (or its link) to read CLAUDE.md and the existing measure-*.mjs harness; PR 1 starts there.
