"""本地 SQLite 存储。Agent 隔离由查询条件和归属检查共同保证。"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv('HIGURUMA_DATA_DIR', '.runtime'))

def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'higuruma.db', timeout=20)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, body TEXT NOT NULL, original BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, body TEXT NOT NULL);
        ''')
    for audit in list_audits():
        if audit['status'] in ('queued', 'running'):
            audit['status'] = 'interrupted'
            audit['conclusion'] = '需人工复核'
            audit['error'] = '服务重启，审核未完成；可重新发起审核'
            save_audit(audit)


def agents():
    with connection() as db:
        return [json.loads(r['body']) for r in db.execute('SELECT body FROM agents ORDER BY rowid')]


def get_agent(agent_id):
    with connection() as db:
        row = db.execute('SELECT body FROM agents WHERE id=?', (agent_id,)).fetchone()
        return json.loads(row['body']) if row else None


def save_agent(agent):
    with connection() as db:
        db.execute('INSERT INTO agents VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                   (agent['id'], json.dumps(agent, ensure_ascii=False)))


def save_document(agent_id, document, original):
    document = {'id': uid(), 'agent_id': agent_id, 'created_at': now(), **document}
    with connection() as db:
        db.execute('INSERT INTO documents VALUES (?,?,?,?)', (document['id'], agent_id, json.dumps(document, ensure_ascii=False), original))
    return document


def get_document(agent_id, document_id):
    with connection() as db:
        row = db.execute('SELECT body FROM documents WHERE id=? AND agent_id=?', (document_id, agent_id)).fetchone()
        return json.loads(row['body']) if row else None


def documents(agent_id):
    with connection() as db:
        return [json.loads(r['body']) for r in db.execute('SELECT body FROM documents WHERE agent_id=? ORDER BY rowid DESC', (agent_id,))]


def save_audit(audit):
    with connection() as db:
        db.execute('INSERT INTO audits VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                   (audit['id'], audit['agent_id'], json.dumps(audit, ensure_ascii=False)))


def list_audits(agent_id=None):
    with connection() as db:
        rows = db.execute('SELECT body FROM audits ORDER BY rowid DESC') if agent_id is None else db.execute('SELECT body FROM audits WHERE agent_id=? ORDER BY rowid DESC', (agent_id,))
        return [json.loads(r['body']) for r in rows]


def get_audit(agent_id, audit_id):
    with connection() as db:
        row = db.execute('SELECT body FROM audits WHERE id=? AND agent_id=?', (audit_id, agent_id)).fetchone()
        return json.loads(row['body']) if row else None
