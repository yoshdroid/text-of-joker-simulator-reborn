from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path
from typing import Any

from .gui_view_model import build_gui_view_model
from .protocol import action_selected_message, choice_selected_message, decode_message, encode_message, mulligan_selected_message
from .sample_player import choose_action


def choose_choice(legal_choices: list[dict[str, Any]]) -> dict[str, Any]:
    return legal_choices[0]


def make_response(message: dict[str, Any], *, mode: str) -> dict[str, Any] | None:
    message_type = message.get("type")
    player_id = str(message.get("player_id") or "")
    request_id = str(message.get("request_id") or "")
    if message_type == "request_mulligan":
        return mulligan_selected_message(request_id=request_id, player_id=player_id, do_mulligan=False)
    if message_type == "request_action":
        legal_actions = message.get("legal_actions", [])
        if not isinstance(legal_actions, list) or not legal_actions:
            return None
        return action_selected_message(choose_action(legal_actions, mode), request_id=request_id, player_id=player_id)
    if message_type == "choice_request":
        legal_choices = message.get("legal_choices", [])
        if not isinstance(legal_choices, list) or not legal_choices:
            return None
        return choice_selected_message(choose_choice(legal_choices), request_id=request_id, player_id=player_id)
    return None


def build_model_from_message(message: dict[str, Any], images_dir: str | Path | None) -> dict[str, Any] | None:
    public_state = message.get("public_state") or message.get("state")
    private_view = message.get("private_view")
    if not isinstance(public_state, dict) or not isinstance(private_view, dict):
        return None
    return build_gui_view_model(public_state, private_view, images_dir=images_dir)


def tile_display_size(tile: dict[str, Any], card_width: int, card_height: int) -> tuple[int, int]:
    if tile.get("kind") == "unit" and tile.get("exhausted"):
        return card_height, card_width
    return card_width, card_height


def run_protocol_loop(*, mode: str, images_dir: str | Path | None, model_queue: queue.Queue[dict[str, Any]] | None) -> None:
    for line in sys.stdin:
        try:
            message = decode_message(line)
        except (ValueError, TypeError):
            continue
        model = build_model_from_message(message, images_dir)
        if model is not None and model_queue is not None:
            if isinstance(message.get("event"), dict):
                model["event"] = message["event"]
            model_queue.put(model)
        if message.get("type") == "game_over":
            break
        response = make_response(message, mode=mode)
        if response is not None:
            sys.stdout.write(encode_message(response))
            sys.stdout.flush()


