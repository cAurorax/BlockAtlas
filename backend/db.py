"""SQLite connection factory; each request owns its transaction."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, nickname TEXT NOT NULL,
 password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
 disabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_active TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 content TEXT NOT NULL, visibility TEXT NOT NULL DEFAULT 'public',
 hidden INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
 post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, name TEXT NOT NULL,
 PRIMARY KEY(post_id,name)
);
CREATE TABLE IF NOT EXISTS media (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE, filename TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
 id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, content TEXT NOT NULL,
 parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ratings (
 post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5), PRIMARY KEY(post_id,user_id)
);
CREATE TABLE IF NOT EXISTS friends (
 id INTEGER PRIMARY KEY, requester INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 receiver INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
 CHECK(requester != receiver), UNIQUE(requester, receiver)
);
CREATE TABLE IF NOT EXISTS sensitive_words (word TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS audit_logs (
 id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL,
 target TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(created_at);
CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_friend_pair ON friends(min(requester,receiver),max(requester,receiver));
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.executemany(
                "INSERT OR IGNORE INTO sensitive_words VALUES(?)",
                [("测试违禁词",), ("恶意辱骂",)],
            )
