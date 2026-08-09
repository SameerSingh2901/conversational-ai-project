#!/usr/bin/env python3
"""Bootstrap a new project from this workbench.

Run via `make init`, or directly:

    uv run --no-project python init.py

Pure standard library, no shell built-ins, so it behaves identically on
macOS, Linux, and Windows.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"

PY_CHOICES = [
    ("3.14", "newest stable"),
    ("3.13", "safest, widest library support"),
    ("3.12", "most conservative"),
]

DIST_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
PKG_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PY_VERSION_RE = re.compile(r"^3\.\d+$")


def fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def ask(label: str, default: str = "") -> str:
    shown = f"{label} [{default}]: " if default else f"{label}: "
    try:
        answer = input(shown).strip()
    except EOFError:
        if not default:
            fail(f"no input available for: {label}")
        answer = ""
    return answer or default


def ask_until(
    label: str,
    default: str,
    is_valid: Callable[[str], bool],
    complaint: str,
) -> str:
    """Keep asking until the answer is usable.

    Re-prompting rather than exiting matters: a hard exit throws away every
    answer already given. EOF (piped input) falls back to the default.
    """
    while True:
        answer = ask(label, default)
        if is_valid(answer):
            return answer
        print(f"{complaint}: {answer}", file=sys.stderr)


def ask_yes_no(prompt: str, *, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer.startswith("y")


def to_dist_name(raw: str) -> str:
    """Directory name -> plausible distribution name."""
    return re.sub(r"[_\s]+", "-", raw.strip().lower())


def to_pkg_name(dist: str) -> str:
    """Distribution name -> importable package name."""
    return re.sub(r"[-.]+", "_", dist.strip().lower())


def run(*args: str) -> None:
    """Run a command, streaming output. `uv` is resolved via PATH."""
    exe = shutil.which(args[0])
    if exe is None:
        fail(f"{args[0]} not found on PATH")
    subprocess.run([exe, *args[1:]], cwd=ROOT, check=True)


def read_pyproject() -> str:
    return PYPROJECT.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Always LF, so a Windows checkout does not flip line endings."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def sub_once(pattern: str, replacement: str, text: str) -> str:
    """Replace the first match, and require that there was one."""
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        fail(f"expected exactly one match for {pattern!r} in pyproject.toml")
    return new_text


def current_package() -> str:
    candidates = [p.name for p in (ROOT / "src").iterdir() if p.is_dir()]
    if len(candidates) != 1:
        fail(f"expected exactly one package under src/, found: {candidates}")
    return candidates[0]


def current_project() -> str:
    match = re.search(r'^name = "(.+)"$', read_pyproject(), flags=re.MULTILINE)
    if match is None:
        fail("could not find the project name in pyproject.toml")
    return match.group(1)


def choose_python() -> str:
    print("Python version for this project?")
    for index, (version, blurb) in enumerate(PY_CHOICES, start=1):
        print(f"  Type {index} for {version}  - {blurb}")
    other = str(len(PY_CHOICES) + 1)
    print(f"  Type {other} for another version (you will be asked which)")

    while True:
        raw = ask("Choice")
        if raw.lower() in {other, "other"}:
            version = ask("Version (e.g. 3.13)")
        elif raw.isdigit() and 1 <= int(raw) <= len(PY_CHOICES):
            version = PY_CHOICES[int(raw) - 1][0]
        else:
            # Typing "3.13" straight in is the obvious thing to try.
            version = raw
        if PY_VERSION_RE.match(version):
            return version
        print(f"answer 1-{other}, or a version like 3.13, not: {raw}", file=sys.stderr)


# Accept the numbers and the words, because people type the words.
ASYNC_ANSWERS = {
    "1": True,
    "y": True,
    "yes": True,
    "2": False,
    "n": False,
    "no": False,
    "3": False,
    "u": False,
    "unsure": False,
    "not sure": False,
    "dunno": False,
}


def choose_async() -> bool:
    print("Will this project use async code?")
    print("  Type 1 for yes     - adds pytest-asyncio with asyncio_mode = auto")
    print("  Type 2 for no      - adds nothing")
    print("  Type 3 for unsure  - adds nothing; add it later if you need it")
    while True:
        raw = ask("Choice").lower()
        if raw in ASYNC_ANSWERS:
            return ASYNC_ANSWERS[raw]
        print(f"answer 1/2/3 or yes/no/unsure, not: {raw}", file=sys.stderr)


def rewrite_sources(old: str, new: str) -> None:
    """Replace an identifier across src/ and tests/ .py files."""
    if old == new:
        return
    for directory in ("src", "tests"):
        for path in (ROOT / directory).rglob("*.py"):
            original = path.read_text(encoding="utf-8")
            updated = original.replace(old, new)
            if updated != original:
                write_text(path, updated)


def clear_pycache() -> None:
    for directory in ("src", "tests"):
        for path in (ROOT / directory).rglob("__pycache__"):
            shutil.rmtree(path, ignore_errors=True)


def main() -> None:
    old_pkg = current_package()
    old_project = current_project()

    python_version = choose_python()

    project = ask_until(
        "Project name",
        to_dist_name(ROOT.name),
        lambda value: bool(DIST_NAME_RE.match(value)),
        "not a valid distribution name",
    )
    package = ask_until(
        "Package name",
        to_pkg_name(project),
        lambda value: bool(PKG_NAME_RE.match(value)),
        "not a valid Python package name",
    )

    description = ask("Short description (blank to skip)").replace('"', "")
    use_async = choose_async()
    want_git = not (ROOT / ".git").exists() and ask_yes_no(
        "Initialize a fresh git repository?"
    )
    if (ROOT / ".git").exists():
        print("note: .git already exists; skipping git init.")
        print("      Delete it yourself if you want a fresh history.")

    # --- apply ---------------------------------------------------------------
    write_text(ROOT / ".python-version", f"{python_version}\n")
    print(f"Pinned {python_version} -> .python-version")

    text = read_pyproject()
    text = sub_once(r'^name = ".+"$', f'name = "{project}"', text)
    text = sub_once(r"^version = .+$", 'version = "0.1.0"', text)
    text = sub_once(
        r"^requires-python = .+$", f'requires-python = ">={python_version}"', text
    )
    if description:
        text = sub_once(r"^description = .*$", f'description = "{description}"', text)

    # This script is meant to be deleted after bootstrapping, so drop it from
    # mypy's scope; otherwise `make check` breaks the moment it is removed.
    # The workbench repo itself keeps it listed and type-checked.
    text = text.replace(
        'files = ["init.py", "src", "tests"]', 'files = ["src", "tests"]'
    )

    # uv_build infers the module name from the project name; state it only when
    # the two disagree.
    if package != to_pkg_name(project) and "[tool.uv.build-backend]" not in text:
        text += f'\n[tool.uv.build-backend]\nmodule-name = "{package}"\n'
        print(f"Set module-name={package} -> pyproject.toml")

    write_text(PYPROJECT, text)
    print(f"Set name={project}, version=0.1.0, requires-python=>={python_version}")
    if description:
        print("Set description -> pyproject.toml")

    # This README documents the workbench, which is of no use inside your
    # project. Start from a blank one.
    write_text(ROOT / "README.md", "")
    print("Emptied README.md")

    # Likewise the licence: it covers the workbench, and licensing your project
    # is your call, not something to inherit by accident.
    licence = ROOT / "LICENSE"
    if licence.exists():
        licence.unlink()
        print("Removed LICENSE - add your own if you need one")

    clear_pycache()
    if package != old_pkg:
        (ROOT / "src" / old_pkg).rename(ROOT / "src" / package)
        rewrite_sources(old_pkg, package)
        print(f"Renamed src/{old_pkg} -> src/{package}")
    rewrite_sources(old_project, project)

    # --- environment ---------------------------------------------------------
    print("Running uv sync...")
    run("uv", "sync")

    if use_async:
        run("uv", "add", "--dev", "pytest-asyncio")
        text = read_pyproject()
        text = sub_once(
            r'^testpaths = \["tests"\]$',
            'testpaths = ["tests"]\nasyncio_mode = "auto"',
            text,
        )
        write_text(PYPROJECT, text)
        print("Added pytest-asyncio with asyncio_mode = auto.")

    # --- git (last, so the first commit contains everything above) -----------
    if want_git:
        run("git", "init", "-q")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "Initial commit")
        print("Initialized git repository with an initial commit.")

    print("Done. Try: make check")

    this_file = Path(__file__).name
    removal = f"git rm {this_file}" if want_git else f"rm {this_file}"
    print("\nThis bootstrap script has done its job. Delete it when ready:")
    print(f"    {removal}")


if __name__ == "__main__":
    main()
