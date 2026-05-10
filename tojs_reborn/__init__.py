from __future__ import annotations

from pathlib import Path


_SRC_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "src" / "tojs_reborn"
if _SRC_PACKAGE_PATH.exists():
    __path__.append(str(_SRC_PACKAGE_PATH))

