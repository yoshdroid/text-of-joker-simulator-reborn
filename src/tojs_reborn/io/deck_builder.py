from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.state import CardDefinition, load_card_catalog

from .gui_view_model import find_card_image


DECK_SIZE = 40
MAX_COPIES = 3


@dataclass(frozen=True)
class DeckRegulationStatus:
    passed: bool
    total_cards: int
    over_limit: dict[str, int]
    messages: tuple[str, ...]


def run_deck_builder_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a mouse-driven deck builder GUI.")
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--images", default="carddata/images")
    parser.add_argument("--deck-dir", default="decklists")
    parser.add_argument("--deck-name", default="new_deck")
    parser.add_argument("--no-window", action="store_true", help="Print card count and exit without opening Tk.")
    args = parser.parse_args(argv)

    try:
        card_catalog = load_card_catalog(args.cards)
        if args.no_window:
            print(json.dumps({"card_count": len(card_catalog)}, ensure_ascii=False, separators=(",", ":")))
            return 0
        DeckBuilderTkGui(
            card_catalog=card_catalog,
            images_dir=Path(args.images),
            deck_dir=Path(args.deck_dir),
            deck_name=args.deck_name,
        ).run()
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"deck builder failed: {exc}", file=sys.stderr)
        return 1
    return 0


def regulation_status(card_nos: Sequence[str]) -> DeckRegulationStatus:
    counts = Counter(card_nos)
    over_limit = {card_no: count for card_no, count in sorted(counts.items()) if count > MAX_COPIES}
    messages: list[str] = []
    if len(card_nos) != DECK_SIZE:
        messages.append(f"deck size must be {DECK_SIZE}: current={len(card_nos)}")
    if over_limit:
        detail = ", ".join(f"{card_no}={count}" for card_no, count in over_limit.items())
        messages.append(f"copy limit must be <= {MAX_COPIES}: {detail}")
    return DeckRegulationStatus(
        passed=not messages,
        total_cards=len(card_nos),
        over_limit=over_limit,
        messages=tuple(messages),
    )


def decklist_json(deck_name: str, card_nos: Sequence[str], card_catalog: dict[str, CardDefinition]) -> dict[str, Any]:
    counts = Counter(card_nos)
    return {
        "deck_name": deck_name,
        "joker": "JK-01",
        "cards": [
            {"card_name": card_catalog[card_no].name, "count": count}
            for card_no, count in sorted(counts.items(), key=lambda item: _card_sort_key(item[0], card_catalog))
        ],
    }


def card_detail_text(card_no: str, card: CardDefinition) -> str:
    lines = [
        f"{card.name} ({card_no})",
        f"category={card.category} color={card.color} cp={card.cp if card.cp is not None else '-'} race={card.race or '-'}",
    ]
    if card.bp_by_level:
        lines.append("BP " + "/".join(str(value) for value in card.bp_by_level))
    if not card.abilities:
        lines.append("abilities: none")
    for ability in card.abilities:
        lines.extend(
            [
                "",
                f"[{ability.status}] {ability.name}",
                f"timing={ability.timing} optional={ability.optional}",
            ]
        )
        source_text = ability.raw.get("source_text")
        if source_text:
            lines.append(str(source_text))
        condition = ability.raw.get("condition")
        if condition is not None:
            lines.append("condition=" + json.dumps(condition, ensure_ascii=False))
        selector = ability.raw.get("selector")
        if selector is not None:
            lines.append("selector=" + json.dumps(selector, ensure_ascii=False))
        cost_steps = ability.raw.get("cost_steps") or []
        if cost_steps:
            lines.append("cost=" + json.dumps(cost_steps, ensure_ascii=False))
        effect_steps = ability.raw.get("effect_steps") or []
        if effect_steps:
            lines.append("effects=" + json.dumps(effect_steps, ensure_ascii=False))
    return "\n".join(lines)


def filtered_card_nos(
    card_catalog: dict[str, CardDefinition],
    *,
    search: str = "",
    color: str = "all",
    category: str = "all",
) -> list[str]:
    needle = search.strip().lower()
    result = []
    for card_no, card in card_catalog.items():
        if color != "all" and card.color != color:
            continue
        if category != "all" and card.category != category:
            continue
        if needle and needle not in f"{card_no} {card.name}".lower():
            continue
        result.append(card_no)
    return sorted(result, key=lambda card_no: _card_sort_key(card_no, card_catalog))


