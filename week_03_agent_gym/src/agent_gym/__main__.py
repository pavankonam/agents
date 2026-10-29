"""python -m agent_gym list | run TASK [--model M] [--max-steps N] [--json]"""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
