#!/usr/bin/env python3
"""Four Thousand Weeks: a small, local task app.

Python 3.8+ standard library only. Binds 127.0.0.1, stores everything in one
SQLite file, makes no network calls. See README.md and docs/.
"""

import argparse
import base64
import contextlib
import csv
import datetime
import hashlib
import html
import io
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.realpath(os.path.join(HERE, "static"))
DEFAULT_DB = os.path.join(HERE, "data", "fourthousand.sqlite")
MAX_BODY = 64 * 1024
WEEKS_TOTAL = 4000

CSP = "default-src 'self'; img-src 'self' data:"
ALLOWED_HOST = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\])(:\d{1,5})?$")
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}

STATES = ("open", "closed", "focus", "neglect", "done", "let_go")
TIERS = ("open", "closed", "focus")
LIST_STATES = ("open", "closed", "focus", "neglect")
REVIVABLE = ("neglect", "let_go", "done")
LABEL = {
    "open": "Open",
    "closed": "Closed",
    "focus": "Focus",
    "neglect": "Neglect",
    "done": "Done",
    "let_go": "Let go",
}
STAMP = {
    "closed": "closed_at",
    "focus": "focused_at",
    "done": "done_at",
    "let_go": "let_go_at",
    "neglect": "neglect_at",
}
SETTING_DEFAULTS = {"closed_cap": "10", "focus_cap": "3", "open_cap": "20", "stale_days": "14"}
OPEN_CAP_MIN, OPEN_CAP_MAX = 5, 200
BUMPED_OUT = "Bumped out of Open"
# Where the item that falls off the end of a full list goes.
OVERFLOW = {"focus": "closed", "closed": "open", "open": "neglect"}

# The five questions from the book's last chapter, in this app's own words.
QUESTIONS = (
    "Where are you choosing comfort when a little discomfort is what is called for?",
    "Are you holding yourself to a standard nobody could meet?",
    "Where have you not yet accepted who you actually are?",
    "What are you putting off until you feel ready?",
    "What would you do if you no longer needed to see the results?",
)

