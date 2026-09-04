// Drive the panel's sign-in surfaces and assert they can actually be reached.
//
// The failure this exists to prevent is not a layout bug — it is a panel
// that can sign you in once and can never talk to you about it again. The
// sign-in screen was gated on `authenticated` alone, so the moment a
// credential existed there was no route back to it; and `authenticated` is
// true for a credential that has STOPPED WORKING, because the only store
// that records an expiry is the CLI's own. So the exact state that needs
// the screen — a token that died on a Tuesday, chip reading "Claude auth
// failed" — was the one state with nothing to press. The chip was a `<span>`
// with no handler, there was no sign-out anywhere (the route existed and
// nothing called it), and sharing the login with the other BRUH add-ons was
// reachable only from a terminal command people had to already know about.
//
// So the checks are about what is REACHABLE as much as where it sits:
//
//   * the auth chip is a button and presses through to the sign-in screen,
//     from the failed state, with a credential stored.
//   * the sign-in screen has a way back out that returns the dashboard.
//   * ⚙ Settings names the credential in use, WHICH STORE it came from, and
//     the verdict of the last real check — three stores, always, because a
//     surface that can see only its own answers "not signed in" to somebody
//     who is. That is the bug `ha login --status` had.
//   * sharing is a control with two states and a note that changes with
//     them, and the note says what sharing costs (/config is in HA backups).
//   * a login that CANNOT be shared (Claude Code's own session token) hides
//     the button and says why, rather than offering a press that fails.
//   * every target clears the touch floor and nothing scrolls sideways.
//
// Drives the panel's real renderers behind a stubbed fetch. A copy of
// renderAuthBox in this file would only ever agree with itself.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.resolve(HERE, '..', '..', 'brain', 'panel');

const WIDTHS = [390, 430, 768, 1200];
const MIN_TARGET = 44;

// Three credential states, because none is a superset of the others and
// each one is a different sentence in the dialog:
//   panel    signed in here, shareable, nothing shared yet
//   shared   already published to the other add-ons
//   cli      Claude Code's own session login — signed in, NOT shareable
const STUB = `
window.__auth = null;
window.__authState = 'ok';
window.EventSource = function () {
  return { close() {}, addEventListener() {}, onmessage: null, onerror: null };
};
window.__mkAuth = (kind) => {
  const base = { auth_check: { state: window.__authState, error:
    window.__authState === 'failed' ? 'Invalid bearer token' : '',
    checked_at: Math.floor(Date.now() / 1000), running: false },
    recheck_seconds: 21600, shared_path: '/config/.brain/secrets/claude_auth.json' };
  if (kind === 'cli') {
    return { ...base, authenticated: true, type: 'cli_login', source: 'cli',
      saved_at: null, can_share: false,
      stores: { local: { present: false }, cli: { present: true },
                shared: { present: false } } };
  }
  if (kind === 'shared') {
    return { ...base, authenticated: true, type: 'oauth_token', source: 'local',
      saved_at: 1756000000, can_share: true,
      stores: { local: { present: true, saved_at: 1756000000 },
                cli: { present: false },
                shared: { present: true, type: 'oauth_token', saved_at: 1756000000 } } };
  }
  return { ...base, authenticated: true, type: 'oauth_token', source: 'local',
    saved_at: 1756000000, can_share: true,
    stores: { local: { present: true, saved_at: 1756000000 },
              cli: { present: false }, shared: { present: false } } };
};
window.__auth = window.__mkAuth('panel');
window.fetch = async (url, opts) => {
  const p = String(url);
  const answer = (body) => new Response(JSON.stringify(body), {
    status: 200, headers: { 'Content-Type': 'application/json' } });
  if (p.endsWith('api/auth')) return answer(window.__auth);
  if (p.includes('api/auth/share')) {
    window.__auth = window.__mkAuth('shared');
    return answer(window.__auth);
  }
  if (p.includes('api/auth/unshare')) {
    window.__auth = window.__mkAuth('panel');
    return answer({ ...window.__auth, removed: true });
  }
  if (p.includes('api/auth/recheck')) return answer({ started: true });
  if (p.includes('api/auth/token')) return answer({ saved: true, type: 'oauth_token' });
  if (p.includes('api/auth/setup/status')) return answer({ phase: 'idle', url: '', error: '' });
  if (p.includes('api/status')) {
    return answer({
      version: 'test', authenticated: true, auth_type: 'oauth_token',
      auth_source: 'local',
      auth_check: { state: window.__authState,
                    error: window.__authState === 'failed' ? 'Invalid bearer token' : '' },
      model: 'default', settings: { onboarded: true }, usage: {}, auto: {},
      categories: [], jobs: {}, queue_size: 0, findings_open: 0,
    });
  }
  if (p.includes('api/onboarding')) return answer({ state: 'done', onboarded: true });
  if (p.includes('api/settings')) return answer({ settings: {}, models: [], usage: {} });
  if (p.includes('api/insights')) return answer({ insights: [] });
  if (p.includes('api/diagnostics')) return answer({});
  if (p.includes('api/findings')) {
    return answer({ findings: [], hypotheses: [], open: 0, settled: [] });
  }
  return answer({});
};
`;

