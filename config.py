import os
import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


_cfg = load_config()


def get(key: str, default=None):
    return _cfg.get(key, default)