MIGRATIONS = [
    [
        """CREATE TABLE tasks(
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL CHECK (state IN ('open','closed','focus','neglect','done','let_go')),
            position INTEGER NOT NULL DEFAULT 0,
            is_first INTEGER NOT NULL DEFAULT 0,
            for_its_own_sake INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            closed_at TEXT, focused_at TEXT, done_at TEXT, let_go_at TEXT, neglect_at TEXT
        )""",
        """CREATE TABLE events(
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id),
            kind TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            detail TEXT NOT NULL DEFAULT '',
            at TEXT NOT NULL
        )""",
        """CREATE TABLE reviews(
            week TEXT PRIMARY KEY,
            question_index INTEGER NOT NULL,
            answer TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE INDEX tasks_state ON tasks(state, position)",
        "CREATE INDEX events_task ON events(task_id)",
    ],
    [
        "ALTER TABLE tasks ADD COLUMN touched_at TEXT",  # set by Renew; NULL otherwise
    ],
]


class ApiError(Exception):
    def __init__(self, status, message, extra=None):
        Exception.__init__(self, message)
        self.status = status
        self.message = message
        self.extra = extra or {}


# ---------------------------------------------------------------- time


def now():
    return datetime.datetime.now().astimezone()


def stamp(dt=None):
    return (dt or now()).isoformat(timespec="seconds")


def local_date(ts):
    """Stored timestamps are local time, so the first ten characters are the local date."""
    return datetime.date.fromisoformat(ts[:10])


def iso_week(d):
    year, week = d.isocalendar()[0], d.isocalendar()[1]
    return "%04d-W%02d" % (year, week)


def parse_week(week):
    m = re.match(r"\A[0-9]{4}-W[0-9]{2}\Z", week or "")
    if not m:
        raise ApiError(400, "Week must look like 2026-W44.")
    year, number = int(week[:4]), int(week[6:])
    if not 1970 <= year <= 2200 or not 1 <= number <= 53:
        raise ApiError(400, "That week does not exist.")
    try:
        monday = datetime.date.fromisocalendar(year, number, 1)
    except ValueError:
        raise ApiError(400, "That week does not exist.")
    return monday, monday + datetime.timedelta(days=6)


def question_index(week):
    return int(week.split("-W")[1]) % 5


def parse_date(value, what):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(400, "%s must be a date like 2026-01-31." % what)


# ---------------------------------------------------------------- database


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def transaction(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def init_db(path):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number in range(version, len(MIGRATIONS)):
            with transaction(conn):
                for statement in MIGRATIONS[number]:
                    conn.execute(statement)
                conn.execute("PRAGMA user_version = %d" % (number + 1))
    finally:
        conn.close()


def get_settings(conn):
    values = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    return {
        "closed_cap": int(values["closed_cap"]),
        "focus_cap": int(values["focus_cap"]),
        "open_cap": int(values["open_cap"]),
        "stale_days": int(values["stale_days"]),
        "birth_date": values.get("birth_date") or None,
    }


def caps_of(settings):
    return {"focus": settings["focus_cap"], "closed": settings["closed_cap"], "open": settings["open_cap"]}


def add_event(conn, task_id, kind, from_state, to_state, detail, at):
    conn.execute(
        "INSERT INTO events(task_id, kind, from_state, to_state, detail, at) VALUES (?,?,?,?,?,?)",
        (task_id, kind, from_state, to_state, detail, at),
    )


def get_task(conn, task_id):
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ApiError(404, "No such task.")
    return row


def next_position(conn, state):
    return conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE state = ?", (state,)
    ).fetchone()[0]


def task_json(row, stale_days=None, current=None):
    """age_days and stale are only meaningful for Open items: days since Renew, else since creation."""
    task = dict(row)
    task["is_first"] = bool(task["is_first"])
    task["for_its_own_sake"] = bool(task["for_its_own_sake"])
    task["stale"] = False
    task["age_days"] = None
    if task["state"] == "open":
        if stale_days is None:
            stale_days = int(SETTING_DEFAULTS["stale_days"])
        since = task.get("touched_at") or task["created_at"]
        task["age_days"] = ((current or now()).date() - local_date(since)).days
        task["stale"] = task["age_days"] >= stale_days
    return task


def quick_log_ids(conn):
    rows = conn.execute("SELECT task_id FROM events WHERE kind = 'create' AND to_state = 'done'")
    return set(r[0] for r in rows)


def update_task(conn, task_id, fields):
    names = sorted(fields)
    conn.execute(
        "UPDATE tasks SET %s WHERE id = ?" % ", ".join("%s = ?" % n for n in names),
        [fields[n] for n in names] + [task_id],
    )


# ---------------------------------------------------------------- validation


def check_text(value):
    """Reject strings that cannot be stored as UTF-8 (lone surrogates from JSON escapes)."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, "Text contains invalid characters.")
    return value


def want_text(body, key, required=False):
    if key not in body:
        if required:
            raise ApiError(400, "%s is required." % key.capitalize())
        return None
    value = body[key]
    if not isinstance(value, str):
        raise ApiError(400, "%s must be text." % key.capitalize())
    return check_text(value).strip()


def parse_id(value, status):
    """A task id: ASCII digits (at most 18) or a JSON integer, between 1 and 2**53."""
    message = "No such task." if status == 404 else "ids must be a list of task ids."
    if isinstance(value, str):
        if not 0 < len(value) <= 18 or not all("0" <= c <= "9" for c in value):
            raise ApiError(status, message)
        value = int(value)
    elif isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(status, message)
    if not 1 <= value <= 2 ** 53:
        raise ApiError(status, message)
    return value


def want_bool(body, key):
    if key not in body:
        return None
    if not isinstance(body[key], bool):
        raise ApiError(400, "%s must be true or false." % key)
    return body[key]


def want_position(body):
    """A 0-based place in a list (0 = top); missing or null means "not given"."""
    value = body.get("position")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100000:
        raise ApiError(400, "Position must be a whole number, 0 or more.")
    return value


def want_bump(body):
    value = body.get("bump_id")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 2 ** 53:
        raise ApiError(400, "bump_id must be a task id.")
    return value


def only_keys(body, allowed):
    for key in body:
        if key not in allowed:
            raise ApiError(400, "Unknown field: %s." % check_text(key))


# ---------------------------------------------------------------- API handlers


def api_state(ctx):
    conn = ctx.conn
    settings = get_settings(conn)
    current = now()
    lists = {}
    for state in LIST_STATES:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE state = ? ORDER BY position, id", (state,)
        ).fetchall()
        lists[state] = [task_json(r, settings["stale_days"], current) for r in rows]
    today = current.date().isoformat()
    today_done = [
        task_json(r)
        for r in conn.execute(
            "SELECT * FROM tasks WHERE state = 'done' AND substr(done_at, 1, 10) = ? ORDER BY done_at, id",
            (today,),
        )
    ]
    notes = {}
    projects = set(t["project"] for t in lists["focus"] if t["project"])
    if len(projects) > 1:
        notes["serialize"] = "%d projects in focus" % len(projects)
    week_number = None
    if settings["birth_date"]:
        born = datetime.date.fromisoformat(settings["birth_date"])
        week_number = (current.date() - born).days // 7
    return {
        "settings": settings,
        "caps": caps_of(settings),
        "week_number": week_number,
        "notes": notes,
        "lists": lists,
        "today_done": today_done,
        "today": today,
    }


def api_create(ctx):
    body = ctx.body
    only_keys(body, ("title", "notes", "project", "state", "position", "bump_id", "for_its_own_sake"))
    title = want_text(body, "title", required=True)
    if not title:
        raise ApiError(400, "Title is required.")
    state = body.get("state", "open")
    if not isinstance(state, str) or state not in TIERS + ("done",):
        raise ApiError(400, "New items go to Focus, Closed or Open, or straight to Done.")
    notes = want_text(body, "notes") or ""
    project = want_text(body, "project") or ""
    own_sake = want_bool(body, "for_its_own_sake") or False
    position = want_position(body)
    bump_id = want_bump(body)
    ts = stamp()
    conn = ctx.conn
    cascade = []
    with transaction(conn):
        settings = get_settings(conn)
        if state in TIERS:
            check_room(conn, settings, state, None, position, bump_id)
        cur = conn.execute(
            "INSERT INTO tasks(title, notes, project, state, position, for_its_own_sake, created_at, done_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                title,
                notes,
                project,
                state,
                -1 if state in TIERS else next_position(conn, state),
                1 if own_sake else 0,
                ts,
                ts if state == "done" else None,
            ),
        )
        task_id = cur.lastrowid
        add_event(conn, task_id, "create", None, state, "", ts)
        if state in TIERS:
            place(conn, settings, get_task(conn, task_id), None, state, position, bump_id, ts, cascade)
        task = task_json(get_task(conn, task_id), settings["stale_days"])
    return 201, {"task": task, "cascade": cascade}


