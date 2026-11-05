"""SQLite connection helpers. One writer at a time; every mutation runs in an explicit BEGIN IMMEDIATE transaction."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path=":memory:", check_same_thread=True):
    # autocommit; we issue BEGIN/COMMIT ourselves. The API runs every database call on one event-loop thread
    # (and serialises mutations with a lock), so it opens its connection with check_same_thread=False.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def new_db(path=":memory:", check_same_thread=True):
    conn = connect(path, check_same_thread)
    init_schema(conn)
    return conn


@contextmanager
def transaction(conn):
    """BEGIN IMMEDIATE ... COMMIT, ROLLBACK on any exception (including constraint violations)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
