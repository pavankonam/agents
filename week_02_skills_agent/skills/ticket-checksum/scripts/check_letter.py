"""Check letter for team ticket IDs: XX-NNNNN or XX-NNNNN-L.

Usage: python3 check_letter.py HX-40217      -> prints HX-40217-<letter>
       python3 check_letter.py HX-40217-Q    -> prints VALID or INVALID (expected ...)
Exit codes: 0 ok or valid, 1 invalid letter, 2 bad format.
"""

import re
import sys

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXY"  # 23 letters, no I, O or Z
WEIGHTS = [7, 3, 1, 7, 3, 1, 7]


def check_letter(prefix: str, digits: str) -> str:
    values = [ord(c) - ord("A") + 10 for c in prefix] + [int(d) for d in digits]
    total = sum(v * w for v, w in zip(values, WEIGHTS))
    return ALPHABET[total % len(ALPHABET)]


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_letter.py XX-NNNNN[-L]", file=sys.stderr)
        return 2
    m = re.fullmatch(r"([A-Z]{2})-(\d{5})(?:-([A-Z]))?", argv[0].strip().upper())
    if not m:
        print(f"bad ticket ID {argv[0]!r}; expected format XX-NNNNN", file=sys.stderr)
        return 2
    prefix, digits, given = m.groups()
    letter = check_letter(prefix, digits)
    if given is None:
        print(f"{prefix}-{digits}-{letter}")
        return 0
    if given == letter:
        print(f"VALID {prefix}-{digits}-{letter}")
        return 0
    print(f"INVALID {prefix}-{digits}-{given} (expected check letter {letter})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
