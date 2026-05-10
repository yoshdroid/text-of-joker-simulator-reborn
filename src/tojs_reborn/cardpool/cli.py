from __future__ import annotations

import argparse
from pathlib import Path

from .normalizer import write_normalized_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Text of Joker card pool data.")
    parser.add_argument("--excel", default="carddata/text-of-joker.cardpool.xlsx")
    parser.add_argument("--mapping", default="carddata/manual/ability_mapping.json")
    parser.add_argument("--output-dir", default="carddata/generated")
    args = parser.parse_args()

    cards_path, report_path = write_normalized_outputs(
        Path(args.excel),
        Path(args.mapping),
        Path(args.output_dir),
    )
    print(f"wrote {cards_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()

