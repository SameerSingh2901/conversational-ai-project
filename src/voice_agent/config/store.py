"""Reading and writing agent configs as JSON files under `configs/`.

Every save mints a fresh `<slug>-<YYYYMMDD-HHMMSS>` id, so saving an edited config
leaves the previous version on disk rather than overwriting it. Config history for
free, which matters once you are comparing latency between prompt revisions.

This class is the seam for a database later: swap the body of these four methods,
leave every caller alone.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from voice_agent.config.errors import ConfigValidationError, FieldError
from voice_agent.config.schema import AgentConfig, parse_config

DEFAULT_CONFIG_DIR = Path("configs")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """`My Sales Agent!` -> `my-sales-agent`. Filesystem- and URL-safe."""
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug or "agent"


def make_config_id(name: str, when: datetime | None = None) -> str:
    """Build the `<slug>-<date>-<time>` id used as both filename and identifier.

    Local time, so the filename matches the wall clock of whoever saved it.
    """
    stamp = (when or datetime.now(UTC).astimezone()).strftime("%Y%m%d-%H%M%S")
    return f"{slugify(name)}-{stamp}"


class ConfigNotFoundError(LookupError):
    pass


class ConfigStore:
    def __init__(self, root: Path | str = DEFAULT_CONFIG_DIR) -> None:
        self.root = Path(root)

    def _path(self, config_id: str) -> Path:
        return self.root / f"{config_id}.json"

    def _unique_id(self, name: str, when: datetime) -> str:
        """`make_config_id` only has one-second resolution, and saving twice in the
        same second is easy from a UI. Suffix a counter rather than overwrite."""
        base = make_config_id(name, when)
        config_id = base
        counter = 2
        while self._path(config_id).exists():
            config_id = f"{base}-{counter}"
            counter += 1
        return config_id

    def save(self, config: AgentConfig) -> AgentConfig:
        """Stamp a new id and timestamp, write the file, return the stored config."""
        now = datetime.now(UTC).astimezone()
        stored = AgentConfig(
            id=self._unique_id(config.name, now),
            name=config.name,
            created_at=now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            stt=config.stt,
            llm=config.llm,
            tts=config.tts,
            vad=config.vad,
            prompt=config.prompt,
            tools=config.tools,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(stored.id)
        path.write_text(json.dumps(stored.to_dict(), indent=2) + "\n", encoding="utf-8")
        return stored

    def load(self, config_id: str) -> AgentConfig:
        path = self._path(config_id)
        if not path.is_file():
            raise ConfigNotFoundError(f"no config with id {config_id!r} in {self.root}")
        return self.load_file(path)

    def load_file(self, path: Path | str) -> AgentConfig:
        """Parse a config from an explicit path — used by the terminal runner."""
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigValidationError(
                [
                    FieldError(
                        (), f"{path}: invalid JSON — {exc.msg} at line {exc.lineno}"
                    )
                ]
            ) from exc
        return parse_config(raw)

    def list(self) -> list[AgentConfig]:
        """Every valid config on disk, newest first. Invalid files are skipped."""
        if not self.root.is_dir():
            return []
        configs: list[AgentConfig] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                configs.append(self.load_file(path))
            except ConfigValidationError:
                continue
        configs.sort(key=lambda c: c.id, reverse=True)
        return configs
