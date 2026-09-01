"""Allow ``python -m quattro_agent`` to invoke the public CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