def api_edit(ctx, task_id):
    task_id = parse_id(task_id, 404)
    body = ctx.body
    only_keys(body, ("title", "notes", "project", "is_first", "for_its_own_sake"))
    conn = ctx.conn
    ts = stamp()
    with transaction(conn):
        task = get_task(conn, int(task_id))
        fields = {}
        title = want_text(body, "title")
        if title is not None:
            if not title:
                raise ApiError(400, "Title cannot be empty.")
            fields["title"] = title
        for key in ("notes", "project"):
            value = want_text(body, key)
            if value is not None:
                fields[key] = value
        own_sake = want_bool(body, "for_its_own_sake")
        if own_sake is not None:
            fields["for_its_own_sake"] = 1 if own_sake else 0
        first = want_bool(body, "is_first")
        if first is not None:
            if first and task["state"] != "focus":
                raise ApiError(400, "Only a Focus item can be first.")
            if first:
                for other in conn.execute(
                    "SELECT id FROM tasks WHERE is_first = 1 AND id != ?", (task["id"],)
                ).fetchall():
                    conn.execute("UPDATE tasks SET is_first = 0 WHERE id = ?", (other["id"],))
                    add_event(conn, other["id"], "edit", task["state"], task["state"], '{"is_first": 0}', ts)
            fields["is_first"] = 1 if first else 0
        if fields:
            update_task(conn, task["id"], fields)
            add_event(conn, task["id"], "edit", task["state"], task["state"],
                      json.dumps(fields, sort_keys=True), ts)
    return task_json(get_task(conn, int(task_id)))


def check_move(from_state, to, reason):
    if not isinstance(to, str) or to not in STATES:
        raise ApiError(400, "Unknown list.")
    if to == from_state:
        raise ApiError(400, "It is already in %s." % LABEL[to])
    if to in TIERS and from_state in TIERS + ("neglect",):
        return
    if to == "open" and from_state in ("let_go", "done"):
        return
    if to in ("done", "let_go") and from_state in TIERS + ("neglect",):
        return
    if to == "neglect" and from_state in TIERS:
        if not reason:
            raise ApiError(400, "Neglecting on purpose needs a one-line reason.")
        return
    raise ApiError(400, "%s items cannot move to %s." % (LABEL[from_state], LABEL[to]))


def api_move(ctx, task_id):
    task_id = parse_id(task_id, 404)
    body = ctx.body
    only_keys(body, ("to", "position", "bump_id", "reason"))
    to = body.get("to")
    reason = want_text(body, "reason") or ""
    position = want_position(body)
    bump_id = want_bump(body)
    conn = ctx.conn
    ts = stamp()
    cascade = []
    with transaction(conn):
        task = get_task(conn, task_id)
        from_state = task["state"]
        check_move(from_state, to, reason)
        settings = get_settings(conn)
        if to in TIERS:
            check_room(conn, settings, to, task["id"], position, bump_id)
            add_event(conn, task["id"], "move", from_state, to, "", ts)
            place(conn, settings, task, from_state, to, position, bump_id, ts, cascade)
        else:
            fields = {
                "state": to,
                "position": next_position(conn, to),
                "reason": reason if to in ("neglect", "let_go") else "",
                STAMP[to]: ts,
            }
            if from_state == "focus":
                fields["is_first"] = 0
            update_task(conn, task["id"], fields)
            add_event(conn, task["id"], "move", from_state, to, reason, ts)
        result = task_json(get_task(conn, task_id), settings["stale_days"])
    return {"task": result, "cascade": cascade}


def bucket_ids(conn, state, exclude):
    rows = conn.execute("SELECT id FROM tasks WHERE state = ? ORDER BY position, id", (state,))
    return [r[0] for r in rows if r[0] != exclude]


