from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from tojs_reborn.engine.state import CardDefinition, load_card_catalog

from .replay_gui_model import build_replay_gui_model


DEFAULT_REPLAY_CARD_WIDTH = 36


def run_replay_gui_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open a seekable replay GUI.")
    parser.add_argument("--replay", required=True)
    parser.add_argument("--cards", default="carddata/generated/cards.normalized.json")
    parser.add_argument("--images", default="carddata/images")
    parser.add_argument("--start-event-no", type=int)
    parser.add_argument("--card-width", type=int, default=DEFAULT_REPLAY_CARD_WIDTH)
    parser.add_argument("--no-window", action="store_true", help="Print the selected frame summary instead of opening Tk.")
    args = parser.parse_args(argv)

    try:
        replay_record = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        card_catalog = _load_optional_card_catalog(args.cards)
        model = build_replay_gui_model(replay_record, card_catalog=card_catalog, images_dir=args.images)
        frame_index = _frame_index_for_event_no(model["frames"], args.start_event_no)
        if args.no_window:
            print(json.dumps(_frame_summary(model, frame_index), ensure_ascii=False, separators=(",", ":")))
            return 0
        ReplayTkGui(model=model, start_frame_index=frame_index, card_width=args.card_width).run()
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"replay GUI failed: {exc}", file=sys.stderr)
        return 1
    return 0


