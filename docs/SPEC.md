# Build spec, v2: Four Thousand Weeks task app

Read docs/PRINCIPLES.md and docs/DECISIONS.md first. This spec is the minimal
implementation of those rulings. v1 of this file is superseded; the v1 code in
the repo is the starting point and must be changed to match this document.
Do not add features, dependencies or abstractions beyond it.

## Hard constraints (unchanged)

1. **Python 3.8+ standard library only.** No pip, no venv, no third-party
   anything, no build step. `python app.py` on Windows, `python3 app.py` on
   macOS/Linux. No syntax newer than 3.8 (no `match`, no `X | Y`, no
   `str.removeprefix`, no zoneinfo, no `datetime.UTC`).
2. **No network beyond the loopback.** Bind `127.0.0.1` only. CSP
   `default-src 'self'; img-src 'self' data:` on every response (the report
   page may add a `style-src` hash). Host header check. Writes require
   `Content-Type: application/json` and reject cross-site `Origin` /
   `Sec-Fetch-Site`. No external fonts, scripts, images, CDNs, analytics,
   update checks or telemetry. `grep -rniE "https?://" --exclude-dir=.git .`
   finds only loopback addresses.
3. **No secrets, no PII in the repo.** `data/` is gitignored. Birth date is
   optional and lives only in the SQLite file.
4. **Nothing in history is deleted.** The `events` table is append-only. No
   hard delete in the UI.
5. **Tone.** No shame, no streaks, no badges, no scores, no timers, no due
   dates, no notifications, no gamification. Letting go and setting aside are
   outcomes, not failures. Copy is short and plain. (Colour rules changed: see
   Design. Red is still never used for anything.)
6. **No libraries of any kind in the UI.** Hand-written HTML, CSS and plain
   JS. Icons are inline SVG drawn by hand in index.html as `<symbol>`s and
   used with `<use href="#icon-name">`.

## Layout (unchanged)

```
app.py  static/index.html  static/app.js  static/style.css
tests/__init__.py  tests/test_app.py   (python3 -m unittest -v)
README.md  .gitignore  run.sh  run.bat  docs/
```

## Running (unchanged)

`python3 app.py [--port 8787] [--db data/fourthousand.sqlite] [--no-browser]`

## Data model

v1 schema plus migration to `user_version = 2`:

```sql
ALTER TABLE tasks ADD COLUMN touched_at TEXT;   -- set by Renew; NULL otherwise
```

Settings keys: `focus_cap` 3 (fixed), `closed_cap` 10 (fixed), `open_cap` 20
(editable in Settings, 5 to 200), `stale_days` 14 (fixed), `birth_date`
optional `YYYY-MM-DD`.

`age_days` of an open item = days since `touched_at` if set, else since
`created_at`. `stale` = `age_days >= stale_days`.

## Buckets and movement

Three active buckets, all capped: **Focus** (3), **Closed** (10), **Open**
(open_cap). Plus **Neglect** (set aside; unbounded), **Done**, **Let go**.

- A task may be created into, or moved to, **any** of Focus, Closed, Open
  (the one-step rule is gone). `done`, `let_go`, `neglect` from any active
  bucket or from neglect; `neglect` needs a non-empty reason, `let_go` an
  optional one. Revives: neglect → any active bucket, let_go → open,
  done → open (undo).
- **Position.** Every placement takes an optional `position` (0 = top).
  Default 0 for a move between buckets and for creation; `reorder` within a
  bucket is unchanged.
- **Moving into a full Focus.** The request must name `bump_id`, a current
  focus task. The bumped task goes to Closed at position 0. Without
  `bump_id` the server answers `409 {"error": "Focus is full.", "needs":
  "bump", "candidates": [{id, title}, ...]}` and changes nothing.
- **Moving into a full Closed** (directly, or because a bump pushed one
  in): the entering task takes the given `position` (default 0; a drop
  gives the drop index), later tasks shift down, and the **last** Closed
  task moves to Open at position 0. Automatic, no prompt.
- **Moving into a full Open** (directly, or because Closed overflowed):
  - direct: the request must give `position` (0..open_cap-1); without it
    `409 {"error": "Open is full.", "needs": "position", "cap": 20}` and
    nothing changes. The task is inserted there, later items shift down.
  - overflow from Closed: position 0.
  - Either way the **last** Open task leaves Open to **Neglect** with
    `reason = "Bumped out of Open"` and `neglect_at` set.
- The whole cascade is one transaction. The response is
  `{"task": ..., "cascade": [{"id", "title", "from", "to"}, ...]}` in the
  order the moves happened, so the UI can show one small warning.
- `is_first` stays: one Focus item may be marked first; set only on a focus
  item, cleared when it leaves Focus (including when bumped).