def check_room(conn, settings, to, task_id, position, bump_id):
    """Refuse, before anything changes, a placement that needs an answer first.

    Full Focus needs bump_id (which one steps aside); a direct move into full Open
    needs a position. Full Closed needs nothing: it overflows on its own."""
    ids = bucket_ids(conn, to, task_id)
    cap = caps_of(settings)[to]
    if len(ids) < cap:
        return
    if to == "focus":
        if bump_id is None:
            candidates = [
                {"id": r["id"], "title": r["title"]}
                for r in conn.execute(
                    "SELECT id, title FROM tasks WHERE state = 'focus' ORDER BY is_first DESC, position, id")
            ]
            raise ApiError(409, "Focus is full.", {"needs": "bump", "candidates": candidates})
        if bump_id not in ids:
            raise ApiError(400, "bump_id must be one of the Focus items.")
    elif to == "open":
        if position is None:
            raise ApiError(409, "Open is full.", {"needs": "position", "cap": cap})
        if position > cap - 1:
            raise ApiError(400, "Position must be between 0 and %d." % (cap - 1))


def place(conn, settings, task, from_state, to, position, bump_id, ts, cascade):
    """Put `task` into the active list `to` at `position` (default top) and run the cascade.

    A full Focus sends bump_id to the top of Closed; a full Closed takes the newcomer at
    `position` and sends its last item to the top of Open; a full Open sends its last item
    to Neglect. Runs inside the caller's transaction; `cascade` collects the knock-on
    moves in the order they happen. check_room() has already validated the request."""
    ids = bucket_ids(conn, to, task["id"])
    index = position or 0
    out = None
    if len(ids) >= caps_of(settings)[to]:
        if to == "focus":
            out = bump_id
            ids.remove(bump_id)
        else:
            # Full Closed or Open: the previous last item leaves. Popping it first and then
            # inserting at min(index, cap - 1) is the same as inserting at that clamped index
            # and evicting the old last after; a position of cap or more means "last".
            out = ids.pop()
    ids.insert(min(index, len(ids)), task["id"])
    fields = {"state": to, "reason": ""}
    if to in STAMP:
        fields[STAMP[to]] = ts
    if from_state == "focus":
        fields["is_first"] = 0
    if from_state in REVIVABLE:
        fields[STAMP[from_state]] = None
    update_task(conn, task["id"], fields)
    for i, task_id in enumerate(ids):
        conn.execute("UPDATE tasks SET position = ? WHERE id = ? AND position != ?", (i, task_id, i))
    if out is None:
        return
    leaving = get_task(conn, out)
    target = OVERFLOW[to]
    cascade.append({"id": out, "title": leaving["title"], "from": to, "to": target})
    if target == "neglect":
        update_task(conn, out, {"state": "neglect", "reason": BUMPED_OUT, "neglect_at": ts,
                                "position": next_position(conn, "neglect")})
        add_event(conn, out, "move", to, target, BUMPED_OUT, ts)
    else:
        add_event(conn, out, "move", to, target, "bumped", ts)
        place(conn, settings, leaving, to, target, 0, None, ts, cascade)


def api_renew(ctx, task_id):
    task_id = parse_id(task_id, 404)
    only_keys(ctx.body, ())
    conn = ctx.conn
    ts = stamp()
    with transaction(conn):
        task = get_task(conn, task_id)
        if task["state"] != "open":
            raise ApiError(400, "Only an Open item can be renewed.")
        update_task(conn, task_id, {"touched_at": ts})
        add_event(conn, task_id, "renew", "open", "open", "", ts)
        result = task_json(get_task(conn, task_id), get_settings(conn)["stale_days"])
    return result


