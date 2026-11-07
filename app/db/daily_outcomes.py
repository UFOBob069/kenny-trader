"""Immutable daily research records; use the existing durable settings backend."""
import json
import sqlite3

from app.config import settings
from app.db.technical_alerts import AlertStore


class OutcomeStore(AlertStore):
    def records(self, prefix, since):
        # Compare ISO dates, not a punctuation sentinel whose sort order
        # differs between PostgreSQL locale collations and SQLite binary text.
        lower, upper = prefix + since, prefix + '9999-12-31'
        if self._backend() == 'supabase':
            rows = self.client.table('settings').select('key,value').like('key', prefix + '%').gte('key', lower).lt(
                'key', upper).order('key').limit(500).execute().data
            return {r['key'][len(prefix):]: r['value'] for r in rows}
        with sqlite3.connect(settings.state_db_path, timeout=10) as db:
            db.execute('CREATE TABLE IF NOT EXISTS daily_outcomes (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            rows = db.execute('SELECT key,value FROM daily_outcomes WHERE key>=? AND key<?', (lower, upper))
            return {k[len(prefix):]: json.loads(v) for k, v in rows}

    def insert(self, key, value):
        if self._backend() == 'supabase':
            self.client.table('settings').upsert({'key': key, 'value': value}, on_conflict='key',
                                                 ignore_duplicates=True).execute()
        else:
            with sqlite3.connect(settings.state_db_path, timeout=10) as db:
                db.execute('INSERT OR IGNORE INTO daily_outcomes VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))
