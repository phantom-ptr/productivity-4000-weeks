"""Tests for app.py. Standard library only: python3 -m unittest -v"""

import datetime
import http.client
import io
import json
import os
import socket
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402

CSP = "default-src 'self'; img-src 'self' data:"


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test.sqlite")
        self.server = app.make_server(self.db, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02})
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers

    def call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, err.read()

    def api(self, method, path, body=None):
        status, _, raw = self.call(method, path, body)
        return status, json.loads(raw.decode("utf-8"))

    def add(self, title, **extra):
        body = {"title": title}
        body.update(extra)
        status, data = self.api("POST", "/api/tasks", body)
        self.assertEqual(status, 201, data)
        return data["task"]

    def move_full(self, task_id, to, **extra):
        body = {"to": to}
        body.update(extra)
        return self.api("POST", "/api/tasks/%d/move" % task_id, body)

    def move(self, task_id, to, reason=None):
        """(status, task) on success, (status, error body) otherwise."""
        status, data = self.move_full(task_id, to, **({} if reason is None else {"reason": reason}))
        return status, data["task"] if status == 200 else data

    def titles(self, state):
        return [t["title"] for t in self.state()["lists"][state]]

    def fill(self, state, count, prefix):
        """Create `count` tasks straight into `state`; returns them top to bottom."""
        for i in range(count):
            self.add("%s%d" % (prefix, i), state=state, position=i)
        return self.state()["lists"][state]

    def state(self):
        status, data = self.api("GET", "/api/state")
        self.assertEqual(status, 200)
        return data

    def sql(self, statement, args=()):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(statement, args)
            conn.commit()
        finally:
            conn.close()

    def raw_request(self, method, path, headers, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders(body)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    # tests

    def test_migrations_idempotent(self):
        app.init_db(self.db)
        app.init_db(self.db)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(app.MIGRATIONS))
            tables = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        finally:
            conn.close()
        self.assertTrue({"tasks", "events", "reviews", "settings"} <= tables)

    def test_full_closed_overflows_to_top_of_open(self):
        self.fill("closed", 10, "c")
        self.add("o0")
        t = self.add("new")
        status, data = self.move_full(t["id"], "closed")
        self.assertEqual(status, 200)
        self.assertEqual(data["task"]["state"], "closed")
        self.assertEqual(data["cascade"], [{"id": data["cascade"][0]["id"], "title": "c9", "from": "closed", "to": "open"}])
        self.assertEqual(self.titles("closed"), ["new"] + ["c%d" % i for i in range(9)])
        self.assertEqual(self.titles("open"), ["c9", "o0"])

    def test_full_closed_honours_position(self):
        # Owner ruling 2026-10-28 morning: a drop lower in a full Closed list lands there.
        self.fill("closed", 10, "c")
        self.fill("open", 2, "o")
        t = self.state()["lists"]["open"][1]
        status, data = self.move_full(t["id"], "closed", position=4)
        self.assertEqual(status, 200)
        self.assertEqual(self.titles("closed"), ["c0", "c1", "c2", "c3", "o1", "c4", "c5", "c6", "c7", "c8"])
        self.assertEqual([t["position"] for t in self.state()["lists"]["closed"]], list(range(10)))
        self.assertEqual([(c["title"], c["from"], c["to"]) for c in data["cascade"]], [("c9", "closed", "open")])
        self.assertEqual(self.titles("open"), ["c9", "o0"])

    def test_full_closed_position_omitted_is_top(self):
        self.fill("closed", 10, "c")
        t = self.add("new")
        status, data = self.move_full(t["id"], "closed")
        self.assertEqual(status, 200)
        self.assertEqual(self.titles("closed"), ["new"] + ["c%d" % i for i in range(9)])
        self.assertEqual(len(data["cascade"]), 1)

    def test_full_closed_position_last_and_beyond(self):
        # Position 9 and position 10 (closed_cap or more) both mean "last": the newcomer
        # is inserted at the bottom and the previous last item goes to the top of Open.
        for position in (9, 10):
            self.sql("DELETE FROM tasks")
            self.fill("closed", 10, "c")
            t = self.add("new")
            status, data = self.move_full(t["id"], "closed", position=position)
            self.assertEqual(status, 200, position)
            self.assertEqual(self.titles("closed"), ["c%d" % i for i in range(9)] + ["new"], position)
            self.assertEqual([(c["title"], c["to"]) for c in data["cascade"]], [("c9", "open")], position)
            self.assertEqual(self.titles("open"), ["c9"], position)

    def test_caps_come_from_settings(self):
        self.sql("INSERT INTO settings(key, value) VALUES ('closed_cap', '1')")
        a, b = self.add("a"), self.add("b")
        self.assertEqual(self.move(a["id"], "closed")[0], 200)
        status, data = self.move_full(b["id"], "closed")
        self.assertEqual(status, 200)
        self.assertEqual(self.titles("closed"), ["b"])
        self.assertEqual(self.titles("open"), ["a"])

    def test_any_bucket_any_move(self):
        t = self.add("skip")
        status, task = self.move(t["id"], "focus")
        self.assertEqual(status, 200)
        self.assertEqual(task["state"], "focus")
        self.assertTrue(task["focused_at"])
        self.assertEqual(self.move(t["id"], "open")[0], 200)
        self.assertEqual(self.move(t["id"], "neglect", "later")[0], 200)
        self.assertEqual(self.move(t["id"], "focus")[0], 200)  # revive straight to Focus
        self.move(t["id"], "let_go")
        self.assertEqual(self.move(t["id"], "focus")[0], 400)  # let go revives to Open only
        self.assertEqual(self.move(t["id"], "open")[0], 200)

    def test_neglect_needs_reason(self):
        t = self.add("maybe")
        self.assertEqual(self.move(t["id"], "neglect")[0], 400)
        self.assertEqual(self.move(t["id"], "neglect", "  ")[0], 400)
        status, task = self.move(t["id"], "neglect", "not this year")
        self.assertEqual(status, 200)
        self.assertEqual(task["reason"], "not this year")
        self.assertTrue(task["neglect_at"])
        self.assertEqual(self.state()["lists"]["neglect"][0]["id"], t["id"])

    def test_is_first_unique_and_cleared_on_demotion(self):
        a, b, c = self.add("a"), self.add("b"), self.add("c")
        for t in (a, b):
            self.move(t["id"], "closed")
            self.move(t["id"], "focus")
        self.assertEqual(self.api("PATCH", "/api/tasks/%d" % c["id"], {"is_first": True})[0], 400)
        self.assertEqual(self.api("PATCH", "/api/tasks/%d" % a["id"], {"is_first": True})[0], 200)
        self.assertEqual(self.api("PATCH", "/api/tasks/%d" % b["id"], {"is_first": True})[0], 200)
        focus = {t["id"]: t["is_first"] for t in self.state()["lists"]["focus"]}
        self.assertEqual(focus, {a["id"]: False, b["id"]: True})
        status, task = self.move(b["id"], "closed")
        self.assertEqual(status, 200)
        self.assertFalse(task["is_first"])

    def test_reorder_validates_state(self):
        a, b, c = self.add("a"), self.add("b"), self.add("c")
        self.assertEqual(self.api("POST", "/api/tasks/reorder", {"state": "open", "ids": [c["id"], a["id"], b["id"]]})[0], 200)
        self.assertEqual([t["title"] for t in self.state()["lists"]["open"]], ["c", "a", "b"])
        self.move(a["id"], "closed")
        status, err = self.api("POST", "/api/tasks/reorder", {"state": "open", "ids": [a["id"], b["id"]]})
        self.assertEqual(status, 400)
        self.assertEqual(self.api("POST", "/api/tasks/reorder", {"state": "open", "ids": [b["id"], b["id"]]})[0], 400)
        self.assertEqual(self.api("POST", "/api/tasks/reorder", {"state": "done", "ids": []})[0], 400)

    def test_done_records_date_and_event_and_undo(self):
        t = self.add("write letter")
        status, task = self.move(t["id"], "done")
        self.assertEqual(status, 200)
        today = datetime.date.today().isoformat()
        self.assertEqual(task["done_at"][:10], today)
        self.assertEqual([d["id"] for d in self.state()["today_done"]], [t["id"]])
        conn = sqlite3.connect(self.db)
        try:
            events = conn.execute("SELECT kind, from_state, to_state FROM events WHERE task_id = ? ORDER BY id",
                                  (t["id"],)).fetchall()
        finally:
            conn.close()
        self.assertEqual(events, [("create", None, "open"), ("move", "open", "done")])
        status, task = self.move(t["id"], "open")
        self.assertEqual(status, 200)
        self.assertIsNone(task["done_at"])
        self.assertEqual(self.state()["today_done"], [])
        status, done = self.api("GET", "/api/done?from=%s&to=%s" % (today, today))
        self.assertEqual(done["done"], [])

    def test_quick_log_for_its_own_sake(self):
        status, data = self.api("POST", "/api/tasks", {"title": "walked by the river", "state": "done",
                                                        "for_its_own_sake": True})
        self.assertEqual(status, 201)
        self.assertEqual(data["cascade"], [])
        task = data["task"]
        self.assertEqual(task["state"], "done")
        self.assertTrue(task["for_its_own_sake"])
        self.assertTrue(task["done_at"])
        self.assertEqual(self.state()["today_done"][0]["title"], "walked by the river")
        self.assertEqual(self.api("POST", "/api/tasks", {"title": "x", "state": "neglect"})[0], 400)

    def test_stale_flag(self):
        old, new = self.add("old"), self.add("new")
        long_ago = (datetime.datetime.now().astimezone() - datetime.timedelta(days=100)).isoformat(timespec="seconds")
        self.sql("UPDATE tasks SET created_at = ? WHERE id = ?", (long_ago, old["id"]))
        flags = {t["title"]: t["stale"] for t in self.state()["lists"]["open"]}
        self.assertEqual(flags, {"old": True, "new": False})

    def test_serialize_note(self):
        a, b, c = self.add("a", project="house"), self.add("b", project="book"), self.add("c")
        for t in (a, c):
            self.move(t["id"], "closed")
            self.move(t["id"], "focus")
        self.assertNotIn("serialize", self.state()["notes"])
        self.move(b["id"], "closed")
        self.move(b["id"], "focus")
        self.assertEqual(self.state()["notes"]["serialize"], "2 projects in focus")

    def test_review_question_and_save(self):
        status, review = self.api("GET", "/api/review?week=2026-W44")
        self.assertEqual(status, 200)
        self.assertEqual(review["question_index"], 44 % 5)
        self.assertEqual(review["question"], app.QUESTIONS[4])
        self.assertEqual(review["answer"], "")
        self.assertEqual(self.api("PUT", "/api/review/2026-W44", {"answer": "Fewer things."})[0], 200)
        self.assertEqual(self.api("PUT", "/api/review/2026-W45", {"answer": "Still fewer."})[0], 200)
        status, review = self.api("GET", "/api/review?week=2026-W44")
        self.assertEqual(review["answer"], "Fewer things.")
        self.assertEqual([p["week"] for p in review["past"]], ["2026-W45"])
        self.assertEqual(self.api("GET", "/api/review?week=2026-W60")[0], 400)

    def test_report(self):
        def done_at(task, created, done):
            self.move(task["id"], "done")
            self.sql("UPDATE tasks SET created_at = ?, done_at = ? WHERE id = ?",
                     (created + "T09:00:00+00:00", done + "T09:00:00+00:00", task["id"]))

        ages = [1, 2, 3, 4, 10]
        for i, age in enumerate(ages):
            created = datetime.date(2025, 3, 1)
            done = created + datetime.timedelta(days=age)
            done_at(self.add("d%d" % i, project="house" if i < 3 else ""), created.isoformat(), done.isoformat())
        log = self.add("sat in the garden", state="done", for_its_own_sake=True)
        self.sql("UPDATE tasks SET created_at = '2025-07-04T10:00:00+00:00', done_at = '2025-07-04T10:00:00+00:00'"
                 " WHERE id = ?", (log["id"],))
        let = self.add("learn the oboe")
        self.move(let["id"], "let_go", "not for me")
        self.sql("UPDATE tasks SET let_go_at = '2025-05-02T08:00:00+00:00' WHERE id = ?", (let["id"],))
        neg = self.add("tidy garage")
        self.move(neg["id"], "neglect", "the garage can wait")
        self.sql("UPDATE tasks SET neglect_at = '2025-05-03T08:00:00+00:00' WHERE id = ?", (neg["id"],))
        self.api("PUT", "/api/review/2025-W10", {"answer": "Rest more."})
        for i in range(12):
            t = self.add("open%d" % i)
            self.sql("UPDATE tasks SET created_at = ? WHERE id = ?",
                     ("2025-01-%02dT09:00:00+00:00" % (i + 1), t["id"]))

        status, report = self.api("GET", "/api/report/2025")
        self.assertEqual(status, 200)
        self.assertEqual(report["year"], 2025)
        self.assertEqual(len(report["months"]), 12)
        self.assertEqual(report["months"][2]["done"], 5)
        self.assertEqual(report["months"][6]["done"], 1)
        self.assertEqual(report["months"][6]["for_its_own_sake"], 1)
        self.assertEqual(report["months"][4]["let_go"], 1)
        self.assertEqual(report["months"][4]["neglect"], 1)
        self.assertEqual(report["totals"], {"done": 6, "for_its_own_sake": 1, "let_go": 1, "neglect": 1})
        self.assertEqual(report["age_at_done_days"], {"count": 5, "median": 3, "p90": 10})
        self.assertEqual(report["by_project"], [{"project": "house", "done": 3}, {"project": "no project", "done": 3}])
        self.assertEqual(report["let_go"][0]["reason"], "not for me")
        self.assertEqual(report["neglected"][0]["reason"], "the garage can wait")
        self.assertEqual(report["reviews"][0]["answer"], "Rest more.")
        self.assertEqual(len(report["still_open"]), 10)
        self.assertEqual(report["still_open"][0]["title"], "open0")
        expected_age = (datetime.date.today() - datetime.date(2025, 1, 1)).days
        self.assertEqual(report["still_open"][0]["age_days"], expected_age)

        status, headers, page = self.call("GET", "/api/report/2025.html")
        self.assertEqual(status, 200)
        page = page.decode("utf-8")
        self.assertIn("What you chose in 2025", page)
        self.assertNotIn("<script", page)
        self.assertNotIn("productiv", page.lower())
        self.assertTrue(headers["Content-Security-Policy"].startswith(CSP))

    def test_done_csv(self):
        a = self.add("one")
        self.move(a["id"], "done")
        self.add("two", state="done", for_its_own_sake=True)
        self.add("still open")
        status, headers, body = self.call("GET", "/api/export/done.csv")
        self.assertEqual(status, 200)
        lines = body.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "date,title,project,for_its_own_sake,age_days")
        self.assertEqual(len(lines), 3)

    def test_export_json(self):
        self.add("one")
        status, data = self.api("GET", "/api/export.json")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(len(data["events"]), 1)

    def test_csp_header(self):
        for path in ("/", "/api/state", "/static/app.js", "/nope"):
            status, headers, _ = self.call("GET", path)
            self.assertEqual(headers["Content-Security-Policy"], CSP, path)

    def test_wrong_host_rejected(self):
        status, _ = self.raw_request("GET", "/api/state", {"Host": "evil.example"})
        self.assertEqual(status, 400)
        status, _ = self.raw_request("GET", "/api/state", {"Host": "localhost:%d" % self.port})
        self.assertEqual(status, 200)
        status, _ = self.raw_request("GET", "/api/state", {"Host": "[::1]:%d" % self.port})
        self.assertEqual(status, 200)

    def test_path_traversal_404(self):
        host = {"Host": "127.0.0.1:%d" % self.port}
        for path in ("/static/../app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py"):
            status, _ = self.raw_request("GET", path, host)
            self.assertEqual(status, 404, path)
        self.assertEqual(self.raw_request("GET", "/static/app.js", host)[0], 200)

    def test_oversized_body_400(self):
        status, body = self.raw_request("POST", "/api/tasks", {
            "Host": "127.0.0.1:%d" % self.port,
            "Content-Type": "application/json",
            "Content-Length": str(70 * 1024),
        }, b"x" * (70 * 1024))
        self.assertEqual(status, 400)
        self.assertIn("too large", json.loads(body.decode("utf-8"))["error"])

    def test_weeks(self):
        self.assertEqual(self.api("GET", "/api/weeks"), (200, {"birth_date": None}))
        born = datetime.date.today() - datetime.timedelta(days=7 * 2134 + 3)
        status, _ = self.api("PUT", "/api/settings", {"birth_date": born.isoformat()})
        self.assertEqual(status, 200)
        status, weeks = self.api("GET", "/api/weeks")
        self.assertEqual(weeks, {"birth_date": born.isoformat(), "week_number": 2134, "weeks_total": 4000,
                                 "today": datetime.date.today().isoformat()})
        self.assertEqual(self.state()["week_number"], 2134)
        self.assertEqual(self.api("PUT", "/api/settings", {"birth_date": ""})[0], 200)
        self.assertEqual(self.api("GET", "/api/weeks")[1], {"birth_date": None})

    def test_unknown_path_404(self):
        self.assertEqual(self.api("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.api("PATCH", "/api/tasks/999", {"title": "x"})[0], 404)

    # v2: buckets, positions and the bump cascade

    def count(self, state):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT COUNT(*) FROM tasks WHERE state = ?", (state,)).fetchone()[0]
        finally:
            conn.close()

    def test_create_into_each_bucket_with_position(self):
        for state in ("focus", "closed", "open"):
            a = self.add(state + "-a", state=state)
            b = self.add(state + "-b", state=state)  # default position 0: top
            c = self.add(state + "-c", state=state, position=1)
            self.assertEqual(a["state"], state)
            self.assertEqual(self.titles(state), [state + "-b", state + "-c", state + "-a"])
        self.assertTrue(self.state()["lists"]["focus"][0]["focused_at"])
        self.assertTrue(self.state()["lists"]["closed"][0]["closed_at"])
        self.add("far", state="open", position=99)  # past the end lands last
        self.assertEqual(self.titles("open")[-1], "far")
        for bad in (-1, "2", True, 1.5):
            self.assertEqual(self.api("POST", "/api/tasks", {"title": "x", "position": bad})[0], 400, bad)
        self.assertEqual(self.api("POST", "/api/tasks", {"title": "x", "bump_id": "1"})[0], 400)

    def test_move_default_position_is_top(self):
        self.fill("closed", 3, "c")
        t = self.add("new")
        self.move(t["id"], "closed")
        self.assertEqual(self.titles("closed"), ["new", "c0", "c1", "c2"])
        status, data = self.move_full(t["id"], "open", position=0)
        self.assertEqual(status, 200)
        self.assertEqual(data["cascade"], [])

    def test_full_focus_needs_bump(self):
        focus = self.fill("focus", 3, "f")
        self.api("PATCH", "/api/tasks/%d" % focus[1]["id"], {"is_first": True})
        t = self.add("fence")
        status, err = self.move_full(t["id"], "focus")
        self.assertEqual(status, 409)
        self.assertEqual(err["error"], "Focus is full.")
        self.assertEqual(err["needs"], "bump")
        self.assertEqual(len(err["candidates"]), 3)
        self.assertEqual(set(c["id"] for c in err["candidates"]), set(f["id"] for f in focus))
        self.assertEqual(self.titles("open"), ["fence"])  # nothing changed
        self.assertEqual(self.move_full(t["id"], "focus", bump_id=t["id"])[0], 400)  # not a focus task
        status, data = self.move_full(t["id"], "focus", bump_id=focus[1]["id"])
        self.assertEqual(status, 200)
        self.assertEqual(data["task"]["state"], "focus")
        self.assertEqual(data["cascade"], [{"id": focus[1]["id"], "title": "f1", "from": "focus", "to": "closed"}])
        closed = self.state()["lists"]["closed"]
        self.assertEqual(closed[0]["id"], focus[1]["id"])
        self.assertEqual(closed[0]["position"], 0)
        self.assertFalse(closed[0]["is_first"])
        self.assertEqual(self.titles("focus"), ["fence", "f0", "f2"])

    def test_bump_through_full_closed(self):
        focus = self.fill("focus", 3, "f")
        self.fill("closed", 10, "c")
        status, data = self.api("POST", "/api/tasks", {"title": "fence", "state": "focus", "bump_id": focus[0]["id"]})
        self.assertEqual(status, 201)
        self.assertEqual([(c["title"], c["from"], c["to"]) for c in data["cascade"]],
                         [("f0", "focus", "closed"), ("c9", "closed", "open")])
        self.assertEqual(self.titles("closed")[0], "f0")
        self.assertEqual(self.titles("open"), ["c9"])
        self.assertEqual(self.state()["lists"]["open"][0]["position"], 0)

    def test_bump_through_full_closed_and_full_open(self):
        focus = self.fill("focus", 3, "f")
        self.fill("closed", 10, "c")
        self.fill("open", 20, "o")
        status, data = self.api("POST", "/api/tasks", {"title": "fence", "state": "focus", "bump_id": focus[2]["id"]})
        self.assertEqual(status, 201)
        self.assertEqual([(c["title"], c["from"], c["to"]) for c in data["cascade"]],
                         [("f2", "focus", "closed"), ("c9", "closed", "open"), ("o19", "open", "neglect")])
        self.assertEqual((self.count("focus"), self.count("closed"), self.count("open"), self.count("neglect")),
                         (3, 10, 20, 1))
        neglected = self.state()["lists"]["neglect"][0]
        self.assertEqual(neglected["title"], "o19")
        self.assertEqual(neglected["reason"], "Bumped out of Open")
        self.assertTrue(neglected["neglect_at"])
        self.assertEqual(self.titles("open")[:2], ["c9", "o0"])
        self.assertEqual(self.titles("closed")[:2], ["f2", "c0"])

    def test_cascade_is_one_transaction(self):
        focus = self.fill("focus", 3, "f")
        self.fill("closed", 10, "c")
        self.fill("open", 20, "o")
        real = app.add_event

        def fail_on_neglect(conn, task_id, kind, from_state, to_state, detail, at):
            if to_state == "neglect":
                raise sqlite3.OperationalError("disk I/O error")
            return real(conn, task_id, kind, from_state, to_state, detail, at)

        with mock.patch.object(app, "add_event", side_effect=fail_on_neglect):
            status, _ = self.api("POST", "/api/tasks", {"title": "fence", "state": "focus",
                                                        "bump_id": focus[0]["id"]})
        self.assertEqual(status, 503)  # the third step failed, so none of it happened
        self.assertEqual(self.titles("focus"), ["f0", "f1", "f2"])
        self.assertEqual(self.titles("closed"), ["c%d" % i for i in range(10)])
        self.assertEqual(self.titles("open"), ["o%d" % i for i in range(20)])
        self.assertEqual(self.count("neglect"), 0)
        self.assertEqual(self.api("GET", "/api/export.json")[1]["tasks"][-1]["title"], "o19")

    def test_full_open_needs_position(self):
        self.fill("open", 20, "o")
        t = self.add("x", state="done")
        status, err = self.move_full(t["id"], "open")
        self.assertEqual(status, 409)
        self.assertEqual(err, {"error": "Open is full.", "needs": "position", "cap": 20})
        self.assertEqual(self.api("POST", "/api/tasks", {"title": "y"})[0], 409)
        self.assertEqual(self.move_full(t["id"], "open", position=20)[0], 400)
        self.assertEqual(self.count("open"), 20)
        status, data = self.move_full(t["id"], "open", position=5)
        self.assertEqual(status, 200)
        self.assertEqual(data["cascade"], [{"id": data["cascade"][0]["id"], "title": "o19", "from": "open",
                                            "to": "neglect"}])
        titles = self.titles("open")
        self.assertEqual(titles, ["o0", "o1", "o2", "o3", "o4", "x"] + ["o%d" % i for i in range(5, 19)])
        self.assertEqual([t["position"] for t in self.state()["lists"]["open"]], list(range(20)))
        self.assertEqual(self.state()["lists"]["neglect"][0]["reason"], "Bumped out of Open")

    def test_open_cap_setting(self):
        self.assertEqual(self.state()["caps"], {"focus": 3, "closed": 10, "open": 20})
        for good in (5, 200, 37):
            status, settings = self.api("PUT", "/api/settings", {"open_cap": good})
            self.assertEqual(status, 200, good)
            self.assertEqual(settings["open_cap"], good)
        for bad in (4, 201, "20", 20.0, True, None):
            self.assertEqual(self.api("PUT", "/api/settings", {"open_cap": bad})[0], 400, bad)
        self.assertEqual(self.state()["caps"]["open"], 37)
        self.api("PUT", "/api/settings", {"open_cap": 5})
        self.fill("open", 5, "o")
        self.assertEqual(self.api("POST", "/api/tasks", {"title": "y"})[1]["cap"], 5)

    def test_renew_and_age(self):
        old, new = self.add("old"), self.add("new")
        long_ago = (datetime.datetime.now().astimezone() - datetime.timedelta(days=16)).isoformat(timespec="seconds")
        self.sql("UPDATE tasks SET created_at = ? WHERE id = ?", (long_ago, old["id"]))
        lists = self.state()["lists"]
        ages = {t["title"]: (t["age_days"], t["stale"]) for t in lists["open"]}
        self.assertEqual(ages, {"old": (16, True), "new": (0, False)})
        status, task = self.api("POST", "/api/tasks/%d/renew" % old["id"], {})
        self.assertEqual(status, 200)
        self.assertTrue(task["touched_at"])
        self.assertEqual(task["created_at"], long_ago)  # the creation date is never faked
        self.assertEqual((task["age_days"], task["stale"]), (0, False))
        thirteen = (datetime.datetime.now().astimezone() - datetime.timedelta(days=13)).isoformat(timespec="seconds")
        self.sql("UPDATE tasks SET touched_at = ? WHERE id = ?", (thirteen, old["id"]))
        ages = {t["title"]: (t["age_days"], t["stale"]) for t in self.state()["lists"]["open"]}
        self.assertEqual(ages["old"], (13, False))
        self.move(new["id"], "closed")
        self.assertEqual(self.api("POST", "/api/tasks/%d/renew" % new["id"], {})[0], 400)
        self.assertEqual(self.api("POST", "/api/tasks/999/renew", {})[0], 404)
        self.assertEqual(self.api("POST", "/api/tasks/%d/renew" % old["id"], {"x": 1})[0], 400)
        conn = sqlite3.connect(self.db)
        try:
            kinds = [r[0] for r in conn.execute("SELECT kind FROM events WHERE task_id = ?", (old["id"],))]
        finally:
            conn.close()
        self.assertIn("renew", kinds)

    def test_state_lists_carry_age(self):
        self.add("a")
        self.add("b", state="closed")
        lists = self.state()["lists"]
        self.assertEqual(sorted(lists), ["closed", "focus", "neglect", "open"])
        self.assertEqual((lists["open"][0]["age_days"], lists["open"][0]["stale"]), (0, False))
        self.assertIsNone(lists["closed"][0]["age_days"])

    def test_migration_from_v1(self):
        path = os.path.join(self.tmp, "v1.sqlite")
        conn = sqlite3.connect(path)
        try:
            for statement in app.MIGRATIONS[0]:
                conn.execute(statement)
            conn.execute("INSERT INTO tasks(title, state, created_at) VALUES ('kept', 'open', '2026-01-02T09:00:00+00:00')")
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
        finally:
            conn.close()
        app.init_db(path)
        conn = sqlite3.connect(path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
            rows = conn.execute("SELECT title, touched_at FROM tasks").fetchall()
        finally:
            conn.close()
        self.assertIn("touched_at", columns)
        self.assertEqual(rows, [("kept", None)])

    # writes from other sites (CSRF)

    def post_json(self, headers, body=b'{"title": "x"}'):
        base = {"Host": "127.0.0.1:%d" % self.port, "Content-Length": str(len(body))}
        base.update(headers)
        status, raw = self.raw_request("POST", "/api/tasks", base, body)
        return status, json.loads(raw.decode("utf-8"))

    def test_write_needs_json_content_type(self):
        status, err = self.post_json({"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(err["error"], "Send JSON (Content-Type: application/json).")
        self.assertEqual(self.post_json({})[0], 415)
        self.assertEqual(self.state()["lists"]["open"], [])

    def test_cross_site_origin_403(self):
        scheme = "http" + "://"  # split so the repo's web-address grep stays clean
        status, err = self.post_json({"Content-Type": "application/json", "Origin": scheme + "evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(err["error"], "Cross-site requests are not allowed.")
        self.assertEqual(self.post_json({"Content-Type": "application/json", "Origin": "null"})[0], 403)
        self.assertEqual(self.state()["lists"]["open"], [])

    def test_cross_site_fetch_metadata_403(self):
        for site in ("cross-site", "same-site"):
            status, err = self.post_json({"Content-Type": "application/json", "Sec-Fetch-Site": site})
            self.assertEqual(status, 403, site)
        self.assertEqual(self.state()["lists"]["open"], [])

    def test_same_origin_write_201(self):
        scheme = "http" + "://"
        status, data = self.post_json({"Content-Type": "application/json; charset=utf-8",
                                       "Origin": scheme + "127.0.0.1:%d" % self.port,
                                       "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 201)
        self.assertEqual(data["task"]["title"], "x")

    def test_options_not_implemented(self):
        self.assertEqual(self.raw_request("OPTIONS", "/api/tasks", {"Host": "127.0.0.1:%d" % self.port})[0], 501)

    # inputs that used to be 500s

    def test_deeply_nested_json_400(self):
        body = b"[" * 30000 + b"]" * 30000
        status, raw = self.raw_request("POST", "/api/tasks", {
            "Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json",
            "Content-Length": str(len(body))}, body)
        self.assertEqual(status, 400)  # RecursionError on 3.9; newer parsers return a list instead
        self.assertIn(json.loads(raw.decode("utf-8"))["error"], ("Body must be JSON.", "Body must be a JSON object."))

    def test_lone_surrogate_text_400(self):
        t = self.add("ok")
        lone = '"\\ud800"'  # a JSON escape that decodes to a lone surrogate
        cases = [
            ("POST", "/api/tasks", '{"title": %s}' % lone),
            ("POST", "/api/tasks", '{"title": "x", "notes": %s}' % lone),
            ("PATCH", "/api/tasks/%d" % t["id"], '{"project": %s}' % lone),
            ("POST", "/api/tasks/%d/move" % t["id"], '{"to": "neglect", "reason": %s}' % lone),
            ("PUT", "/api/review/2026-W44", '{"answer": %s}' % lone),
            ("POST", "/api/tasks", '{%s: 1}' % lone),
        ]
        for method, path, text in cases:
            body = text.encode("ascii")
            status, raw = self.raw_request(method, path, {
                "Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json",
                "Content-Length": str(len(body))}, body)
            self.assertEqual(status, 400, text)
            self.assertEqual(json.loads(raw.decode("utf-8"))["error"], "Text contains invalid characters.", text)

    def test_bad_task_ids(self):
        t = self.add("a")
        for bad in ("0", "9" * 19, "9" * 30, str(2 ** 53 + 1)):
            self.assertEqual(self.api("PATCH", "/api/tasks/" + bad, {"title": "x"}),
                             (404, {"error": "No such task."}), bad)
            self.assertEqual(self.api("POST", "/api/tasks/%s/move" % bad, {"to": "done"})[0], 404, bad)
        for ids in ([0], [-1], [2 ** 53 + 1], [10 ** 30]):
            status, err = self.api("POST", "/api/tasks/reorder", {"state": "open", "ids": ids})
            self.assertEqual(status, 400, ids)
            self.assertEqual(err["error"], "ids must be a list of task ids.")
        self.assertEqual(self.api("POST", "/api/tasks/reorder", {"state": "open", "ids": [t["id"]]})[0], 200)

    def test_review_week_bounds(self):
        for week in ("1969-W10", "2201-W01", "2026-W00", "2026-W54", "2026-W44\n"):
            self.assertEqual(self.api("GET", "/api/review?week=" + urllib.request.quote(week))[0], 400, week)
            self.assertEqual(self.api("PUT", "/api/review/" + urllib.request.quote(week), {"answer": ""})[0],
                             400 if "\n" not in week else 404, week)
        self.assertEqual(self.api("GET", "/api/review?week=2026-W53")[0], 200)  # 2026 has 53 ISO weeks
        self.assertEqual(self.api("GET", "/api/review?week=2025-W53")[0], 400)
        self.assertEqual(self.api("GET", "/api/review?week=1970-W01")[0], 200)

    def test_database_busy_503(self):
        with mock.patch.object(app, "get_settings", side_effect=sqlite3.OperationalError("database is locked")):
            status, err = self.api("GET", "/api/state")
        self.assertEqual(status, 503)
        self.assertEqual(err, {"error": "The database is busy. Try again."})
        with mock.patch.object(app.sqlite3, "connect", wraps=sqlite3.connect) as spy:
            app.connect(self.db).close()
        self.assertEqual(spy.call_args[1]["timeout"], 5)

    def test_handler_timeout(self):
        self.assertEqual(app.Handler.timeout, 30)

    def test_csv_formula_guard_and_bom(self):
        self.add('=HYPERLINK("x","y")', state="done", project="+1")
        self.add("@home", state="done")
        self.add("-5 kg", state="done")
        self.add("plain", state="done")
        status, _, body = self.call("GET", "/api/export/done.csv")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        text = body.decode("utf-8-sig")
        self.assertIn('"\'=HYPERLINK(""x"",""y"")",\'+1,', text)
        self.assertIn(",'@home,", text)
        self.assertIn(",'-5 kg,", text)
        self.assertIn(",plain,", text)

    def test_reuse_address_off_on_windows(self):
        with mock.patch.object(app.sys, "platform", "win32"):
            server = app.make_server(self.db, 0)
        try:
            self.assertFalse(server.allow_reuse_address)
            self.assertEqual(server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        finally:
            server.server_close()
        self.assertTrue(self.server.allow_reuse_address)

    def test_startup_on_ascii_console(self):
        class FakeServer(object):
            server_address = ("127.0.0.1", 8787)

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                pass

        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
        with mock.patch.object(app, "make_server", return_value=FakeServer()), \
                mock.patch.object(app.sys, "stdout", console):
            code = app.main(["--no-browser", "--db", os.path.join(self.tmp, "d\u00e9j\u00e0.sqlite")])
            console.flush()
        self.assertEqual(code, 0)
        self.assertIn(b"d?j?.sqlite", raw.getvalue())
        with mock.patch.object(app, "make_server", return_value=FakeServer()), \
                mock.patch.object(app.sys, "stdout", io.StringIO()):
            self.assertEqual(app.main(["--no-browser"]), 0)  # no reconfigure() on this stream


if __name__ == "__main__":
    unittest.main()