def api_reorder(ctx):
    body = ctx.body
    only_keys(body, ("state", "ids"))
    state = body.get("state")
    ids = body.get("ids")
    if state not in LIST_STATES:
        raise ApiError(400, "Reorder works on open, closed, focus or neglect.")
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError(400, "ids must be a list of task ids.")
    ids = [parse_id(i, 400) for i in ids]
    if len(set(ids)) != len(ids):
        raise ApiError(400, "Each id may appear once.")
    conn = ctx.conn
    ts = stamp()
    with transaction(conn):
        for task_id in ids:
            row = conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None or row["state"] != state:
                raise ApiError(400, "Task %d is not in %s." % (task_id, LABEL[state]))
        for position, task_id in enumerate(ids):
            old = conn.execute("SELECT position FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
            if old != position:
                conn.execute("UPDATE tasks SET position = ? WHERE id = ?", (position, task_id))
                add_event(conn, task_id, "reorder", state, state, "%d -> %d" % (old, position), ts)
    return {"ok": True}


def api_done(ctx):
    params = ctx.query
    sql = "SELECT * FROM tasks WHERE state = 'done'"
    args = []
    start = params.get("from", [None])[0]
    end = params.get("to", [None])[0]
    if start:
        args.append(parse_date(start, "from").isoformat())
        sql += " AND substr(done_at, 1, 10) >= ?"
    if end:
        args.append(parse_date(end, "to").isoformat())
        sql += " AND substr(done_at, 1, 10) <= ?"
    rows = ctx.conn.execute(sql + " ORDER BY done_at, id", args).fetchall()
    return {"from": start, "to": end, "done": [task_json(r) for r in rows]}


def in_range(conn, state, monday, sunday):
    column = STAMP[state]
    rows = conn.execute(
        "SELECT * FROM tasks WHERE state = ? AND substr(%s, 1, 10) BETWEEN ? AND ? ORDER BY %s, id"
        % (column, column),
        (state, monday.isoformat(), sunday.isoformat()),
    )
    return [task_json(r) for r in rows]


def api_review_get(ctx):
    week = ctx.query.get("week", [None])[0] or iso_week(now().date())
    monday, sunday = parse_week(week)
    conn = ctx.conn
    row = conn.execute("SELECT answer FROM reviews WHERE week = ?", (week,)).fetchone()
    index = question_index(week)
    past = [
        {"week": r["week"], "question": QUESTIONS[r["question_index"]], "answer": r["answer"]}
        for r in conn.execute(
            "SELECT * FROM reviews WHERE answer != '' AND week != ? ORDER BY week DESC", (week,)
        )
    ]
    return {
        "week": week,
        "question_index": index,
        "question": QUESTIONS[index],
        "answer": row["answer"] if row else "",
        "done": in_range(conn, "done", monday, sunday),
        "let_go": in_range(conn, "let_go", monday, sunday),
        "neglect": in_range(conn, "neglect", monday, sunday),
        "past": past,
    }


def api_review_put(ctx, week):
    parse_week(week)
    only_keys(ctx.body, ("answer",))
    answer = want_text(ctx.body, "answer")
    if answer is None:
        raise ApiError(400, "Answer is required (it may be empty).")
    ts = stamp()
    conn = ctx.conn
    with transaction(conn):
        conn.execute(
            "INSERT OR IGNORE INTO reviews(week, question_index, answer, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (week, question_index(week), answer, ts, ts),
        )
        conn.execute("UPDATE reviews SET answer = ?, updated_at = ? WHERE week = ?", (answer, ts, week))
    return {"week": week, "question_index": question_index(week),
            "question": QUESTIONS[question_index(week)], "answer": answer}


def api_settings_get(ctx):
    return get_settings(ctx.conn)


def api_settings_put(ctx):
    only_keys(ctx.body, ("birth_date", "open_cap"))
    value = want_text(ctx.body, "birth_date")
    born = None
    if value:
        born = parse_date(value, "Birth date")
        if born > now().date():
            raise ApiError(400, "Birth date cannot be in the future.")
    open_cap = ctx.body.get("open_cap")
    if "open_cap" in ctx.body and (isinstance(open_cap, bool) or not isinstance(open_cap, int)
                                   or not OPEN_CAP_MIN <= open_cap <= OPEN_CAP_MAX):
        raise ApiError(400, "Open holds a whole number from %d to %d." % (OPEN_CAP_MIN, OPEN_CAP_MAX))
    conn = ctx.conn
    with transaction(conn):
        if value == "":
            conn.execute("DELETE FROM settings WHERE key = 'birth_date'")
        elif born is not None:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('birth_date', ?)",
                         (born.isoformat(),))
        if "open_cap" in ctx.body:
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('open_cap', ?)", (str(open_cap),))
    return get_settings(conn)


def api_weeks(ctx):
    born = get_settings(ctx.conn)["birth_date"]
    if not born:
        return {"birth_date": None}
    today = now().date()
    return {
        "birth_date": born,
        "week_number": (today - datetime.date.fromisoformat(born)).days // 7,
        "weeks_total": WEEKS_TOTAL,
        "today": today.isoformat(),
    }


# ---------------------------------------------------------------- report


