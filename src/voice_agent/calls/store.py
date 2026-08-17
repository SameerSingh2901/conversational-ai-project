"""Call records as JSON files under `call_logs/`.

Mirrors `ConfigStore` deliberately, including the seam: swap these three method
bodies for SQL and no caller changes.

One constraint worth stating plainly — **the worker writes and the API reads**,
so this only works while both processes share a filesystem. That is true on one
laptop and false the moment they are on separate machines, which is the point at
which this class becomes a database client rather than a file writer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from voice_agent.calls.models import CallRecord, record_from_dict

logger = logging.getLogger("voice-agent.calls")

DEFAULT_CALL_LOG_DIR = Path("call_logs")


class CallNotFoundError(LookupError):
    pass


class CallStore:
    def __init__(self, root: Path | str = DEFAULT_CALL_LOG_DIR) -> None:
        self.root = Path(root)

    def _path(self, call_id: str) -> Path:
        # Room names contain no path separators, but a record id reaching the
        # filesystem is worth being paranoid about.
        return self.root / f"{Path(call_id).name}.json"

    def save(self, record: CallRecord) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(record.call_id)
        path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def load(self, call_id: str) -> CallRecord:
        path = self._path(call_id)
        if not path.is_file():
            raise CallNotFoundError(f"no call record for {call_id!r} in {self.root}")
        return record_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def exists(self, call_id: str) -> bool:
        return self._path(call_id).is_file()

    def list(self) -> list[CallRecord]:
        """Every readable record, newest first. Unreadable files are skipped and
        logged rather than failing the listing."""
        if not self.root.is_dir():
            return []
        records: list[CallRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                records.append(
                    record_from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                logger.warning("skipping unreadable call record: %s", path)
        records.sort(key=lambda r: r.started_at, reverse=True)
        return records
