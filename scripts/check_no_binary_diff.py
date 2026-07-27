#!/usr/bin/env python
"""Fail when a proposed Git diff contains binary file changes."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alt_asset_explorer.git_checks import binary_paths  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="HEAD^", help="Base revision for the proposed diff")
    args = parser.parse_args()
    output = subprocess.run(
        ["git", "diff", "--numstat", args.base, "--"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    paths = binary_paths(output)
    if paths:
        raise SystemExit("Unsupported binary changes:\n- " + "\n- ".join(paths))
    print("No binary files in proposed diff.")


if __name__ == "__main__":
    main()