def build_report(conn, year):
    prefix = "%04d" % year
    today = now().date()
    months = [
        {"month": m, "done": 0, "let_go": 0, "neglect": 0, "for_its_own_sake": 0}
        for m in range(1, 13)
    ]
    done = conn.execute(
        "SELECT * FROM tasks WHERE state = 'done' AND substr(done_at, 1, 4) = ? ORDER BY done_at, id",
        (prefix,),
    ).fetchall()
    let_go = conn.execute(
        "SELECT * FROM tasks WHERE state = 'let_go' AND substr(let_go_at, 1, 4) = ? ORDER BY let_go_at, id",
        (prefix,),
    ).fetchall()
    neglected = conn.execute(
        "SELECT * FROM tasks WHERE state = 'neglect' AND substr(neglect_at, 1, 4) = ? ORDER BY neglect_at, id",
        (prefix,),
    ).fetchall()
    logs = quick_log_ids(conn)
    projects = {}
    ages = []
    for t in done:
        month = months[local_date(t["done_at"]).month - 1]
        month["done"] += 1
        if t["for_its_own_sake"]:
            month["for_its_own_sake"] += 1
        projects[t["project"]] = projects.get(t["project"], 0) + 1
        if t["id"] not in logs:
            ages.append((local_date(t["done_at"]) - local_date(t["created_at"])).days)
    for t in let_go:
        months[local_date(t["let_go_at"]).month - 1]["let_go"] += 1
    for t in neglected:
        months[local_date(t["neglect_at"]).month - 1]["neglect"] += 1
    by_project = sorted(
        ({"project": p or "no project", "done": n, "_blank": p == ""} for p, n in projects.items()),
        key=lambda x: (x["_blank"], -x["done"], x["project"].lower()),
    )
    for item in by_project:
        del item["_blank"]
    ages.sort()
    age = {"count": len(ages), "median": None, "p90": None}
    if ages:
        age["median"] = statistics.median(ages)
        age["p90"] = ages[max(0, math.ceil(0.9 * len(ages)) - 1)]
    reviews = [
        {"week": r["week"], "question": QUESTIONS[r["question_index"]], "answer": r["answer"]}
        for r in conn.execute(
            "SELECT * FROM reviews WHERE week LIKE ? AND answer != '' ORDER BY week", (prefix + "-W%",)
        )
    ]
    still_open = [
        {"id": r["id"], "title": r["title"], "project": r["project"],
         "age_days": (today - local_date(r["created_at"])).days}
        for r in conn.execute("SELECT * FROM tasks WHERE state = 'open' ORDER BY created_at, id LIMIT 10")
    ]

    def outcome(rows, column):
        return [{"title": r["title"], "project": r["project"],
                 "date": r[column][:10], "reason": r["reason"]} for r in rows]

    return {
        "year": year,
        "months": months,
        "by_project": by_project,
        "age_at_done_days": age,
        "neglected": outcome(neglected, "neglect_at"),
        "let_go": outcome(let_go, "let_go_at"),
        "reviews": reviews,
        "still_open": still_open,
        "totals": {
            "done": len(done),
            "for_its_own_sake": sum(1 for t in done if t["for_its_own_sake"]),
            "let_go": len(let_go),
            "neglect": len(neglected),
        },
        "generated_at": stamp(),
    }


REPORT_CSS = """
:root { --paper: #f5f0e6; --ink: #1f1b16; --muted: #776e61; --hair: #ddd3c2; --accent: #96610f; }
@media (prefers-color-scheme: dark) {
  :root { --paper: #1c1916; --ink: #ece4d4; --muted: #a69c8b; --hair: #3a342c; --accent: #d9a44a; }
}
body { font: 1rem/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink);
       background: var(--paper); max-width: 70ch; margin: 3rem auto 4rem; padding: 0 16px; }
h1 { font: 600 2.441rem/1.15 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; margin: 0 0 0.75rem; }
h2 { font: 600 1.25rem/1.3 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
     margin: 2.5rem 0 0.75rem; padding-bottom: 0.35rem; border-bottom: 1px solid var(--hair); }
.lede { font: 1.25rem/1.5 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }
.quiet { color: var(--muted); font-size: 0.8rem; }
ul { padding: 0; list-style: none; }
li { padding: 0.35rem 0; border-bottom: 1px solid var(--hair); }
.bar { display: grid; grid-template-columns: 2.5rem 1fr 2.5rem; align-items: center; gap: 0.75rem;
       font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.bar svg { width: 100%; height: 6px; display: block; }
.bar rect { fill: var(--ink); }
.bar .n { text-align: right; }
.answer { font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; white-space: pre-wrap; }
"""
REPORT_CSP = "%s; style-src 'sha256-%s'" % (
    CSP, base64.b64encode(hashlib.sha256(REPORT_CSS.encode("utf-8")).digest()).decode("ascii"))
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def bars(months, key):
    """One thin horizontal rule per month; its length is the count."""
    scale = max([m[key] for m in months] + [30])
    rows = []
    for m in months:
        rows.append(
            "<div class=\"bar\"><span>%s</span><svg viewBox=\"0 0 %d 6\" preserveAspectRatio=\"none\""
            " aria-hidden=\"true\"><rect y=\"2\" height=\"2\" width=\"%d\"></rect></svg>"
            "<span class=\"n\">%d</span></div>" % (MONTHS[m["month"] - 1], scale, m[key], m[key]))
    return "".join(rows)


