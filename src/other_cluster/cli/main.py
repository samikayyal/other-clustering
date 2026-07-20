"""Help-only CLI scaffolding for later command implementations."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="other-cluster",
        description="Cluster prepared survey Other answers with auditable outputs.",
    )
    commands = parser.add_subparsers(dest="command", title="planned commands")
    for command in ("template", "validate", "estimate", "preview", "run"):
        commands.add_parser(command, help="Reserved for a later implementation slice.")

    cache = commands.add_parser("cache", help="Inspect or purge the provider cache.")
    cache_commands = cache.add_subparsers(dest="cache_command", title="cache commands")
    for command in ("inspect", "purge"):
        cache_commands.add_parser(
            command, help="Reserved for a later implementation slice."
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the placeholder command registry without performing application work."""
    build_parser().parse_args(argv)
    return 0
