#!/usr/bin/env python3
"""Fail closed when a stale Analook checkout is used for deployment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TRACKED_FILES = (
    "app.py",
    "Dockerfile",
    "fly.toml",
    "static/llms.txt",
    "static/robots.txt",
    "static/sitemap.xml",
)
EXPECTED_REMOTE_SUFFIX = "Gingiris-1031/Competitor-analysis-tool.git"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def main() -> int:
    errors: list[str] = []

    try:
        remote = git("remote", "get-url", "origin")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        errors.append(f"cannot resolve git origin: {exc}")
        remote = ""

    if remote and not remote.rstrip("/").endswith(EXPECTED_REMOTE_SUFFIX):
        errors.append(f"unexpected origin: {remote}")

    branch = git("branch", "--show-current")
    if branch != "main":
        errors.append(f"production deploys must run from main, not {branch or 'detached HEAD'}")

    for relative in REQUIRED_TRACKED_FILES:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"required deploy asset missing: {relative}")
            continue
        try:
            git("ls-files", "--error-unmatch", relative)
        except subprocess.CalledProcessError:
            errors.append(f"required deploy asset is not tracked by git: {relative}")

    try:
        behind = int(git("rev-list", "--count", "HEAD..origin/main"))
        if behind:
            errors.append(f"checkout is {behind} commit(s) behind origin/main")
    except (subprocess.CalledProcessError, ValueError):
        errors.append("cannot compare HEAD with origin/main; run git fetch first")

    if errors:
        print("Analook deploy-source verification FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Analook deploy source OK: {ROOT}")
    print(f"HEAD: {git('rev-parse', '--short', 'HEAD')}")
    print("Required SEO/GEO assets: llms.txt, robots.txt, sitemap.xml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
