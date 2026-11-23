"""Eval command line.

    uv run python -m evals validate        # parse the golden set, print counts (no LLM calls)
    uv run python -m evals run [...]       # run items against the live agent (see `run --help`)
    uv run python -m evals scrape-bench    # fetch-waterfall benchmark on real URLs
    uv run python -m evals fixtures        # serve the fixture site on :8765 for manual poking
"""

import argparse
import logging
import sys


def main() -> None:
    """Parse arguments and dispatch to the chosen command (imports are lazy to keep `validate` fast)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(prog="evals")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="check the golden dataset parses")
    r = sub.add_parser("run", help="run the golden set against the live agent")
    r.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    r.add_argument("--split", choices=["dev", "holdout"])
    r.add_argument("--ids", help="comma-separated item ids")
    r.add_argument("--no-judge", action="store_true", help="skip LLM-judge scoring (saves quota)")
    r.add_argument("--langsmith", action="store_true", help="attach scores to LangSmith traces")
    sub.add_parser("scrape-bench", help="benchmark the fetch waterfall on ~35 real URLs")
    sub.add_parser("fixtures", help="serve the fixture site on :8765")
    args = ap.parse_args()

    if args.cmd == "validate":
        from collections import Counter

        from .runner import DATA
        from .schema import load

        items = load(DATA, "http://127.0.0.1:8765")
        print(f"{len(items)} items OK · smoke {sum(i.smoke for i in items)} · holdout {sum(i.split == 'holdout' for i in items)}")
        print(dict(Counter(i.category for i in items)))
        turns = [t for i in items for t in i.all_turns()]
        print(f"turns {len(turns)} · routes {dict(Counter(t.expected_mode for t in turns))} · "
              f"difficulty {dict(Counter(i.difficulty for i in items))}")
    elif args.cmd == "run":
        from .runner import main_run

        main_run(args)
    elif args.cmd == "scrape-bench":
        from .scrape_bench import main as bench

        bench()
    else:
        import uvicorn

        from .fixtures_site import PORT, app

        uvicorn.run(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