- **Renew**: `POST /api/tasks/{id}/renew` sets `touched_at = now` on an
  open task and logs an event `renew`.
- **Aging**: the Neglect page shows two groups: open tasks with
  `stale = true` ("Aging in Open", with age in days) and tasks in state
  `neglect` ("Set aside"). Both offer **Retire** (= let_go, optional
  reason). Aging items also offer Renew and the bucket chooser. Set-aside
  items offer Revive (bucket chooser).
- Serialize note, stale flag, quick log, reviews, report, exports as in v1.
  The report gains nothing new except that "Bumped out of Open" items are
  listed under "what you neglected on purpose" with that reason, as any
  neglect is.

## API

Unchanged except:

```
POST /api/tasks                 {title, notes?, project?, state?: open|closed|focus|done,
                                 position?, bump_id?, for_its_own_sake?}
                                -> 201 {"task":..., "cascade":[...]} | 409 as above
POST /api/tasks/{id}/move       {to, position?, bump_id?, reason?}
                                -> 200 {"task":..., "cascade":[...]} | 409 as above
POST /api/tasks/{id}/renew      -> 200 task
GET  /api/state                 lists {focus, closed, open, neglect}; every open
                                task carries age_days and stale; caps include open_cap
PUT  /api/settings              {birth_date?, open_cap?}
```

Errors keep the v1 shape and codes (400/403/404/409/415/503, never 500).

## Pages and navigation

Nav order: **Focus**, **Open**, **Neglect**, **Weeks**, **Review**,
**Report**, **Settings**, **Why**. Hash routes as in v1 (`#/` is Focus).

**Focus page (home)**, top to bottom:
1. Header: wordmark, nav, theme toggle (icon button cycling system → light
   → dark, remembered in `localStorage` key `theme`; the chosen theme is
   applied by setting `data-theme` on `<html>`).
2. **Lifeline** (the weeks band; see Design). Links to the Weeks page.
3. **Focus** band: three slots, the first-marked item as the large card.
4. **Closed**: ten slots, compact, "7 of 10".
5. **Done today** ledger at the bottom of the page, with the quick-log
   line (title + "for its own sake" checkbox).
6. Floating **+** button, bottom right, always visible on every page.

**Open page**: the Open list, "12 of 20", stale items marked with the clock
icon and "16 days" in muted text. Same row controls. Drag to reorder.

**Neglect page**: "Aging in Open" then "Set aside", as described above.

**Weeks, Review, Report, Settings, Why**: as v1. Settings gains the Open
cap field (number, 5 to 200) next to the birth date.

## Row controls (every task row in Focus, Closed, Open)

Left to right: drag grip (icon-grip, cursor grab, also the DnD handle),
checkbox (marks done; unchecking in the ledger undoes), title (click to edit
inline), project chip, then a control cluster that is always visible but
quiet (muted colour, brightens on hover/focus of the row):

