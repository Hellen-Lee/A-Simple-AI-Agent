"""Conversation memory with auto-trimming and persistence."""

import json
import os
from datetime import datetime
from typing import Optional


class Memory:
    """Manages conversation history with token-aware trimming and file persistence."""

    def __init__(self, max_messages: int = 100):
        self.messages: list[dict] = []
        self.max_messages = max_messages

    def add(self, role: str, content: Optional[str] = None, **kwargs) -> None:
        msg = {"role": role}
        if content is not None:
            msg["content"] = content
        msg.update(kwargs)
        self.messages.append(msg)
        self._trim()

    def get_messages(self) -> list[dict]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages = [m for m in self.messages if m["role"] == "system"]

    def _trim(self) -> None:
        if len(self.messages) <= self.max_messages:
            return
        system = [m for m in self.messages if m["role"] == "system"]
        others = [m for m in self.messages if m["role"] != "system"]
        keep_count = self.max_messages - len(system)
        self.messages = system + others[-keep_count:]

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"messages": self.messages, "saved_at": datetime.now().isoformat()},
                f,
                ensure_ascii=False,
                indent=2,
            )

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.messages = data.get("messages", [])
        return True
