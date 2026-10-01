"""Opt-in creative constraints; canonical invariants are never disabled here."""
import json
from pathlib import Path


def load_policy(root: Path) -> dict:
    defaults = {"pacing": {"enabled": False, "max_fast_per_volume": 3,
                            "max_consecutive_fast": 1, "slow_density_window": 4},
                "narrative": {"avoid_resolution": False, "quota_abc": False,
                              "cliffhanger": False, "finale_chapters": []}}
    path = root / ".novel_policy.json"
    if not path.exists():
        return defaults
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or set(data) - set(defaults):
        raise ValueError(".novel_policy.json 只接受 pacing / narrative 对象")
    for group, values in data.items():
        if not isinstance(values, dict) or set(values) - set(defaults[group]):
            raise ValueError(f"无效策略字段: {group}")
        defaults[group].update(values)
    for group, keys in (("pacing", ["enabled"]),
                        ("narrative", ["avoid_resolution", "quota_abc", "cliffhanger"])):
        for key in keys:
            if type(defaults[group][key]) is not bool:
                raise ValueError(f"{group}.{key} 必须为布尔值")
    for key in ("max_fast_per_volume", "max_consecutive_fast", "slow_density_window"):
        value = defaults["pacing"][key]
        if type(value) is not int or value < 1:
            raise ValueError(f"pacing.{key} 必须为正整数")
    finals = defaults["narrative"]["finale_chapters"]
    if not isinstance(finals, list) or any(type(n) is not int or n < 1 for n in finals):
        raise ValueError("narrative.finale_chapters 必须为正整数组")
    return defaults
