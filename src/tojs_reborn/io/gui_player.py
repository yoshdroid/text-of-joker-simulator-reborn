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
        self.image_refs: list[Any] = []
        self.frame = tk.Frame(self.root, bg="#20242a")
        self.frame.pack(fill=tk.BOTH, expand=True)
        self.status = tk.Label(self.frame, text="waiting for state...", bg="#20242a", fg="#f3f5f7", anchor="w")
        self.status.pack(fill=tk.X, padx=10, pady=8)
        self.body = tk.Frame(self.frame, bg="#20242a")
        self.body.pack(fill=tk.BOTH, expand=True)

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
        for child in self.body.winfo_children():
            child.destroy()
        self.image_refs.clear()
        self.status.configure(
            text=(
                f"player={model.get('player_id')} round={model.get('round_no')} "
                f"turn={model.get('turn_no')} turn_player={model.get('turn_player_id')}"
                f"{self._event_status(model.get('event'))}"
            )
        )
        self._section("Opponent Battlefield", model.get("opponent", {}).get("battlefield", []))
        self._section("Own Battlefield", model.get("own", {}).get("battlefield", []))
        self._section("Own Trigger Zone", model.get("own", {}).get("trigger_zone", []))
        self._section("Own Hand", model.get("own", {}).get("hand", []))

    def _section(self, title: str, tiles: list[dict[str, Any]]) -> None:
        label = self.tk.Label(self.body, text=title, bg="#20242a", fg="#f3f5f7", anchor="w")
        label.pack(fill=self.tk.X, padx=10, pady=(8, 2))
        row = self.tk.Frame(self.body, bg="#20242a")
        row.pack(fill=self.tk.X, padx=10)
        if not tiles:
            empty = self.tk.Label(row, text="(empty)", bg="#20242a", fg="#9aa3ad")
            empty.pack(side=self.tk.LEFT, padx=4, pady=4)
            return
        for tile in tiles:
            self._tile(row, tile)

    def _tile(self, parent: Any, tile: dict[str, Any]) -> None:
        box = self.tk.Frame(parent, width=self.card_width, height=int(self.card_width * 1.45), bg="#343b44", bd=1, relief=self.tk.SOLID)
        box.pack(side=self.tk.LEFT, padx=4, pady=4)
        box.pack_propagate(False)
        image = self._load_image(tile.get("image_path"))
        if image is not None:
            image_label = self.tk.Label(box, image=image, bg="#343b44")
            image_label.pack(fill=self.tk.BOTH, expand=True)
            self.image_refs.append(image)
        else:
            text = f"{tile.get('card_no')}\n{tile.get('name') or ''}"
            if tile.get("kind") == "unit":
                text += f"\nLv{tile.get('level')} BP{tile.get('current_bp')}"
                if tile.get("exhausted"):
                    text += "\nEXHAUSTED"
            self.tk.Label(box, text=text, bg="#343b44", fg="#f3f5f7", wraplength=self.card_width - 8).pack(fill=self.tk.BOTH, expand=True)

    def _load_image(self, image_path: str | None) -> Any | None:
        if not image_path:
            return None

    @staticmethod
    def _event_status(event: Any) -> str:
        if not isinstance(event, dict):
            return ""
        return f" | event#{event.get('event_no')} {event.get('type')}"
        try:
            from PIL import Image, ImageTk
        except ModuleNotFoundError:
            return None
        try:
            image = Image.open(image_path)
            height = max(1, int(self.card_width * image.height / image.width))
            image = image.resize((self.card_width, height))
            return ImageTk.PhotoImage(image)
        except OSError:
            return None


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