def render_report_html(report):
    e = html.escape
    year = report["year"]
    totals = report["totals"]
    parts = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
        "<title>What you chose in %d</title><style>%s</style></head><body>" % (year, REPORT_CSS),
        "<h1>What you chose in %d</h1>" % year,
        "<p class=\"lede\">%d done, of which %d for its own sake. %d let go. %d neglected on purpose.</p>"
        % (totals["done"], totals["for_its_own_sake"], totals["let_go"], totals["neglect"]),
        "<h2>Done, by month</h2>",
        bars(report["months"], "done"),
    ]
    age = report["age_at_done_days"]
    if age["count"]:
        parts.append("<p class=\"quiet\">From adding to done: median %s days, 90th percentile %s days.</p>"
                     % (age["median"], age["p90"]))
    parts.append("<h2>For its own sake</h2>")
    parts.append(bars(report["months"], "for_its_own_sake"))

    def items(rows, render, empty):
        if not rows:
            return "<p class=\"quiet\">%s</p>" % empty
        return "<ul>%s</ul>" % "".join("<li>%s</li>" % render(r) for r in rows)

    def with_reason(r):
        text = "%s <span class=\"quiet\">%s</span>" % (e(r["title"]), e(r["date"]))
        if r["reason"]:
            text += " &mdash; %s" % e(r["reason"])
        return text

    parts += [
        "<h2>By project</h2>",
        items(report["by_project"], lambda r: "%s: %d" % (e(r["project"]), r["done"]), "Nothing done yet."),
        "<h2>What you let go</h2>",
        items(report["let_go"], with_reason, "Nothing let go."),
        "<h2>What you neglected on purpose</h2>",
        items(report["neglected"], with_reason, "Nothing on the neglect shelf."),
        "<h2>Review answers</h2>",
        items(report["reviews"],
              lambda r: "<strong>%s</strong> <span class=\"quiet\">%s</span><div class=\"answer\">%s</div>"
              % (e(r["week"]), e(r["question"]), e(r["answer"])),
              "No answers written."),
        "<h2>Still open</h2>",
        items(report["still_open"],
              lambda r: "%s <span class=\"quiet\">%d days</span>" % (e(r["title"]), r["age_days"]),
              "Open is empty."),
        "<p class=\"quiet\">Made on this machine from your own data, %s.</p>" % e(report["generated_at"][:10]),
        "</body></html>",
    ]
    return "".join(parts)


def report_year(year):
    year = int(year)
    if year < 1900 or year > 9999:
        raise ApiError(400, "Pick a sensible year.")
    return year


def api_report_json(ctx, year):
    return build_report(ctx.conn, report_year(year))


def api_report_html(ctx, year):
    year = report_year(year)
    page = render_report_html(build_report(ctx.conn, year))
    return Raw(200, page.encode("utf-8"), "text/html; charset=utf-8", csp=REPORT_CSP)


# ---------------------------------------------------------------- exports


def api_export_json(ctx):
    conn = ctx.conn
    data = {
        "exported_at": stamp(),
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
    }
    for table in ("tasks", "events", "reviews", "settings"):
        data[table] = [dict(r) for r in conn.execute("SELECT * FROM %s ORDER BY rowid" % table)]
    body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    return Raw(200, body, "application/json; charset=utf-8",
               disposition='attachment; filename="fourthousand-export.json"')


def api_export_csv(ctx):
    conn = ctx.conn
    logs = quick_log_ids(conn)
    out = io.StringIO()
    out.write("\ufeff")  # byte order mark, so spreadsheet programs read the file as UTF-8
    writer = csv.writer(out)

    def cell(value):
        """Keep spreadsheets from running a title like =HYPERLINK(...) as a formula."""
        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
        return value

    writer.writerow(["date", "title", "project", "for_its_own_sake", "age_days"])
    for t in conn.execute("SELECT * FROM tasks WHERE state = 'done' ORDER BY done_at, id"):
        age = "" if t["id"] in logs else (local_date(t["done_at"]) - local_date(t["created_at"])).days
        writer.writerow([cell(v) for v in (t["done_at"][:10], t["title"], t["project"], t["for_its_own_sake"], age)])
    return Raw(200, out.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
               disposition='attachment; filename="done.csv"')


# ---------------------------------------------------------------- HTTP


