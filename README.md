# Four Thousand Weeks

A small task app built on one idea from Oliver Burkeman's book *Four Thousand
Weeks*: an average life is about four thousand weeks, so you will never get
through everything. The app does not try to help you fit it all in. It helps
you choose a few things, let the rest go on purpose, and keep a record of what
you actually did.

It runs on your own machine, in your browser, with nothing to install beyond
Python. There are no accounts, no sync, no notifications, no streaks and no
scores. The book's ideas, and the feature each one became, are in
[docs/PRINCIPLES.md](docs/PRINCIPLES.md).

## Run it

The one requirement is **Python 3.8 or newer**. Nothing else: no pip, no
packages, no build step. Check your version with `python3 --version` (macOS,
Linux) or `python --version` (Windows).

macOS and Linux:

```sh
python3 app.py        # or ./run.sh
```

Windows:

```bat
python app.py         & rem or double-click run.bat
```

Your browser opens at `http://127.0.0.1:8787/`. Stop the app with Ctrl-C.

Options: `--port 8788` to use another port, `--db path/to/file.sqlite` to keep
the data elsewhere, `--no-browser` to skip opening a browser window.

## How the lists work

Three active lists, each with a fixed size:

- **Focus** holds three, shown large at the top of the page. Mark one as
  **first** and it sits alone above the other two. Do it before the day eats
  you.
- **Closed** holds ten, under Focus.
- **Open** holds 20 by default (5 to 200, in Settings) and has its own page.

Anything can go straight into any list, when you add it or later. When a list
is full, something has to give, and nothing is lost:

- **Full Focus**: you choose which one steps aside. It goes to the top of
  Closed.
- **Full Closed**: the newcomer takes the top and Closed's last item goes to
  the top of Open. No question asked.
- **Full Open**: you choose the position; the items below shift down and
  Open's last item goes to the Neglect page, marked "Bumped out of Open".

One move can ripple through all three lists. It happens all at once, and a
small note at the bottom of the page says what moved, for example "Fence moved
to Focus · Call Dad moved to Closed · Sourdough moved to Open."

- **Adding**: the round **+** button (or the `n` key, or an empty Focus or
  Closed slot) opens a small dialog: title, project, notes, and which list.
  Each list shows how full it is; picking a full one asks the question above
  right there. Enter adds, Esc closes.
- **Moving**: every row has a drag grip, a checkbox, and quiet icons: up and
  down move it one list, the stacked-bars icon picks any list, and the
  three-dot menu has edit, mark first, move up, move down, renew, let go and
  set aside. Drag rows to reorder them, and between Focus and Closed on the
  home page; Open reorders on its own page.
- **Done**: tick the box on any row. It moves to Done today, at the bottom of
  the page, with the time. Untick it there to undo.
- **Aging**: an item in Open for 14 days shows its age and appears on the
  Neglect page under "Aging in Open". **Renew** restarts its clock (the date
  you added it is kept); **Retire** lets it go.
- **Let go**: drop an item, with an optional reason. A real outcome, not a
  failure.
- **Set aside**: put an item on the Neglect page with a one-line reason. You
  decided not to do it well, or at all, for now. Revive it into any list, or
  retire it.
- **For its own sake**: log something you did with no task behind it, like a
  walk or an afternoon off. Counted apart and never scored.
- **Review**: once a week, if you like, one of five questions from the book,
  with that week's done, let go and neglected lists. No reminders.
- **Report**: one page per year, "What you chose in 2026": done by month, for
  its own sake, by project, what you let go, what you neglected (including
  anything bumped out of Open), your review answers, and what is still open.
- **Weeks**: enter a birth date in Settings and the lifeline at the top of the
  page fills in, with the full grid of about 4,000 weeks on the Weeks page.
  Optional and blank by default.
- **Theme**: the round button at the top right cycles system, light and dark.
  The choice is kept in this browser only.

Keyboard: `n` opens the new-item dialog, Enter saves, Esc cancels or closes.
The arrow icons and the menu's move up and move down do everything dragging
does.

## Your data

Everything lives in one SQLite file, `data/fourthousand.sqlite`, next to
`app.py`. Nothing is ever deleted: items change state, and every change is
appended to an event log.

To back up, copy the `data/` folder while the app is stopped. From the Report
page you can also download:

- **Export everything (JSON)**: every table, readable in any text editor.
- **Done list (CSV)**: date, title, project, for its own sake, age in days.

## Privacy

- The server binds to `127.0.0.1` only, so no other machine can reach it.
- Requests whose `Host` header is not `localhost`, `127.0.0.1` or `[::1]` are
  refused.
- Every response carries `Content-Security-Policy: default-src 'self'; img-src 'self' data:`,
  so the page cannot load or send anything to another site. The year-report
  page adds a `style-src` hash for its own inline styles, and nothing else.
- Writes require `Content-Type: application/json` and refuse requests from
  other origins, so another web page open in the same browser cannot change
  your lists.
- No telemetry, analytics, update checks, fonts, scripts or images from
  anywhere else. The app makes no network calls.

To check for yourself, search the code for web addresses. The only hits are
the local address:

```sh
grep -rniE "https?://" --exclude-dir=.git .
```

Then open your browser's developer tools, go to the Network tab, and use the
app. Every request goes to `127.0.0.1`.

## Tests

Standard library `unittest`, a few seconds:

```sh
python3 -m unittest -v
```

## Project layout

```
app.py              server, API, SQLite, report rendering (one file)
static/index.html   the single page
static/app.js       plain JavaScript, no framework
static/style.css    hand-written CSS, light and dark
tests/test_app.py   tests (tests/__init__.py lets unittest find them)
run.sh, run.bat     one-line launchers
docs/               PRINCIPLES.md, DECISIONS.md, SPEC.md
data/               your database (created on first run, not in git)
```

## Acknowledgement

The ideas are Oliver Burkeman's, from *Four Thousand Weeks: Time Management for
Mortals* (2021). This app paraphrases them and is not affiliated with the
author or publisher. If it is useful to you, read the book.

## License

MIT. See [LICENSE](LICENSE).
