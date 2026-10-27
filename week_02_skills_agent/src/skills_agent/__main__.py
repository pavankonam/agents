"""python -m skills_agent COMMAND ...  (list, validate, inspect, run, doctor; see cli.py).

The day 1 short form still works: python -m skills_agent [--budget N] "task".
"""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
