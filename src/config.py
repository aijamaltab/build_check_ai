"""Загрузка конфигов из config/*.yaml. Пороги, маркеры и шаблоны живут там, а не в коде."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str, config_dir=CONFIG_DIR) -> dict:
    return yaml.safe_load((Path(config_dir) / name).read_text(encoding="utf-8"))


def load_config(config_dir=CONFIG_DIR) -> dict:
    """Все конфиги одним словарём: templates, units, rules, synonyms."""
    return {
        "templates": load_yaml("templates.yaml", config_dir)["templates"],
        "units": load_yaml("units.yaml", config_dir),
        "rules": load_yaml("rules.yaml", config_dir),
        "synonyms": load_yaml("synonyms.yaml", config_dir),
    }
