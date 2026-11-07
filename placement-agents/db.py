import sqlite3
from contextlib import contextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics(
  id INTEGER PRIMARY KEY, ord INTEGER, name TEXT UNIQUE, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS problems(
  id INTEGER PRIMARY KEY, ord INTEGER, topic TEXT, name TEXT UNIQUE,
  difficulty TEXT, source TEXT, done INTEGER DEFAULT 0, done_on TEXT);
CREATE TABLE IF NOT EXISTS events(           -- exams / vacations / busy days
  id INTEGER PRIMARY KEY, kind TEXT, title TEXT, start TEXT, end TEXT);
CREATE TABLE IF NOT EXISTS study_log(
  day TEXT, minutes INTEGER, source TEXT);   -- source: auto | manual
CREATE TABLE IF NOT EXISTS syllabus(         -- college subject units
  id INTEGER PRIMARY KEY, subject TEXT, unit TEXT, done INTEGER DEFAULT 0,
  UNIQUE(subject, unit));
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS inbox(            -- messages/calls seen on the phone (notifications)
  id INTEGER PRIMARY KEY AUTOINCREMENT, app TEXT, sender TEXT, chat TEXT, text TEXT, ts REAL,
  nkey TEXT, status TEXT DEFAULT 'open',     -- open | read | handled
  nudges INTEGER DEFAULT 0, last_nudge REAL DEFAULT 0, can_reply INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS inbox_status ON inbox(status, ts);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def get(k, default=None):
    with conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def put(k, v):
    with conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  (k, str(v)))


def q(sql, args=()):
    with conn() as c:
        return c.execute(sql, args).fetchall()


def x(sql, args=()):
    with conn() as c:
        c.execute(sql, args)
