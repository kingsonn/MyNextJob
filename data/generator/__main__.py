"""Generate, validate, publish, and optionally load Postgres."""

from __future__ import annotations

import sys

from generator.build import generate
from generator.config import load_config
from generator.load import load_postgres
from generator.publish import publish
from generator.validate import all_problems


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in (["write"], ["seed"]):
        raise SystemExit("usage: python -m generator write|seed")
    config = load_config()
    dataset = generate(config)
    problems = all_problems(dataset, config)
    if problems:
        raise SystemExit("generator validation failed:\n" + "\n".join(problems))
    publish(dataset)
    if args == ["seed"]:
        load_postgres(dataset)


if __name__ == "__main__":
    main()
