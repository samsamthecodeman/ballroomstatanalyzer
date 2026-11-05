"""Shared parsed-results index. SQLite lives beside the persistent HTML cache."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

PARSER_VERSION = 1
WEEK = 7 * 86400


class ResultsStore:
    def __init__(self, directory):
        self.path = Path(directory) / "results.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    cid INTEGER, eid INTEGER, payload TEXT NOT NULL, version INTEGER NOT NULL,
                    updated REAL NOT NULL, PRIMARY KEY(cid,eid));
                CREATE TABLE IF NOT EXISTS people (
                    person TEXT, cid INTEGER, eid INTEGER, PRIMARY KEY(person,cid,eid));
                CREATE TABLE IF NOT EXISTS competitions (
                    cid INTEGER PRIMARY KEY, data TEXT NOT NULL, refreshed REAL NOT NULL DEFAULT 0,
                    frozen INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS profiles (
                    aid INTEGER PRIMARY KEY, overview TEXT NOT NULL, comps TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS external_cache (
                    provider TEXT, kind TEXT, id TEXT, data TEXT NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(provider,kind,id));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.execute("PRAGMA synchronous=NORMAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_events(self, pairs):
        pairs = list(set(pairs))
        found = {}
        with self.connect() as db:
            for offset in range(0, len(pairs), 300):
                batch = pairs[offset:offset + 300]
                marks = ",".join("(?,?)" for _ in batch)
                args = [value for pair in batch for value in pair]
                for cid, eid, payload in db.execute(
                    f"SELECT cid,eid,payload FROM events WHERE (cid,eid) IN ({marks}) AND version=?",
                    [*args, PARSER_VERSION],
                ):
                    found[cid, eid] = json.loads(payload)
        return found

    def put_event(self, cid, eid, payload, people=()):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?)",
                       (cid, eid, json.dumps(payload, ensure_ascii=False), PARSER_VERSION, time.time()))
            db.execute("DELETE FROM people WHERE cid=? AND eid=?", (cid, eid))
            db.executemany("INSERT OR IGNORE INTO people VALUES (?,?,?)", ((p, cid, eid) for p in set(people)))

    def find_person_events(self, person):
        with self.connect() as db:
            return db.execute("SELECT cid,eid FROM people WHERE person=? ORDER BY cid,eid", (person,)).fetchall()

    def get_profile(self, aid, max_age=WEEK):
        with self.connect() as db:
            row = db.execute("SELECT overview,comps,updated FROM profiles WHERE aid=?", (aid,)).fetchone()
        if row and (max_age is None or time.time() - row[2] < max_age):
            return {"overview": row[0], "comps": json.loads(row[1]), "updated": row[2]}

    def put_profile(self, aid, overview, comps):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?)",
                       (aid, overview or "", json.dumps(comps, ensure_ascii=False), time.time()))

    def profile_ids(self):
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT aid FROM profiles")]

    def known_competition_metadata(self):
        metadata = {}
        with self.connect() as db:
            rows = db.execute("SELECT comps FROM profiles").fetchall()
        for (payload,) in rows:
            for comp in json.loads(payload):
                if comp.get("date"):
                    metadata[comp["cid"]] = {key: comp.get(key) for key in ("name", "date", "end_date")}
        return metadata

    def event_updated(self, cid, eid):
        with self.connect() as db:
            row = db.execute("SELECT updated FROM events WHERE cid=? AND eid=? AND version=?", (cid, eid, PARSER_VERSION)).fetchone()
        return row[0] if row else 0

    def competition(self, cid):
        with self.connect() as db:
            row = db.execute("SELECT data,refreshed,frozen FROM competitions WHERE cid=?", (cid,)).fetchone()
        return {"data": json.loads(row[0]), "refreshed": row[1], "frozen": bool(row[2])} if row else None

    def put_competition(self, data, complete=False, frozen=False):
        previous = self.competition(data["cid"])
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO competitions VALUES (?,?,?,?)", (
                data["cid"], json.dumps(data, ensure_ascii=False),
                time.time() if complete else (previous["refreshed"] if previous else 0),
                int(frozen if complete else (previous["frozen"] if previous else False)),
            ))

    def get_meta(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def get_external(self, provider, kind, key):
        with self.connect() as db:
            row = db.execute("SELECT data,updated FROM external_cache WHERE provider=? AND kind=? AND id=?",
                             (provider, kind, key)).fetchone()
        return {"data": json.loads(row[0]), "updated": row[1]} if row else None

    def put_external(self, provider, kind, key, data):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO external_cache VALUES (?,?,?,?,?)",
                       (provider, kind, key, json.dumps(data, ensure_ascii=False), time.time()))

    def external_keys(self, provider, kind):
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM external_cache WHERE provider=? AND kind=?", (provider, kind))]

    def set_meta(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json.dumps(value)))

    def status(self):
        with self.connect() as db:
            events = db.execute("SELECT count(*) FROM events WHERE version=?", (PARSER_VERSION,)).fetchone()[0]
            comps = db.execute("SELECT count(*) FROM competitions WHERE refreshed>0").fetchone()[0]
            profiles = db.execute("SELECT count(*) FROM profiles").fetchone()[0]
        return {"events": events, "competitions": comps, "dancer_profiles": profiles,
                "refresh": self.get_meta("refresh_status", {})}
