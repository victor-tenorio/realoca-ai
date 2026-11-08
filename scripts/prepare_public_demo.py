"""Consistent SQLite backup for the public demo; never seed or migrate."""
import hashlib
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'realoca.db'
target = root / '.public-demo' / 'snapshot.db'
target.parent.mkdir(exist_ok=True)
if target.exists():
    raise SystemExit('Snapshot already exists; refusing to overwrite it.')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
    before = hashlib.sha256('\n'.join(original.iterdump()).encode()).hexdigest()
    with sqlite3.connect(target) as copy:
        original.backup(copy)
        assert copy.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert copy.execute('select count(*) from cases').fetchone()[0] >= 2
    after = hashlib.sha256('\n'.join(original.iterdump()).encode()).hexdigest()
    assert before == after, 'Source changed during backup; inspect before proceeding.'
print(json.dumps({'snapshot': str(target), 'source_unchanged': True, 'integrity': 'ok'}))