class ReplayTkGui:
    def __init__(self, *, model: dict[str, Any], start_frame_index: int, card_width: int) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.model = model
        self.frames: list[dict[str, Any]] = list(model.get("frames") or [])
        self.frame_index = start_frame_index
        self.card_width = card_width
        self.card_height = int(card_width * 1.42)
        self.image_cache: dict[tuple[str, int], Any] = {}
        self.playing = False
        self._updating_scale = False
        self._sash_initialized = False

        self.root = tk.Tk()
        self.root.title("TOJ Reborn Replay GUI")
        self.root.geometry("1360x860")
        self.root.configure(bg="#171b20")

        self.main = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            bg="#171b20",
            sashwidth=8,
            sashrelief=tk.RAISED,
            showhandle=True,
        )
        self.main.pack(fill=tk.BOTH, expand=True)
        self.board_canvas = tk.Canvas(self.main, bg="#171b20", highlightthickness=0)
        self.log = tk.Text(
            self.main,
            bg="#101419",
            fg="#dbe2ea",
            insertbackground="#dbe2ea",
            font=("Consolas", 9),
            wrap=tk.NONE,
        )
        self.main.add(self.board_canvas, minsize=360, stretch="always")
        self.main.add(self.log, minsize=360, stretch="always")

        self.controls = tk.Frame(self.root, bg="#222831")
        self.controls.pack(fill=tk.X)
        self.play_button = ttk.Button(self.controls, text="Play", command=self.toggle_play)
        self.play_button.pack(side=tk.LEFT, padx=6, pady=6)
        ttk.Button(self.controls, text="Prev", command=lambda: self.go(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(self.controls, text="Next", command=lambda: self.go(1)).pack(side=tk.LEFT, padx=2)
        max_index = max(len(self.frames) - 1, 0)
        self.scale = ttk.Scale(self.controls, from_=0, to=max_index, orient=tk.HORIZONTAL, command=self.seek)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.position = tk.Label(self.controls, bg="#222831", fg="#f2f5f8", width=18, anchor="e")
        self.position.pack(side=tk.RIGHT, padx=8)

        self.root.bind_all("<Escape>", lambda _event: self.root.destroy())
        self.root.bind_all("<space>", lambda _event: self.toggle_play())
        self.root.bind_all("<Left>", lambda _event: self.go(-1))
        self.root.bind_all("<Right>", lambda _event: self.go(1))

    def run(self) -> None:
        self.render()
        self.root.mainloop()

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_button.configure(text="Pause" if self.playing else "Play")
        if self.playing:
            self.root.after(450, self._play_tick)

    def _play_tick(self) -> None:
        if not self.playing:
            return
        if self.frame_index >= len(self.frames) - 1:
            self.playing = False
            self.play_button.configure(text="Play")
            return
        self.go(1)
        self.root.after(450, self._play_tick)

    def go(self, delta: int) -> None:
        self.frame_index = max(0, min(len(self.frames) - 1, self.frame_index + delta))
        self.render()

    def seek(self, value: str) -> None:
        if self._updating_scale:
            return
        self.frame_index = max(0, min(len(self.frames) - 1, int(float(value))))
        self.render()

    def render(self) -> None:
        if not self.frames:
            return
        self._initialize_sash()
        frame = self.frames[self.frame_index]
        self.board_canvas.delete("all")
        self._render_board(frame)
        self._render_log(frame)
        self._updating_scale = True
        try:
            self.scale.set(self.frame_index)
        finally:
            self._updating_scale = False
        self.position.configure(text=f"{self.frame_index}/{len(self.frames) - 1}")

    def _initialize_sash(self) -> None:
        if self._sash_initialized:
            return
        width = self.main.winfo_width()
        if width <= 1:
            self.root.after(50, self.render)
            return
        self.main.sash_place(0, width // 2, 0)
        self._sash_initialized = True

    def _render_board(self, frame: dict[str, Any]) -> None:
        event = frame.get("current_event") or {}
        header = (
            f"Replay seed={self.model.get('seed')} R{frame.get('round_no')} T{frame.get('turn_no')} "
            f"turn={frame.get('turn_player_id')}"
        )
        self.board_canvas.create_text(16, 12, anchor="nw", fill="#f2f5f8", font=("TkDefaultFont", 13, "bold"), text=header)
        self.board_canvas.create_text(
            16,
            38,
            anchor="nw",
            fill="#cbd5df",
            font=("TkDefaultFont", 10),
            text=event.get("description") or "Initial state",
        )
        y = 72
        for player in frame.get("players") or []:
            y = self._render_player(y, player)

    def _render_player(self, y: int, player: dict[str, Any]) -> int:
        status = player.get("status") or {}
        title = (
            f"{player.get('player_id')}  LIFE {status.get('life')}  CP {status.get('current_cp')}  "
            f"HAND {status.get('hand_count')}  DECK {status.get('deck_count')}  "
            f"DISCARD {status.get('discard_count')}  TRIGGER {status.get('trigger_zone_count')}"
        )
        self.board_canvas.create_text(16, y, anchor="nw", fill="#f2f5f8", font=("TkDefaultFont", 11, "bold"), text=title)
        y += 24
        for label, zone in (
            ("Battlefield", "battlefield"),
            ("Hand", "hand"),
            ("Trigger", "trigger_zone"),
            ("Discard", "discard_pile"),
            ("Deck", "deck"),
        ):
            y = self._render_zone(y, label, player.get(zone) or [])
        return y + 8

    def _render_zone(self, y: int, label: str, tiles: list[dict[str, Any]]) -> int:
        self.board_canvas.create_text(24, y, anchor="nw", fill="#9fb0c1", font=("TkDefaultFont", 9, "bold"), text=f"{label} ({len(tiles)})")
        x = 120
        row_y = y - 4
        if not tiles:
            self.board_canvas.create_text(x, y, anchor="nw", fill="#697887", font=("TkDefaultFont", 9), text="empty")
            return y + 28
        for tile in tiles[:16]:
            self._render_tile(x, row_y, tile)
            x += self.card_width + 8
        if len(tiles) > 16:
            self.board_canvas.create_text(x + 4, y, anchor="nw", fill="#dbe2ea", text=f"+{len(tiles) - 16}")
        return y + self.card_height + 10

    def _render_tile(self, x: int, y: int, tile: dict[str, Any]) -> None:
        self.board_canvas.create_rectangle(
            x,
            y,
            x + self.card_width,
            y + self.card_height,
            fill="#303842",
            outline="#6f7d8d" if tile.get("kind") == "unit" else "#465360",
        )
        image = self._load_image(tile.get("image_path"))
        if image is not None:
            self.board_canvas.create_image(x, y, anchor="nw", image=image)
            return
        text = f"{tile.get('card_no')}\n{tile.get('name') or ''}"
        if tile.get("kind") == "unit":
            text += f"\nU {tile.get('unit_id')} LV{tile.get('level')}"
        self.board_canvas.create_text(
            x + self.card_width // 2,
            y + self.card_height // 2,
            anchor="center",
            fill="#f2f5f8",
            width=self.card_width - 8,
            font=("TkDefaultFont", 8),
            text=text,
        )

    def _render_log(self, frame: dict[str, Any]) -> None:
        self.log.configure(state=self.tk.NORMAL)
        self.log.delete("1.0", self.tk.END)
        current_index = int(frame.get("event_index", -1))
        for index, line in enumerate(self.model.get("event_lines") or []):
            prefix = "> " if index == current_index else "  "
            self.log.insert(self.tk.END, prefix + line + "\n")
        self.log.configure(state=self.tk.DISABLED)
        if current_index >= 0:
            self.log.see(f"{current_index + 1}.0")

    def _load_image(self, image_path: str | None) -> Any | None:
        if not image_path:
            return None
        cache_key = (image_path, self.card_width)
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        try:
            from PIL import Image, ImageTk
        except ModuleNotFoundError:
            return None
        try:
            image = Image.open(image_path)
            image = image.resize((self.card_width, self.card_height))
            photo = ImageTk.PhotoImage(image)
            self.image_cache[cache_key] = photo
            return photo
        except OSError:
            return None


def _load_optional_card_catalog(path: str) -> dict[str, CardDefinition]:
    card_path = Path(path)
    if not card_path.exists():
        return {}
    return load_card_catalog(card_path)


def _frame_index_for_event_no(frames: list[dict[str, Any]], event_no: int | None) -> int:
    if event_no is None:
        return 0
    for index, frame in enumerate(frames):
        current_event = frame.get("current_event")
        if isinstance(current_event, dict) and current_event.get("event_no") == event_no:
            return index
    return 0


def _frame_summary(model: dict[str, Any], frame_index: int) -> dict[str, Any]:
    frames = model.get("frames") or []
    frame = frames[frame_index] if frames else {}
    return {
        "seed": model.get("seed"),
        "frame_index": frame_index,
        "frame_count": len(frames),
        "current_event": frame.get("current_event"),
        "players": [
            {"player_id": player.get("player_id"), "status": player.get("status")}
            for player in frame.get("players", [])
        ],
        "match_result": model.get("match_result"),
    }


def main() -> None:
    raise SystemExit(run_replay_gui_cli())


if __name__ == "__main__":
    main()