const failures = [];
const note = (where, message) => failures.push(`${where}: ${message}`);

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});

for (const width of WIDTHS) {
  // The narrow widths are phones, so they are driven AS phones: the touch
  // floor lives in a `pointer: coarse` block, and a context with a fine
  // pointer would measure the desktop density and call it a pass.
  const touch = width <= 430;
  const context = await browser.newContext({
    viewport: { width, height: 900 }, hasTouch: touch, isMobile: touch,
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => note(`${width}px`, `page error: ${e.message}`));
  await page.addInitScript(STUB);
  await page.goto(`file://${path.join(PANEL, 'index.html')}`);
  const where = `${width}px`;

  // ---- the ⚙ dialog's Claude account section --------------------------
  await page.click('#settingsBtn');
  await page.waitForSelector('#authBody p');

  const acct = await page.evaluate(() => ({
    body: document.querySelector('#authBody').textContent,
    stores: [...document.querySelectorAll('.authstores li')]
      .map((li) => ({ text: li.textContent.trim(), on: li.classList.contains('on') })),
    verdict: (document.querySelector('.authverdict') || {}).className || '',
    shareChip: document.querySelector('#authShareState').textContent.trim(),
    shareNote: document.querySelector('#authShareNote').textContent,
    shareShown: !document.querySelector('#authShare').classList.contains('hidden'),
    unshareShown: !document.querySelector('#authUnshare').classList.contains('hidden'),
    signoutShown: !document.querySelector('#authSignout').classList.contains('hidden'),
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));

  // All three stores, always. This is the check that would have caught
  // `ha login --status` reporting a working panel login as "not set up".
  if (acct.stores.length !== 3) {
    note(where, `the account section lists ${acct.stores.length} stores, expected 3`);
  }
  if (!acct.stores.some((s) => s.on)) {
    note(where, 'signed in, but no store is marked as holding the credential');
  }
  // "Signed in" is not enough: which store answered is the field that makes
  // "the terminal works and the panel doesn't" diagnosable at all.
  if (!/Signed in here/.test(acct.body)) {
    note(where, `the section never says where the credential came from: "${
      acct.body.slice(0, 70)}"`);
  }
  if (!/^authverdict ok$/.test(acct.verdict.trim())) {
    note(where, `the verdict of the last check is missing or unstyled: "${acct.verdict}"`);
  }
  if (acct.shareChip !== 'Not shared') note(where, `share chip reads "${acct.shareChip}"`);
  if (!acct.shareShown) note(where, 'a shareable login offers no way to share it');
  if (acct.unshareShown) note(where, '"Stop sharing" shown with nothing shared');
  if (!acct.signoutShown) note(where, 'no way to sign out');
  // A credential must never be rendered. This payload is read out loud in
  // bug reports and screenshotted.
  if (/sk-ant/.test(acct.body)) note(where, 'the account section renders a credential');
  if (acct.docWidth > acct.viewport + 1) {
    note(where, `page scrolls sideways (${acct.docWidth} > ${acct.viewport})`);
  }

  // What sharing COSTS has to be on screen: /config rides in Home Assistant
  // backups, which are unencrypted unless the user opted in. A share button
  // with no such sentence is a credential leaving the add-on quietly.
  const costs = await page.textContent('.sharebox');
  if (!/backup/i.test(costs)) {
    note(where, 'the sharing box never mentions that /config is in HA backups');
  }

  // ---- sharing is a real two-state control ----------------------------
  await page.click('#authShare');
  await page.waitForFunction(() =>
    !document.querySelector('#authUnshare').classList.contains('hidden'));
  const after = await page.evaluate(() => ({
    chip: document.querySelector('#authShareState').textContent.trim(),
    shareShown: !document.querySelector('#authShare').classList.contains('hidden'),
    sharedStore: [...document.querySelectorAll('.authstores li')]
      .some((li) => /Shared/.test(li.textContent) && li.classList.contains('on')),
  }));
  if (after.chip !== 'Shared') note(where, `after sharing the chip reads "${after.chip}"`);
  if (after.shareShown) note(where, '"Share it" still offered after sharing');
  if (!after.sharedStore) note(where, 'the store list did not notice the share');

  await page.click('#authUnshare');
  await page.waitForFunction(() =>
    !document.querySelector('#authShare').classList.contains('hidden'));

  // ---- a login that cannot be shared says so, and offers no button ----
  await page.evaluate(() => { window.__auth = window.__mkAuth('cli'); });
  await page.click('#diagRefresh');           // any control; reload the dialog
  await page.evaluate(() => window.loadAuth && window.loadAuth());
  await page.waitForTimeout(150);
  const cli = await page.evaluate(async () => {
    // The dialog reloads its own section; drive the real loader.
    const resp = await window.fetch('api/auth');
    const data = await resp.json();
    window.renderAuthBox ? window.renderAuthBox(data) : null;
    return {
      shareShown: !document.querySelector('#authShare').classList.contains('hidden'),
      note: document.querySelector('#authShareNote').textContent,
    };
  });
  if (cli.note) {
    if (cli.shareShown) {
      note(where, 'a session login that cannot be shared still offers the button');
    }
    if (!/refresh/i.test(cli.note)) {
      note(where, `the unshareable case never explains itself: "${cli.note.slice(0, 60)}"`);
    }
  }
  await page.evaluate(() => { window.__auth = window.__mkAuth('panel'); });

  // ---- every target in the section clears the floor -------------------
  // On TOUCH only, which is where the floor exists: `.authbtns .btn` sits in
  // a `pointer: coarse` block, exactly as `.propbtns .btn` does, so a
  // pointer device keeps the density the panel was designed at (a plain
  // `.btn` is 36px). Asserting it at every width would be asserting a rule
  // the stylesheet does not make — and asserting it at neither is how the
  // section that a person reaches for on a phone, precisely when the panel
  // has stopped working, would come to have 36px targets in it.
  const small = !touch ? [] : await page.evaluate((floor) =>
    [...document.querySelectorAll('.authbtns button')]
      .filter((b) => b.getBoundingClientRect().height > 0
                  && b.getBoundingClientRect().height < floor)
      .map((b) => `${b.textContent.trim()} @${
        Math.round(b.getBoundingClientRect().height)}px`), MIN_TARGET);
  small.forEach((s) => note(where, `target under ${MIN_TARGET}px: ${s}`));

  // ---- "Sign in again" reaches the screen WITH a credential stored ----
  await page.click('#authSignin');
  // Bounded and reported, never a bare `waitForSelector`: the failure this
  // whole block exists for is a screen that is UNREACHABLE, and a wait for
  // a thing that will never appear turns "there is no way to sign in again"
  // into a thirty-second timeout attributed to a selector.
  const opened = await page.waitForFunction(
    () => !document.querySelector('#setup').classList.contains('hidden'),
    null, { timeout: 4000 },
  ).then(() => true, () => false);
  if (!opened) {
    note(where, '"Sign in again" reaches nothing — the sign-in screen is '
              + 'still gated on being signed out, which is every state '
              + 'except the one that needs it');
    await context.close();
    continue;
  }
  const reachable = await page.evaluate(() => ({
    title: document.querySelector('#setupTitle').textContent,
    backShown: !document.querySelector('#setupBack').classList.contains('hidden'),
    dashHidden: document.querySelector('#dash').classList.contains('hidden'),
    settingsClosed: !document.querySelector('#setModal').classList.contains('open'),
  }));
  if (!reachable.backShown) {
    note(where, 'the sign-in screen has no way back — signed in, and stuck on it');
  }
  if (!reachable.dashHidden) note(where, 'the dashboard is still under the sign-in screen');
  if (!reachable.settingsClosed) note(where, 'Settings stayed open behind the sign-in screen');
  if (!/again/i.test(reachable.title)) {
    note(where, `the screen still reads as a first run: "${reachable.title}"`);
  }

  await page.click('#setupBack');
  // `waitForSelector` waits for VISIBLE by default, and a hidden section
  // never becomes that — so the class is what to wait on.
  await page.waitForFunction(() =>
    document.querySelector('#setup').classList.contains('hidden'));
  if (await page.evaluate(() => document.querySelector('#dash').classList.contains('hidden'))) {
    note(where, 'Back left the dashboard hidden');
  }

  // ---- and a sign-in that SUCCEEDS takes the screen down --------------
  // The screen is opened by a flag, and `authenticated` was already true
  // when it was opened — so nothing in the ordinary render would ever put
  // it away again. Sticky in exactly the case the screen was added for:
  // signing in again over a credential that had stopped working.
  // Reopened the way a person does it, not by poking a flag: `state` is a
  // `const` in the module scope and deliberately not on `window`, and a
  // test that reaches past the controls is a test of the reach.
  await page.click('#settingsBtn');
  await page.waitForSelector('#authBody p');
  await page.click('#authSignin');
  await page.waitForFunction(() =>
    !document.querySelector('#setup').classList.contains('hidden'));
  await page.click('.setup .tab[data-pane="paste"]');
  await page.fill('#pasteToken', 'sk-ant-oat01-' + 'x'.repeat(30));
  await page.click('#pasteSave');
  const cleared = await page.waitForFunction(
    () => document.querySelector('#setup').classList.contains('hidden'),
    null, { timeout: 4000 },
  ).then(() => true, () => false);
  if (!cleared) {
    note(where, 'signing in again left you stuck on the sign-in screen — '
              + 'the flag that opened it is never cleared on success');
  }

  // ---- the failed-login chip is a control, and it presses through -----
  // This is the state the whole change exists for: a stored credential that
  // has stopped working, where `authenticated` is true and the old panel
  // therefore had nothing to offer.
  const tag = await page.evaluate(() => document.querySelector('#authChip').tagName);
  if (tag !== 'BUTTON') note(where, `the auth chip is a <${tag.toLowerCase()}>, not a button`);

  await page.evaluate(() => {
    window.__authState = 'failed';
    window.__auth = window.__mkAuth('panel');
  });
  await page.evaluate(() => window.refreshStatus && window.refreshStatus());
  await page.waitForTimeout(200);
  await page.evaluate(() => {
    // The chip renders off the status poll; drive the real render rather
    // than waiting out a timer.
    if (window.renderAuth) window.renderAuth();
  });
  const chip = await page.evaluate(() => {
    const c = document.querySelector('#authChip');
    return { hidden: c.classList.contains('hidden'),
             text: c.textContent.trim(),
             box: c.getBoundingClientRect().height };
  });
  if (!chip.hidden) {
    if (chip.box < 40) note(where, `the auth chip is ${Math.round(chip.box)}px tall`);
    await page.click('#authChip');
    await page.waitForTimeout(200);
    const opened = await page.evaluate(() =>
      !document.querySelector('#setup').classList.contains('hidden'));
    if (!opened) {
      note(where, 'the failed-login chip presses through to nothing — '
                + 'the one state with no way to fix the sign-in');
    }
  }

  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(`measure-account: ${failures.length} problem(s)`);
  failures.forEach((f) => console.error('  ' + f));
  process.exit(1);
}
console.log(`measure-account: OK at ${WIDTHS.join(', ')}px`);
