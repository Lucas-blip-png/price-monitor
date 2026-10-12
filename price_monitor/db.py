import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    selector TEXT,
    target REAL,
    last_price REAL,
    last_notified REAL,
    fails INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price REAL NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    chat_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    last_post_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, name)
);
CREATE TABLE IF NOT EXISTS keywords (
    chat_id INTEGER NOT NULL,
    term TEXT NOT NULL,
    PRIMARY KEY (chat_id, term)
);
"""


class DB:
    """Todo acesso é escopado por chat_id: um chat nunca enxerga dados de outro."""

    def __init__(self, path: str = ":memory:"):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys = ON")
        self.c.executescript(SCHEMA)

    # produtos
    def add_product(self, chat_id, url, title, price, target=None, selector=None) -> int:
        cur = self.c.execute(
            "INSERT INTO products(chat_id,url,title,selector,target,last_price,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (chat_id, url, title, selector, target, price, time.time()),
        )
        self.c.execute("INSERT INTO prices VALUES(?,?,?)", (cur.lastrowid, price, time.time()))
        self.c.commit()
        return cur.lastrowid

    def products(self, chat_id=None) -> list[sqlite3.Row]:
        if chat_id is None:
            return self.c.execute("SELECT * FROM products ORDER BY id").fetchall()
        return self.c.execute("SELECT * FROM products WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()

    def product(self, pid, chat_id):
        return self.c.execute("SELECT * FROM products WHERE id=? AND chat_id=?", (pid, chat_id)).fetchone()

    def remove_product(self, pid, chat_id) -> bool:
        cur = self.c.execute("DELETE FROM products WHERE id=? AND chat_id=?", (pid, chat_id))
        self.c.commit()
        return cur.rowcount > 0

    def set_target(self, pid, chat_id, target) -> bool:
        cur = self.c.execute("UPDATE products SET target=? WHERE id=? AND chat_id=?", (target, pid, chat_id))
        self.c.commit()
        return cur.rowcount > 0

    def record_price(self, pid, price, last_notified) -> None:
        """Atualiza o preço atual; o histórico só guarda mudanças."""
        row = self.c.execute("SELECT last_price FROM products WHERE id=?", (pid,)).fetchone()
        if row and row["last_price"] != price:
            self.c.execute("INSERT INTO prices VALUES(?,?,?)", (pid, price, time.time()))
        self.c.execute(
            "UPDATE products SET last_price=?, last_notified=?, fails=0 WHERE id=?",
            (price, last_notified, pid),
        )
        self.c.commit()

    def record_failure(self, pid) -> int:
        self.c.execute("UPDATE products SET fails = fails + 1 WHERE id=?", (pid,))
        self.c.commit()
        return self.c.execute("SELECT fails FROM products WHERE id=?", (pid,)).fetchone()["fails"]

    def history(self, pid) -> list[sqlite3.Row]:
        return self.c.execute("SELECT price, ts FROM prices WHERE product_id=? ORDER BY ts", (pid,)).fetchall()

    # canais
    def add_channel(self, chat_id, name, last_post_id) -> None:
        self.c.execute(
            "INSERT OR REPLACE INTO channels VALUES(?,?,?)", (chat_id, name.lower(), last_post_id)
        )
        self.c.commit()

    def channels(self, chat_id=None) -> list[sqlite3.Row]:
        if chat_id is None:
            return self.c.execute("SELECT * FROM channels").fetchall()
        return self.c.execute("SELECT * FROM channels WHERE chat_id=?", (chat_id,)).fetchall()

    def remove_channel(self, chat_id, name) -> bool:
        cur = self.c.execute("DELETE FROM channels WHERE chat_id=? AND name=?", (chat_id, name.lower()))
        self.c.commit()
        return cur.rowcount > 0

    def set_last_post(self, chat_id, name, post_id) -> None:
        self.c.execute("UPDATE channels SET last_post_id=? WHERE chat_id=? AND name=?", (post_id, chat_id, name))
        self.c.commit()

    # palavras-chave
    def add_keyword(self, chat_id, term) -> None:
        self.c.execute("INSERT OR IGNORE INTO keywords VALUES(?,?)", (chat_id, term.casefold()))
        self.c.commit()

    def keywords(self, chat_id) -> list[str]:
        return [r["term"] for r in self.c.execute("SELECT term FROM keywords WHERE chat_id=? ORDER BY term", (chat_id,))]

    def remove_keyword(self, chat_id, term) -> bool:
        cur = self.c.execute("DELETE FROM keywords WHERE chat_id=? AND term=?", (chat_id, term.casefold()))
        self.c.commit()
        return cur.rowcount > 0