class Raw(object):
    def __init__(self, status, body, content_type, csp=CSP, disposition=None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.csp = csp
        self.disposition = disposition


class Context(object):
    def __init__(self, conn, query, body):
        self.conn = conn
        self.query = query
        self.body = body


ROUTES = [
    ("GET", r"/api/state", api_state),
    ("POST", r"/api/tasks", api_create),
    ("POST", r"/api/tasks/reorder", api_reorder),
    ("PATCH", r"/api/tasks/(\d+)", api_edit),
    ("POST", r"/api/tasks/(\d+)/move", api_move),
    ("POST", r"/api/tasks/(\d+)/renew", api_renew),
    ("GET", r"/api/done", api_done),
    ("GET", r"/api/review", api_review_get),
    ("PUT", r"/api/review/(\d{4}-W\d{2})", api_review_put),
    ("GET", r"/api/settings", api_settings_get),
    ("PUT", r"/api/settings", api_settings_put),
    ("GET", r"/api/weeks", api_weeks),
    ("GET", r"/api/report/(\d{4})", api_report_json),
    ("GET", r"/api/report/(\d{4})\.html", api_report_html),
    ("GET", r"/api/export\.json", api_export_json),
    ("GET", r"/api/export/done\.csv", api_export_csv),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "FourThousandWeeks"
    sys_version = ""
    timeout = 30  # seconds; a stalled request body does not hold a thread forever
    _csp = None

    def log_message(self, format, *args):
        pass  # no request log: nothing about your tasks is written anywhere but the database

    def end_headers(self):
        self.send_header("Content-Security-Policy", self._csp or CSP)
        self._csp = None
        BaseHTTPRequestHandler.end_headers(self)

    def send_raw(self, raw):
        self.send_response(raw.status)
        self.send_header("Content-Type", raw.content_type)
        self.send_header("Content-Length", str(len(raw.body)))
        self.send_header("Cache-Control", "no-store")
        if raw.disposition:
            self.send_header("Content-Disposition", raw.disposition)
        self._csp = raw.csp
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw.body)

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_raw(Raw(status, body, "application/json; charset=utf-8"))

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_PUT(self):
        self.dispatch("PUT")

    def dispatch(self, method):
        try:
            if not ALLOWED_HOST.match(self.headers.get("Host", "")):
                raise ApiError(400, "This app only answers to localhost.")
            url = urlsplit(self.path)
            if not url.path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(404, "Not found.")
                return self.send_raw(static_file(url.path))
            body = self.read_body() if method in ("POST", "PATCH", "PUT") else {}
            for route_method, pattern, func in ROUTES:
                m = re.match("^%s$" % pattern, url.path)
                if m and route_method == method:
                    return self.run_api(func, m.groups(), parse_qs(url.query), body)
            raise ApiError(404, "Not found.")
        except ApiError as err:
            payload = {"error": err.message}
            payload.update(err.extra)
            self.send_json(err.status, payload)
        except sqlite3.OperationalError:
            self.send_json(503, {"error": "The database is busy. Try again."})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"error": "Something went wrong on this machine. See the terminal."})

    def check_write_headers(self):
        """Writes must be JSON from this app's own page, never from another site."""
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise ApiError(415, "Send JSON (Content-Type: application/json).")
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            raise ApiError(403, "Cross-site requests are not allowed.")
        origin = self.headers.get("Origin")
        if origin is not None and not ALLOWED_HOST.match(urlsplit(origin).netloc):
            raise ApiError(403, "Cross-site requests are not allowed.")

    def read_body(self):
        self.check_write_headers()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Bad Content-Length.")
        if length < 0:
            raise ApiError(400, "Bad Content-Length.")
        if length > MAX_BODY:
            self.close_connection = True
            remaining = min(length, 1024 * 1024)  # drain some, so a browser can read the reply
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            raise ApiError(400, "Request is too large (64 KiB at most).")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ApiError(400, "Body must be JSON.")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")
        return body

    def run_api(self, func, groups, query, body):
        conn = connect(self.server.db_path)
        try:
            result = func(Context(conn, query, body), *groups)
        finally:
            conn.close()
        if isinstance(result, Raw):
            return self.send_raw(result)
        status = 200
        if isinstance(result, tuple):
            status, result = result
        self.send_json(status, result)


def static_file(path):
    if path == "/":
        rel = "index.html"
    elif path.startswith("/static/"):
        rel = unquote(path[len("/static/"):])
    else:
        raise ApiError(404, "Not found.")
    try:
        full = os.path.realpath(os.path.join(STATIC_DIR, rel))
        inside = os.path.commonpath([full, STATIC_DIR]) == STATIC_DIR
    except ValueError:
        inside = False
    ext = os.path.splitext(full)[1].lower() if inside else ""
    if not inside or ext not in STATIC_TYPES or not os.path.isfile(full):
        raise ApiError(404, "Not found.")
    with open(full, "rb") as f:
        return Raw(200, f.read(), STATIC_TYPES[ext])


def make_server(db_path, port=8787):
    init_db(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler, bind_and_activate=False)
    if sys.platform == "win32":
        server.allow_reuse_address = False  # on Windows it would let two copies share one port
    try:
        server.server_bind()
        server.server_activate()
    except BaseException:
        server.server_close()
        raise
    server.daemon_threads = True
    server.db_path = db_path
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Four Thousand Weeks: a local task app.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite file (default: data/fourthousand.sqlite)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # a console that is not UTF-8 must not crash startup
    except AttributeError:
        pass
    try:
        server = make_server(args.db, args.port)
    except OSError as err:
        print("Could not start on port %d: %s" % (args.port, err), file=sys.stderr)
        print("Try another port, for example: --port 8788", file=sys.stderr)
        return 1
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("Four Thousand Weeks is running at %s" % url, flush=True)
    print("Data: %s" % os.path.abspath(args.db), flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.3, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
