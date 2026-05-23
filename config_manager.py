import json
import os
import threading


class ConfigManager:

    def __init__(self, config_dir: str = "./config"):
        self.config_dir = config_dir
        self._persona = self._load_json("persona.json")
        self._teaching_style = self._load_json("teaching_style.json")
        self._locks: dict[str, threading.Lock] = {}

    def _load_json(self, filename: str) -> dict:
        filepath = os.path.join(self.config_dir, filename)
        with open(filepath, "r", encoding = "utf-8", ) as f:
            return json.load(f)

    @property
    def persona(self) -> dict:
        return self._persona

    @property
    def teaching_style(self) -> dict:
        return self._teaching_style

    def get_user_memory(self, user_id: str) -> dict | None:
        filepath = os.path.join(self.config_dir, f"{user_id}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding = "utf-8") as f:
            return json.load(f)

    def update_user_memory(self, user_id: str, updates: dict) -> None:
        lock = self._locks.setdefault(user_id, threading.Lock())
        with lock:
            existing = self.get_user_memory(user_id) or {}
            existing.update(updates)
            filepath = os.path.join(self.config_dir, f"{user_id}.json")
            tmp = filepath + ".tmp"
            with open(tmp, "w", encoding = "utf-8") as f:
                json.dump(existing, f, ensure_ascii = False, indent = 4)
            os.replace(tmp, filepath)

    def build_system_prompt(self, user_memory: dict = None) -> str:
        persona = self._persona
        teaching_style = self._teaching_style

        prompt_parts = [f"你的基础人设是：{persona}",
                        f"你采用的教学方式是：{teaching_style}"]

        if user_memory:
            prompt_parts.append(f"\n保存的用户信息：{json.dumps(user_memory, ensure_ascii = False)}")
        else:
            prompt_parts.append("\n当前用户：新用户，暂无记录。")

        return "\n".join(prompt_parts)
