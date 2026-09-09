"""LeetCode Coach: a private, local weekly study-plan generator."""


def main() -> None:
    """CLI entry point, imported lazily to keep module execution clean."""
    from .cli import main as cli_main

    cli_main()
