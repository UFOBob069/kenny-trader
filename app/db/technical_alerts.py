"""Single-user alert journal, isolated from paper orders and trade records."""
import json
import os
import sqlite3
from pathlib import Path

from app.config import settings


class AlertStorageError(Exception):
    pass


class AlertStore:
    key = 'technicals.alerts.v1'

    def __init__(self):
        self.client = None

    def _backend(self):
        if settings.supabase_url and settings.supabase_key:
            if self.client is None:
                from supabase import create_client
                self.client = create_client(settings.supabase_url, settings.supabase_key)
            return 'supabase'
        path = Path(settings.state_db_path).resolve()
        if os.getenv('RAILWAY_ENVIRONMENT_ID'):
            mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
            if not mount or not path.is_relative_to(Path(mount).resolve()):
                raise AlertStorageError('Alert storage needs Supabase or STATE_DB_PATH on a Railway volume.')
        path.parent.mkdir(parents=True, exist_ok=True)
        return 'sqlite'

    def read(self):
        try:
            if self._backend() == 'supabase':
                rows = self.client.table('settings').select('value').eq('key', self.key).execute().data
                return rows[0]['value'] if rows else None
            with sqlite3.connect(settings.state_db_path, timeout=10) as db:
                db.execute('CREATE TABLE IF NOT EXISTS technical_alerts (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                row = db.execute('SELECT value FROM technical_alerts WHERE key=?', (self.key,)).fetchone()
                return json.loads(row[0]) if row else None
        except AlertStorageError:
            raise
        except Exception:
            raise AlertStorageError('Alert journal unavailable; monitoring has not been updated.') from None

    def write(self, state):
        try:
            if self._backend() == 'supabase':
                self.client.table('settings').upsert({'key': self.key, 'value': state}).execute()
            else:
                with sqlite3.connect(settings.state_db_path, timeout=10) as db:
                    db.execute('INSERT OR REPLACE INTO technical_alerts VALUES (?, ?)',
                               (self.key, json.dumps(state, allow_nan=False)))
        except AlertStorageError:
            raise
        except Exception:
            raise AlertStorageError('Alert journal write failed; changes were not saved.') from None
