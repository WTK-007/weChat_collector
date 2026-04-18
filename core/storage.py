"""SQLite 数据存储，记录公众号和文章信息"""

import sqlite3
from datetime import datetime
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            biz         TEXT PRIMARY KEY,
            nickname    TEXT,
            avatar_url  TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            biz         TEXT NOT NULL,
            title       TEXT NOT NULL,
            url         TEXT NOT NULL UNIQUE,
            author      TEXT,
            digest      TEXT,
            cover_url   TEXT,
            publish_time TEXT,
            pdf_path    TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (biz) REFERENCES accounts(biz)
        );

        CREATE INDEX IF NOT EXISTS idx_articles_biz ON articles(biz);
    """)
    conn.close()


def upsert_account(biz: str, nickname: str = None, avatar_url: str = None):
    """插入或更新公众号信息"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO accounts (biz, nickname, avatar_url)
           VALUES (?, ?, ?)
           ON CONFLICT(biz) DO UPDATE SET
               nickname = COALESCE(excluded.nickname, accounts.nickname),
               avatar_url = COALESCE(excluded.avatar_url, accounts.avatar_url)
        """,
        (biz, nickname, avatar_url),
    )
    conn.commit()
    conn.close()


def get_account(biz: str) -> dict | None:
    """获取公众号信息"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM accounts WHERE biz = ?", (biz,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_article(biz: str, title: str, url: str, author: str = None,
                   digest: str = None, cover_url: str = None,
                   publish_time: str = None) -> bool:
    """插入文章记录，如果已存在则跳过，返回是否新插入"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO articles
               (biz, title, url, author, digest, cover_url, publish_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (biz, title, url, author, digest, cover_url, publish_time),
        )
        conn.commit()
        inserted = conn.total_changes > 0
    except Exception:
        inserted = False
    finally:
        conn.close()
    return inserted


def update_pdf_path(article_url: str, pdf_path: str):
    """更新文章的 PDF 路径"""
    conn = get_connection()
    conn.execute(
        "UPDATE articles SET pdf_path = ? WHERE url = ?",
        (pdf_path, article_url),
    )
    conn.commit()
    conn.close()


def get_articles(biz: str, limit: int = None) -> list[dict]:
    """获取某公众号的所有文章"""
    conn = get_connection()
    query = "SELECT * FROM articles WHERE biz = ? ORDER BY publish_time DESC"
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query, (biz,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_articles_without_pdf(biz: str, limit: int = None) -> list[dict]:
    """获取尚未导出 PDF 的文章"""
    conn = get_connection()
    query = """SELECT * FROM articles
               WHERE biz = ? AND pdf_path IS NULL
               ORDER BY publish_time DESC"""
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = conn.execute(query, (biz,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_article_count(biz: str) -> int:
    """获取某公众号的文章总数"""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM articles WHERE biz = ?", (biz,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_articles_filtered(
    biz: str,
    start_date: str = None,
    end_date: str = None,
    limit: int = None,
) -> list[dict]:
    """
    按条件筛选文章。

    Args:
        biz: 公众号标识
        start_date: 开始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"
        limit: 最多返回条数（取最近 N 篇）
    """
    conn = get_connection()
    query = "SELECT * FROM articles WHERE biz = ?"
    params = [biz]

    if start_date:
        query += " AND publish_time >= ?"
        params.append(start_date)
    if end_date:
        query += " AND publish_time <= ?"
        params.append(end_date + " 23:59:59")

    query += " ORDER BY publish_time DESC"

    if limit:
        query += f" LIMIT {int(limit)}"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