class DeckBuilderTkGui:
    def __init__(
        self,
        *,
        card_catalog: dict[str, CardDefinition],
        images_dir: Path,
        deck_dir: Path,
        deck_name: str,
    ) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.card_catalog = card_catalog
        self.images_dir = images_dir
        self.deck_dir = deck_dir
        self.deck_card_nos: list[str] = []
        self.image_cache: dict[tuple[str, int, int], Any] = {}
        self.card_items: dict[int, str] = {}
        self.tile_width = 72
        self.tile_height = 102

        self.root = tk.Tk()
        self.root.title("TOJ Reborn Deck Builder")
        self.root.geometry("1500x900")
        self.root.configure(bg="#171b20")

        self.search_var = tk.StringVar()
        self.color_var = tk.StringVar(value="all")
        self.category_var = tk.StringVar(value="all")
        self.deck_name_var = tk.StringVar(value=deck_name)
        self.status_var = tk.StringVar()

        self._build_layout()
        self._bind_filters()
        self._refresh_card_pool()
        self._refresh_deck()

    def run(self) -> None:
        self.root.mainloop()

    def _build_layout(self) -> None:
        toolbar = self.tk.Frame(self.root, bg="#222831")
        toolbar.pack(fill=self.tk.X)
        self.tk.Label(toolbar, text="Search", bg="#222831", fg="#f2f5f8").pack(side=self.tk.LEFT, padx=(8, 3))
        self.ttk.Entry(toolbar, textvariable=self.search_var, width=24).pack(side=self.tk.LEFT, padx=3, pady=6)
        self.tk.Label(toolbar, text="Color", bg="#222831", fg="#f2f5f8").pack(side=self.tk.LEFT, padx=(12, 3))
        self.ttk.Combobox(toolbar, textvariable=self.color_var, values=self._color_values(), width=8, state="readonly").pack(side=self.tk.LEFT, padx=3)
        self.tk.Label(toolbar, text="Category", bg="#222831", fg="#f2f5f8").pack(side=self.tk.LEFT, padx=(12, 3))
        self.ttk.Combobox(toolbar, textvariable=self.category_var, values=self._category_values(), width=10, state="readonly").pack(side=self.tk.LEFT, padx=3)
        self.tk.Label(toolbar, text="Deck", bg="#222831", fg="#f2f5f8").pack(side=self.tk.LEFT, padx=(18, 3))
        self.ttk.Entry(toolbar, textvariable=self.deck_name_var, width=22).pack(side=self.tk.LEFT, padx=3)
        self.ttk.Button(toolbar, text="Save", command=self._save_deck).pack(side=self.tk.LEFT, padx=8)
        self.tk.Label(toolbar, textvariable=self.status_var, bg="#222831", fg="#f2f5f8").pack(side=self.tk.RIGHT, padx=10)

        main = self.tk.PanedWindow(self.root, orient=self.tk.HORIZONTAL, bg="#171b20", sashwidth=8, showhandle=True)
        main.pack(fill=self.tk.BOTH, expand=True)

        left = self.tk.Frame(main, bg="#171b20")
        self.card_canvas = self.tk.Canvas(left, bg="#171b20", highlightthickness=0)
        pool_scroll = self.ttk.Scrollbar(left, orient=self.tk.VERTICAL, command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=pool_scroll.set)
        self.card_canvas.pack(side=self.tk.LEFT, fill=self.tk.BOTH, expand=True)
        pool_scroll.pack(side=self.tk.RIGHT, fill=self.tk.Y)

        right = self.tk.Frame(main, bg="#171b20")
        self.detail = self.tk.Text(right, height=14, bg="#101419", fg="#dbe2ea", wrap=self.tk.WORD, font=("Consolas", 9))
        self.detail.pack(fill=self.tk.X, padx=8, pady=(8, 4))
        self.deck_list = self.tk.Listbox(right, bg="#101419", fg="#dbe2ea", selectbackground="#3f5268", font=("Consolas", 10))
        deck_scroll = self.ttk.Scrollbar(right, orient=self.tk.VERTICAL, command=self.deck_list.yview)
        self.deck_list.configure(yscrollcommand=deck_scroll.set)
        self.deck_list.pack(side=self.tk.LEFT, fill=self.tk.BOTH, expand=True, padx=(8, 0), pady=(4, 8))
        deck_scroll.pack(side=self.tk.RIGHT, fill=self.tk.Y, pady=(4, 8), padx=(0, 8))
        self.deck_list.bind("<Double-Button-1>", self._remove_selected_deck_card)

        main.add(left, minsize=760, stretch="always")
        main.add(right, minsize=420, stretch="always")

    def _bind_filters(self) -> None:
        self.search_var.trace_add("write", lambda *_args: self._refresh_card_pool())
        self.color_var.trace_add("write", lambda *_args: self._refresh_card_pool())
        self.category_var.trace_add("write", lambda *_args: self._refresh_card_pool())

    def _refresh_card_pool(self) -> None:
        self.card_canvas.delete("all")
        self.card_items.clear()
        width = max(self.card_canvas.winfo_width(), 760)
        columns = max(1, width // (self.tile_width + 12))
        for index, card_no in enumerate(
            filtered_card_nos(
                self.card_catalog,
                search=self.search_var.get(),
                color=self.color_var.get(),
                category=self.category_var.get(),
            )
        ):
            row, column = divmod(index, columns)
            x = 8 + column * (self.tile_width + 12)
            y = 8 + row * (self.tile_height + 28)
            self._draw_card_tile(card_no, x, y)
        self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all"))

    def _draw_card_tile(self, card_no: str, x: int, y: int) -> None:
        card = self.card_catalog[card_no]
        tag = f"card_{card_no.replace('-', '_')}"
        self.card_canvas.create_rectangle(
            x,
            y,
            x + self.tile_width,
            y + self.tile_height,
            fill="#303842",
            outline="#465360",
            tags=(tag,),
        )
        image = self._load_image(card_no)
        if image is not None:
            self.card_canvas.create_image(x, y, anchor="nw", image=image, tags=(tag,))
        else:
            self.card_canvas.create_text(
                x + self.tile_width // 2,
                y + self.tile_height // 2,
                text=f"{card_no}\n{card.name}",
                fill="#f2f5f8",
                width=self.tile_width - 6,
                font=("TkDefaultFont", 8),
                tags=(tag,),
            )
        label = self._short_label(card.name)
        self.card_canvas.create_text(
            x,
            y + self.tile_height + 3,
            anchor="nw",
            text=label,
            fill="#dbe2ea",
            width=self.tile_width,
            font=("TkDefaultFont", 8),
            tags=(tag,),
        )
        item = self.card_canvas.create_rectangle(
            x,
            y,
            x + self.tile_width,
            y + self.tile_height + 22,
            outline="#171b20",
            fill="",
            tags=(tag,),
        )
        self.card_items[item] = card_no
        self.card_canvas.tag_bind(tag, "<Button-1>", lambda _event, selected=card_no: self._add_card(selected))
        self.card_canvas.tag_bind(tag, "<Enter>", lambda _event, selected=card_no: self._show_card_detail(selected))

    def _load_image(self, card_no: str) -> Any | None:
        path = find_card_image(self.images_dir, card_no)
        if path is None:
            return None
        cache_key = (path, self.tile_width, self.tile_height)
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        try:
            from PIL import Image, ImageTk

            image = Image.open(path)
            image.thumbnail((self.tile_width, self.tile_height))
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return None
        self.image_cache[cache_key] = photo
        return photo

    def _show_card_detail(self, card_no: str) -> None:
        self.detail.configure(state=self.tk.NORMAL)
        self.detail.delete("1.0", self.tk.END)
        self.detail.insert(self.tk.END, card_detail_text(card_no, self.card_catalog[card_no]))
        self.detail.configure(state=self.tk.DISABLED)

    def _add_card(self, card_no: str) -> None:
        self.deck_card_nos.append(card_no)
        self._refresh_deck()

    def _remove_selected_deck_card(self, _event: Any | None = None) -> None:
        selection = self.deck_list.curselection()
        if not selection:
            return
        line = self.deck_list.get(selection[0])
        card_no = line.split(" ", 1)[0]
        if card_no in self.deck_card_nos:
            self.deck_card_nos.remove(card_no)
        self._refresh_deck()

    def _refresh_deck(self) -> None:
        self.deck_list.delete(0, self.tk.END)
        counts = Counter(self.deck_card_nos)
        for card_no, count in sorted(counts.items(), key=lambda item: _card_sort_key(item[0], self.card_catalog)):
            card = self.card_catalog[card_no]
            self.deck_list.insert(self.tk.END, f"{card_no} x{count} {card.name}")
        status = regulation_status(self.deck_card_nos)
        state = "PASS" if status.passed else "VIOLATE"
        detail = "; ".join(status.messages) if status.messages else "regulation ok"
        self.status_var.set(f"{state} {status.total_cards}/{DECK_SIZE}  {detail}")

    def _save_deck(self) -> None:
        deck_name = self.deck_name_var.get().strip() or "unnamed"
        safe_name = _safe_filename(deck_name)
        data = decklist_json(deck_name, self.deck_card_nos, self.card_catalog)
        self.deck_dir.mkdir(parents=True, exist_ok=True)
        path = self.deck_dir / f"{safe_name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        status = regulation_status(self.deck_card_nos)
        state = "PASS" if status.passed else "VIOLATE"
        self.messagebox.showinfo("Deck saved", f"{path}\n{state}: {status.total_cards}/{DECK_SIZE}")

    def _color_values(self) -> list[str]:
        return ["all"] + sorted({card.color for card in self.card_catalog.values() if card.color})

    def _category_values(self) -> list[str]:
        return ["all"] + sorted({card.category for card in self.card_catalog.values() if card.category})

    def _short_label(self, value: str) -> str:
        return value if len(value) <= 14 else value[:13] + "..."


def _card_sort_key(card_no: str, card_catalog: dict[str, CardDefinition]) -> tuple[str, int, str, str]:
    card = card_catalog[card_no]
    return (card.color, card.cp if card.cp is not None else 99, card.category, card_no)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "unnamed"


def main() -> None:
    raise SystemExit(run_deck_builder_cli())


if __name__ == "__main__":
    main()
