"""Command-line entry point. Subcommands are added by later prompts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from themi import __version__
from themi.storage.secrets import generate_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="themi", description="Themi household assistant")
    parser.add_argument("--version", action="version", version=f"themi {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "keygen", help="print a new secret key for THEMI_SECRET_KEY (keep it safe and backed up)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "keygen":
        print(generate_key())
        return 0
    parser.print_help()
    return 0
