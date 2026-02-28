from __future__ import annotations
import json
import os
from typing import Any

class I18N:
    def __init__(self, lang: str = "de", base_dir: str = "content/i18n"):
        self.lang = lang
        self.base_dir = base_dir
        self.data: dict[str, str] = {}

    def load(self) -> None:
        path = os.path.join(self.base_dir, f"{self.lang}.json")
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def set_lang(self, lang: str) -> None:
        self.lang = lang
        self.load()

    def t(self, msg_id: str, **kwargs):
        s = self.data.get(msg_id, msg_id)
        try:
            return s.format(**kwargs)
        except Exception:
            return s