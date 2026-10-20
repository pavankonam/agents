"""`python -m guarded_agent ...` entry point. See cli.py for commands and options."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