- **icon-up**: promote one bucket (Open → Closed → Focus). Hidden in Focus.
- **icon-down**: demote one bucket (Focus → Closed → Open). Hidden in Open.
- **icon-bucket**: opens the **bucket chooser**, a small popover anchored to
  the button with three options Focus / Closed / Open (current one marked)
  and, for Open, a position field shown only when Open is full. Choosing a
  full Focus turns the popover into the **bump picker**: "Focus is full.
  Which one steps aside?" with the three focus titles as a radio list and a
  one-line note of what will happen ("It moves to the top of Closed; if
  Closed is full, its last item moves to the top of Open."). Confirm button.
- **icon-more** (⋯): edit, mark first (Focus only), let go, set aside,
  renew (Open only).

Promote/demote via the arrows and drops via DnD go through the same server
call and get the same 409s; when a 409 with `needs` comes back, the UI
opens the matching picker (bump or position) pre-filled for that move, and
retries with the answer. Every successful move with a non-empty `cascade`
shows one **toast** at the bottom centre for about 6 seconds:
"Fence moved to Focus · Call Dad moved to Closed · Sourdough moved to Open."
Toasts are `role="status"`; no sound, no modal.

**Drag and drop**: within a list to reorder; between Focus and Closed on
the home page; within Open on the Open page. HTML5 DnD with a clear
placeholder; keyboard fallback is the arrow icons plus the ⋯ menu's
"move up / move down".

## Create dialog

The **+** button opens a native `<dialog>` (also opened by the `n` key and
by clicking an empty Focus or Closed slot, which pre-selects that bucket):

- Title (large input, autofocus), Project (small), Notes (optional, one
  line that grows).
- **Bucket**: a three-way segmented control Focus / Closed / Open, default
  Open; each segment shows its count, e.g. "Focus 3/3", "Closed 7/10",
  "Open 12/20". Picking a full bucket reveals the second step inside the
  dialog: the bump picker for Focus (radio list of the three), or for Open
  the position field (number 1..cap, default 1) with the note "The last
  item in Open moves to the Neglect page." Closed full needs no step; show
  the note "Closed is full: its last item will move to the top of Open."
- Enter submits, Esc closes. Submit is one POST with state, position and
  bump_id as needed. On success close, re-render, toast if cascade.

## Design (Fable's direction; implement exactly, ask nothing)

**Concept: "dusk and ember".** The page is a night sky that is slowly
turning, with three embers at the centre (Focus). Light mode is the same
sky at dawn: bone paper with a warm wash. Everything is CSS; the only
"image" is an inline SVG turbulence filter for grain.

**Tokens** (custom properties on `:root`; dark is the default when the
system prefers dark or `data-theme="dark"`; light under
`prefers-color-scheme: light` or `data-theme="light"`):

```
dark:   --bg0 #090b14  --bg1 #10132a  --surface rgba(255,255,255,.045)
        --surface-2 rgba(255,255,255,.08)  --ink #ecebff  --muted #9a9ec4
        --hair rgba(255,255,255,.10)  --hair-strong rgba(255,255,255,.18)
        --ember #ff7a59  --ember-2 #ffb86b   (Focus; gradient ember→ember-2)
        --tide #4fd1c5                        (Closed, done checks)
        --lilac #a78bfa                       (Open, lifeline lived weeks)
        --glow 0 0 60px rgba(255,122,89,.22)
light:  --bg0 #f6f1e8  --bg1 #fffcf6  --surface rgba(255,255,255,.72)
        --surface-2 rgba(255,255,255,.95) --ink #17182a  --muted #666a88
        --hair rgba(23,24,42,.10)  --hair-strong rgba(23,24,42,.20)
        --ember #e4552b  --ember-2 #f29a3a  --tide #0e9a8e  --lilac #6b4fd8
        --glow 0 12px 40px rgba(228,85,43,.16)
type:   --serif "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif
        --sans  system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif
        --mono  ui-monospace,"SF Mono",Menlo,Consolas,monospace (numerals in lifeline)
scale:  1.25 ratio from 1rem; display sizes 2.44rem, 3.05rem, 3.8rem
radius: 14px cards, 999px pills; --ease 180ms cubic-bezier(.2,.7,.2,1)
```

**Background.** `body` has `--bg0` and three fixed radial gradients:
lilac at 15% 10% (alpha .22 dark / .18 light), tide at 85% 90% (alpha .14),
ember at 80% 5% (alpha .12), each 60vmax wide. A `@keyframes drift`
(40 s, alternate, infinite) moves `background-position` a few vw so the sky
turns slowly; off under `prefers-reduced-motion`. A fixed full-page
`<svg>` with `feTurbulence baseFrequency=.8 numOctaves=2` as a grain layer
at opacity .05 (dark) / .035 (light), `pointer-events: none`,
`mix-blend-mode: overlay`.

**Header.** Wordmark "Four Thousand Weeks" in serif at 1.56rem with the
word "Weeks" in the ember gradient (background-clip: text). Nav links are
pills: muted text, active pill has `--surface-2` fill and ink text. Theme
toggle at the far right: a 36px circular button with icon-sun / icon-moon /
icon-auto (three states), hair border.

**Lifeline** (the weeks band under the header, full content width, the most
distinctive element on the page). Three parts in one row (stacks on phones):
- Left: the numeral, e.g. **2,000**, serif 3.05rem with tabular nums and a
  small caption "weeks lived" in muted sans beneath.
- Middle, flexible: a **ribbon** of 200 segments (each 20 weeks), 3px wide,
  18px tall, 2px gap, rounded 1px, flex-grow so the ribbon fills the
  width. Lived segments carry a gradient from lilac (left) to ember
  (right); the current segment is ember-2 with a soft glow and a 2 s
  breathing animation (opacity .7 → 1), off under reduced motion; remaining
  segments are `--hair-strong`. Hovering the ribbon shows no tooltip; it is
  a picture, not a chart.
- Right: "about **2,000** to go" with the number in serif 1.56rem, caption
  "if you get the average" in muted.
- Without a birth date: the ribbon is all hairline and the left numeral is
  replaced by the sentence "Add your birth date to light the ribbon" (serif
  italic) linking to Settings.
- The whole band is a link to the Weeks page, no underline, cursor pointer,
  hover lifts it 1px.

**Focus band.** Heading "Focus" in serif 2.44rem, counter "3 of 3" in mono
muted. Cards are glass: `--surface` fill, 1px `--hair` border, 14px
radius, `backdrop-filter: blur(14px)`, inner highlight `inset 0 1px 0
rgba(255,255,255,.06)`. The first-marked card spans the full width above
the other two and has a **gradient border**: 2px, ember → ember-2 → lilac,
done with two backgrounds and `background-clip: padding-box, border-box`,
plus `box-shadow: var(--glow)`. Titles in serif 2.44rem (first) and
1.95rem (others), ink. Empty slots: 1.5px dashed `--hair-strong`, same
radius, with a centred faint icon-plus that opens the create dialog with
Focus preselected; label "open slot" in muted italic serif.

**Closed.** Heading "Closed" with "7 of 10". Ten slots in a 2-column grid
(5 rows) at ≥ 900px, 1 column below. Filled: `--surface` with a 3px
left rule in `--tide`, 10px radius, compact row. Empty: dashed hairline,
very quiet.

**Open page.** Same rows with a 3px left rule in `--lilac`. Stale rows show
icon-clock and "16 days" in muted; nothing else changes about them.

**Done today ledger** at the bottom: a hairline rule above, heading "Done
today" small caps, each line: tide-coloured icon-check, time in mono
muted, title in ink with a soft strike-through (`text-decoration-color:
var(--hair-strong)`), chips to the right. Quick-log line beneath as a
single ruled input.

**Floating +**: 56px circle, ember gradient, white icon-plus, `--glow`,
bottom-right with 24px margin (safe-area aware), scales 1.06 on hover.

**Dialogs and popovers**: `--bg1` fill, 1px `--hair-strong` border, 16px
radius, `backdrop` of `rgba(9,11,20,.6)` with blur 6px. Inputs: `--surface`
fill, hair border, ember focus ring. Segmented control: pill track in
`--surface`, active segment `--surface-2` with ink text; a full bucket's
segment shows its count in muted and still selectable.

**Toast**: bottom centre, `--bg1`, hair-strong border, 12px radius, ink
text, a 3px top rule in ember; slides up 8px on enter.

**Motion**: cards and rows enter with `opacity 0 → 1, translateY(6px) → 0`
over 220 ms; theme change cross-fades background colours over 300 ms. All
off under `prefers-reduced-motion`.

**Icons** (inline SVG symbols, 24 viewBox, 1.75 stroke, round caps):
plus, up (chevron), down (chevron), bucket (three stacked rounded bars),
more (three dots), grip (six dots), check, clock, sun, moon, auto
(half-filled circle), x.

**Responsive**: content max 1200px, gutters `clamp(16px, 4vw, 56px)`.
≥ 900px: Focus three cards in a row (first spans all three when marked),
Closed two columns. < 900px: single column everywhere; the lifeline stacks
numeral / ribbon / remaining. No horizontal scroll at 375px.

**Never**: red, badges, confetti, progress percentages on tasks, streak
counts. The lifeline shows weeks, never a percentage.

## Tests (tests/test_app.py, unittest only, under 12 s)

Keep every v1 test that still applies (drop the one-step rule test; adapt
move tests to the new response shape). Add:
- create into each bucket with position; default position 0
- move into full Focus without bump_id → 409 needs=bump with 3 candidates;
  with bump_id → bumped task is Closed position 0, cascade lists it;
  is_first cleared on the bumped task
- full Focus + full Closed + bump → last Closed goes to Open position 0;
  cascade has two entries
- full Focus + full Closed + full Open + bump → last Open goes to neglect
  with reason "Bumped out of Open"; cascade has three entries; all in one
  transaction (verify counts after)
- move into full Open without position → 409 needs=position; with
  position 5 → inserted at 5, later items shifted, last one neglected
- open_cap setting: PUT accepts 5..200, rejects 4 and 201 and non-ints
- renew sets touched_at and clears stale; age_days uses touched_at
- state lists carry age_days and stale for open tasks
- migration from a v1 database file (user_version 1) adds touched_at and
  keeps rows

## README

Update the "how the lists work" section for the buckets, caps, bump
cascade, aging and retire, the + dialog, icons and drag and drop, and the
theme toggle. Everything else as v1.

## Definition of done

- `python3 -m unittest -v` and `/usr/bin/python3 -m unittest` pass; the
  3.8 parse check passes; the URL grep shows only loopback addresses.
- Full flow in the browser pane on a scratch database: create into each
  bucket via the dialog; bump out of full Focus with the picker; cascade
  through full Closed and full Open; toast text correct; arrows promote
  and demote; DnD reorders; Open page, Neglect page (aging and set aside,
  retire and renew), theme toggle persists across reload, lifeline with
  and without a birth date, 375px with no horizontal scroll.
- No commits. Leave the working tree for review.
