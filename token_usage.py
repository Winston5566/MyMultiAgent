"""Track actual OpenAI-compatible API usage in SQLite.

Do not record prompts, completions, API keys or response bodies.
Usage is read only from response.usage. Unknown usage/pricing stays NULL.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'multiagent.db'
DEFAULT_PRICES = ROOT / 'token_prices.json'


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _token(value):
    if type(value) is int and value >= 0:
        return value
    return None


def _prices_for(model, path):
    if not Path(path).is_file():
        return None, None, None
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        entry = data.get('models', {}).get(model)
        if not isinstance(entry, dict):
            return None, None, None
        a, b = entry.get('input_per_1m'), entry.get('output_per_1m')
        currency = entry.get('currency')
        if (type(a) not in (int, float) or type(b) not in (int, float)
                or a < 0 or b < 0 or not isinstance(currency, str) or not currency.strip()):
            return None, None, None
        return float(a), float(b), currency.strip().upper()
    except (OSError, ValueError, TypeError):
        return None, None, None


def init_db(db_path=None):
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as conn:
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                job_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                input_price_per_1m REAL,
                output_price_per_1m REAL,
                estimated_cost REAL,
                currency TEXT,
                usage_available INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_api_usage_job ON api_usage(job_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_api_usage_agent ON api_usage(agent_name)')
    return path


def record_response(*, job_id, agent_name, response, model=None,
                    request_id=None, db_path=None, prices_path=None):
    """Save one returned API response. Return True only for newly inserted rows.

    Call once immediately after EACH successful chat.completions.create call.
    request_id defaults to response.id, or a UUID if the provider omits it.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError('job_id must be a nonempty string')
    if not isinstance(agent_name, str) or not agent_name.strip():
        raise ValueError('agent_name must be a nonempty string')
    if response is None:
        raise ValueError('response must not be None')

    response_model = _get(response, 'model')
    chosen_model = str(model or response_model or 'unknown')
    usage = _get(response, 'usage')
    prompt = _token(_get(usage, 'prompt_tokens'))
    completion = _token(_get(usage, 'completion_tokens'))
    total = _token(_get(usage, 'total_tokens'))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    usage_available = int(prompt is not None and completion is not None)

    price_in, price_out, currency = _prices_for(chosen_model, prices_path or DEFAULT_PRICES)
    cost = None
    if usage_available and price_in is not None and price_out is not None:
        cost = (prompt * price_in + completion * price_out) / 1_000_000

    response_id = _get(response, 'id')
    key = str(request_id or response_id or uuid.uuid4().hex)
    created = datetime.now(timezone.utc).isoformat(timespec='seconds')
    db = init_db(db_path)
    with sqlite3.connect(db, timeout=30) as conn:
        conn.execute('PRAGMA busy_timeout=30000')
        cursor = conn.execute('''
            INSERT OR IGNORE INTO api_usage (
                request_id, job_id, agent_name, model,
                prompt_tokens, completion_tokens, total_tokens,
                input_price_per_1m, output_price_per_1m,
                estimated_cost, currency, usage_available, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (key, job_id.strip(), agent_name.strip(), chosen_model,
              prompt, completion, total, price_in, price_out,
              cost, currency, usage_available, created))
        return cursor.rowcount == 1


def tracked_create(client, *, job_id, agent_name, **kwargs):
    """Drop-in wrapper for client.chat.completions.create(...).

    IMPORTANT: Use only for non-streaming requests. The returned response is unchanged.
    """
    if kwargs.get('stream'):
        raise ValueError('tracked_create does not support stream=True')
    response = client.chat.completions.create(**kwargs)
    try:
        record_response(
            job_id=job_id, agent_name=agent_name,
            response=response, model=kwargs.get('model')
        )
    except (sqlite3.Error, OSError, ValueError) as exc:
        # Accounting failures must not cause a successful model call to retry.
        warnings.warn(f'Token usage not recorded: {exc}', RuntimeWarning)
    return response


if __name__ == '__main__':
    print('SQLite ready:', init_db())
    print('Usage records are created only after calling record_response or tracked_create.')