class TkGui:
    def __init__(self, *, title: str, card_width: int) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("1120x760")
        self.card_width = card_width
        self.card_height = int(self.card_width * 1.45)
        self.image_cache: dict[tuple[str, int], Any] = {}
        self.frame = tk.Frame(self.root, bg="#20242a")
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(self.frame, text="waiting for state...", bg="#20242a", fg="#f3f5f7", anchor="w")
        self.status.pack(fill=tk.X, padx=10, pady=8)
        self.canvas = tk.Canvas(self.frame, bg="#20242a", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.root.bind_all("<Escape>", lambda _event: self.root.destroy())

    def run(self, model_queue: queue.Queue[dict[str, Any]]) -> None:
        self.root.after(100, lambda: self._poll(model_queue))
        self.root.mainloop()

    def _poll(self, model_queue: queue.Queue[dict[str, Any]]) -> None:
        latest = None
        while True:
            try:
                latest = model_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self.render(latest)
        self.root.after(100, lambda: self._poll(model_queue))

    def render(self, model: dict[str, Any]) -> None:
        self.canvas.delete("all")
        self.status.configure(
            text=(
                f"player={model.get('player_id')} round={model.get('round_no')} "
                f"turn={model.get('turn_no')} turn_player={model.get('turn_player_id')}"
                f"{self._event_status(model.get('event'))}"
            )
        )
        y = 12
        y = self._section(y, "Opponent Battlefield", model.get("opponent", {}).get("battlefield", []))
        y = self._section(y, "Own Battlefield", model.get("own", {}).get("battlefield", []))
        y = self._section(y, "Own Trigger Zone", model.get("own", {}).get("trigger_zone", []))
        self._section(y, "Own Hand", model.get("own", {}).get("hand", []))

    def _section(self, y: int, title: str, tiles: list[dict[str, Any]]) -> int:
        self.canvas.create_text(10, y, anchor="nw", fill="#f3f5f7", font=("TkDefaultFont", 10, "bold"), text=title)
        row_y = y + 22
        if not tiles:
            self.canvas.create_text(14, row_y + 8, anchor="nw", fill="#9aa3ad", text="(empty)")
            return row_y + 34
        x = 10
        row_height = 0
        for tile in tiles:
            self._tile(x, row_y, tile)
            tile_width, tile_height = tile_display_size(tile, self.card_width, self.card_height)
            x += tile_width + 10
            row_height = max(row_height, tile_height)
        return row_y + row_height + 18

    def _tile(self, x: int, y: int, tile: dict[str, Any]) -> None:
        tile_width, tile_height = tile_display_size(tile, self.card_width, self.card_height)
        tapped = tile.get("kind") == "unit" and bool(tile.get("exhausted"))
        outline = "#e1e7ee" if tile.get("kind") == "unit" and not tile.get("exhausted") else "#5f6975"
        self.canvas.create_rectangle(x, y, x + tile_width, y + tile_height, fill="#343b44", outline=outline)
        image = self._load_image(tile.get("image_path"), tapped=tapped)
        if image is not None:
            self.canvas.create_image(x, y, anchor="nw", image=image)
        else:
            text = f"{tile.get('card_no')}\n{tile.get('name') or ''}"
            if tile.get("kind") == "unit":
                text += f"\nLv{tile.get('level')} BP{tile.get('current_bp')}"
                if tile.get("exhausted"):
                    text += "\nEXHAUSTED"
            self.canvas.create_text(
                x + tile_width // 2,
                y + tile_height // 2,
                anchor="center",
                fill="#f3f5f7",
                width=tile_width - 8,
                text=text,
            )
        if tile.get("kind") == "unit":
            label = f"Lv{tile.get('level')} BP{tile.get('current_bp')}"
            if tile.get("exhausted"):
                label += " EX"
            self.canvas.create_rectangle(x + 2, y + tile_height - 22, x + tile_width - 2, y + tile_height - 2, fill="#111820", outline="")
            self.canvas.create_text(x + 6, y + tile_height - 19, anchor="nw", fill="#f3f5f7", font=("TkDefaultFont", 8), text=label)

    def _load_image(self, image_path: str | None, *, tapped: bool = False) -> Any | None:
        if not image_path:
            return None
        cache_key = (image_path, self.card_width, tapped)
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        try:
            from PIL import Image, ImageTk
        except ModuleNotFoundError:
            return None
        try:
            image = Image.open(image_path)
            image = image.resize((self.card_width, self.card_height))
            if tapped:
                image = image.rotate(90, expand=True)
            photo = ImageTk.PhotoImage(image)
            self.image_cache[cache_key] = photo
            return photo
        except OSError:
            return None

    @staticmethod
    def _event_status(event: Any) -> str:
        if not isinstance(event, dict):
            return ""
        return f" | event#{event.get('event_no')} {event.get('type')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="GUI JSON Lines sample player.")
    parser.add_argument("--images", default="carddata/images", help="Directory containing {card_no}.jpg/png card images.")
    parser.add_argument("--mode", choices=["first", "pass"], default="first")
    parser.add_argument("--no-window", action="store_true", help="Run protocol responses without opening a GUI window.")
    parser.add_argument("--card-width", type=int, default=96)
    args = parser.parse_args()

    if args.no_window:
        run_protocol_loop(mode=args.mode, images_dir=args.images, model_queue=None)
        return

    model_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    protocol_thread = threading.Thread(
        target=run_protocol_loop,
        kwargs={"mode": args.mode, "images_dir": args.images, "model_queue": model_queue},
        daemon=True,
    )
    protocol_thread.start()
    try:
        TkGui(title="TOJ Reborn GUI Player", card_width=args.card_width).run(model_queue)
    except Exception as exc:  # pragma: no cover - GUI startup depends on local desktop availability.
        print(f"gui_player window disabled: {exc}", file=sys.stderr)
        protocol_thread.join()


if __name__ == "__main__":
    main()
