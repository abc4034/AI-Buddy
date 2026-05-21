import json
import os.path
from dataclasses import dataclass, field


class ConfigManager:

    def __init__(self, config_dir: str = "./config"):
        self.config_dir = config_dir
        self._persona = self._load_json("persona.json")
        self._teaching_style = self._load_json("teaching_style.json")
        # self._users_dir = os.path.join(config_dir)

    def _load_json(self, filename: str) -> dict:
        """加载json数据"""
        filepath = os.path.join(self.config_dir, filename)
        with open(filepath, "r", encoding = "utf-8", ) as f:
            return json.load(f)

    @property
    def persona(self) -> dict:
        """AI人设"""
        return self._persona

    @property
    def teaching_style(self) -> dict:
        """教学风格"""
        return self._teaching_style

    def get_user_memory(self, user_id: str) -> dict | None:
        """获取用户信息"""
        filepath = os.path.join(self.config_dir, f"{user_id}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding = "utf-8") as f:
            return json.load(f)

    def update_user_memory(self, user_id: str, updates: dict) -> None:
        """增量更新用户信息"""
        existing = self.get_user_memory(user_id) or {}
        existing.update(updates)
        filepath = os.path.join(self.config_dir, f"{user_id}.json")
        with open(filepath, "w", encoding = "utf-8") as f:
            json.dump(existing, f, ensure_ascii = False, indent = 4)

    def build_system_prompt(self, user_memory: dict = None) -> str:
        """组合system_prompt"""
        persona = self._persona
        teaching_style = self._teaching_style

        # 基础人设
        prompt_parts = [f"你的基础人设是：{persona}",
                        f"你采用的教学方式是：{teaching_style}"]
        # prompt_parts = [
        #     f"你是{persona['name']},一个{persona['role']}。",
        #     f"你的风格是：{persona['vibe']}。"
        # ]

        # 用户信息
        if user_memory:
            prompt_parts.append(f"\n保存的用户信息：{json.dumps(user_memory, ensure_ascii = False)}")
        else:
            prompt_parts.append("\n当前用户：新用户，暂无记录。")

        return "\n".join(prompt_parts)
