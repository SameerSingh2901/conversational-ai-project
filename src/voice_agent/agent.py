"""The LiveKit worker: runs a voice session built from a config.

Which config to run comes from the `VOICE_AGENT_CONFIG` environment variable —
either a config id or a path to a JSON file:

    VOICE_AGENT_CONFIG=sample-agent-20260809-132143 uv run python -m voice_agent.agent console
    VOICE_AGENT_CONFIG=configs/my-agent-20260809-150000.json uv run python -m voice_agent.agent dev

An env var rather than a CLI flag because LiveKit owns the command line here
(`console`, `dev`, `start`), and fighting its parser buys nothing.

Step 4 replaces this with per-room metadata so the UI can pick a config per call
without restarting the worker. The config is deliberately resolved *inside* the
session handler, not at import, so that change lands in one function.
"""

from dotenv import load_dotenv

load_dotenv()

import json
import logging
import os
from typing import Any

from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobContext

from voice_agent.config.env import missing_credentials
from voice_agent.config.errors import ConfigValidationError
from voice_agent.config.schema import AgentConfig, parse_config
from voice_agent.config.store import ConfigNotFoundError, ConfigStore
from voice_agent.pipeline import build_llm, build_stt, build_tts, build_vad
from voice_agent.tools.registry import resolve_tools

CONFIG_ENV = "VOICE_AGENT_CONFIG"
CONFIG_DIR_ENV = "VOICE_AGENT_CONFIG_DIR"

logger = logging.getLogger("voice-agent")

server = AgentServer()


class ConfiguredAgent(Agent):
    """An agent whose behaviour comes entirely from a config document."""

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(
            instructions=config.prompt.instructions,
            tools=resolve_tools(config.tools),
        )


def _store() -> ConfigStore:
    return ConfigStore(os.environ.get(CONFIG_DIR_ENV, "configs"))


def resolve_config() -> AgentConfig:
    """Load the config named by `VOICE_AGENT_CONFIG`, as an id or a file path."""
    store = _store()
    ref = os.environ.get(CONFIG_ENV, "").strip()

    if not ref:
        available = [c.id for c in store.list()]
        listing = "\n  ".join(available) if available else "(none saved yet)"
        raise SystemExit(
            f"{CONFIG_ENV} is not set.\n"
            f"Set it to a config id or a path to a JSON file.\n"
            f"Available in {store.root}/:\n  {listing}"
        )

    try:
        if ref.endswith(".json") or os.sep in ref:
            return store.load_file(ref)
        return store.load(ref)
    except ConfigNotFoundError:
        available = [c.id for c in store.list()]
        listing = "\n  ".join(available) if available else "(none saved yet)"
        raise SystemExit(
            f"no config {ref!r} in {store.root}/.\nAvailable:\n  {listing}"
        ) from None
    except ConfigValidationError as exc:
        problems = "\n  ".join(str(e) for e in exc.errors)
        raise SystemExit(f"config {ref!r} is invalid:\n  {problems}") from None


def config_from_metadata(metadata: str | None) -> AgentConfig | None:
    """Parse the config the API stamped onto the room, if there is one.

    Returns None — rather than raising — when the room has no metadata or the
    metadata belongs to something else, so the caller can fall back to the env
    var. Metadata that *looks* like ours but is invalid does raise, because
    silently ignoring it would start a call with the wrong agent.
    """
    if not metadata or not metadata.strip():
        return None
    try:
        raw = json.loads(metadata)
    except json.JSONDecodeError:
        logger.warning("room metadata is not JSON; falling back to %s", CONFIG_ENV)
        return None
    if not isinstance(raw, dict) or "prompt" not in raw:
        return None
    return parse_config(raw)


def room_metadata(ctx: JobContext) -> str | None:
    """Where to read the room's metadata from, inside a job entrypoint.

    **Not** `ctx.room.metadata`: the room object is not connected yet when the
    entrypoint runs, so that attribute is still empty. The job assignment carries
    the server's copy of the room record, metadata included, and it is available
    immediately. `ctx.room` is kept as a fallback for the console path.
    """
    from_job = getattr(getattr(ctx.job, "room", None), "metadata", "") or ""
    if from_job.strip():
        return from_job
    return (getattr(ctx.room, "metadata", "") or "") or None


@server.rtc_session()
async def session(ctx: JobContext) -> None:
    config = config_from_metadata(room_metadata(ctx))
    source = "room metadata"
    if config is None:
        config = resolve_config()
        source = CONFIG_ENV

    logger.info("config source: %s", source)
    logger.info(
        "starting session config=%s stt=%s llm=%s tts=%s",
        config.id or config.name,
        config.stt.provider,
        config.llm.provider,
        config.tts.provider,
    )

    agent_session: AgentSession[Any] = AgentSession(
        stt=build_stt(config.stt),
        llm=build_llm(config.llm),
        tts=build_tts(config.tts),
        vad=build_vad(config.vad),
    )
    await agent_session.start(room=ctx.room, agent=ConfiguredAgent(config))

    if config.prompt.greeting.strip():
        await agent_session.say(config.prompt.greeting)


def main() -> None:
    # Two ways to run:
    #   VOICE_AGENT_CONFIG set  -> one config, checked now so a typo fails fast
    #                              (`lk agent console`, terminal testing)
    #   VOICE_AGENT_CONFIG unset -> config arrives per room from the API
    #                              (`make worker`, the UI's Run button)
    if os.environ.get(CONFIG_ENV, "").strip():
        config = resolve_config()
        missing = missing_credentials(config)
        if missing:
            raise SystemExit(
                f"config {config.id!r} needs credentials that are not set: "
                f"{', '.join(missing)}\nAdd them to .env"
            )
        logger.info("pinned to config %s", config.id or config.name)
    else:
        logger.info("no %s set — taking config from room metadata", CONFIG_ENV)

    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=session))


if __name__ == "__main__":
    main()
