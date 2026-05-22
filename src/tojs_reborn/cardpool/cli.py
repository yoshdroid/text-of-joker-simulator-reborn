from __future__ import annotations

import argparse
import json
from pathlib import Path

from .normalizer import write_normalized_outputs
from .status_report import build_card_status_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Text of Joker card pool data.")
    parser.add_argument("--excel", default="carddata/text-of-joker.cardpool.xlsx")
    parser.add_argument("--mapping", default="carddata/manual/ability_mapping.json")
    parser.add_argument("--output-dir", default="carddata/generated")
    parser.add_argument("--status-markdown", help="Write a generated card implementation status table.")
    args = parser.parse_args()

    cards_path, report_path = write_normalized_outputs(
        Path(args.excel),
        Path(args.mapping),
        Path(args.output_dir),
    )
    if args.status_markdown:
        normalized = json.loads(cards_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        status_path = Path(args.status_markdown)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(build_card_status_markdown(normalized, report), encoding="utf-8", newline="\n")
        print(f"wrote {status_path}")
    print(f"wrote {cards_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
