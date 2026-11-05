"""python3 -m evidence_agent list | check | run SCENARIO [--model M] [--max-steps N] [--json] [--record PATH]"""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
