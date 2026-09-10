"""Canonical storage paths for Mnemosyne.

Default root: $HERMES_HOME/memories/mnemosyne (HERMES_HOME defaults to ~/.hermes).
Nonblank YAML path > nonblank environment path > derived default. Empty seeded
YAML entries do not mask environment overrides. Resolution never creates files.

The config location is bootstrapped from the environment only, so reading
``home`` or ``data_dir`` from YAML cannot recursively relocate that YAML file.
Changing storage paths does not move, merge, or delete existing data.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any


def _path(value: Any, name: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError(f'{name} must be an absolute filesystem path')
    text = os.fspath(value)
    if not text.strip():
        return None
    result = Path(os.path.expandvars(text)).expanduser()
    if not result.is_absolute():
        raise ValueError(f'{name} must be an absolute path: {text!r}')
    return result


def _env(name: str) -> Path | None:
    return _path(os.environ.get(name), name)


def _bootstrap_home(hermes_home: str | Path | None = None) -> Path:
    explicit = _env('MNEMOSYNE_HOME')
    if explicit is not None:
        return explicit
    base = _path(hermes_home, 'hermes_home')
    if base is None:
        base = _env('HERMES_HOME') or Path.home() / '.hermes'
    return base / 'memories' / 'mnemosyne'


def config_path(hermes_home: str | Path | None = None) -> Path:
    """Bootstrap without importing/initializing the central config singleton."""
    return _env('MNEMOSYNE_CONFIG_PATH') or (
        (_env('MNEMOSYNE_DATA_DIR') or _bootstrap_home(hermes_home) / 'data') / 'config.yaml'
    )


@lru_cache(maxsize=16)
def _read_yaml(filename: str, mtime_ns: int, size: int) -> dict[str, Any]:
    # Cache identity includes mtime and size; files are read, never seeded.
    import yaml
    try:
        with open(filename, encoding='utf-8') as stream:
            result = yaml.safe_load(stream) or {}
        if not isinstance(result, dict):
            raise ValueError('expected a YAML mapping')
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f'Cannot read Mnemosyne path config {filename}: {exc}') from exc
    return result


def _configured(key: str, hermes_home: str | Path | None = None) -> Path | None:
    location = config_path(hermes_home)
    try:
        info = location.stat()
    except FileNotFoundError:
        values = {}
    else:
        values = _read_yaml(str(location), info.st_mtime_ns, info.st_size)
    selected = _path(values.get(key), f'config.{key}')
    return selected if selected is not None else _env(f'MNEMOSYNE_{key.upper()}')


def home(hermes_home: str | Path | None = None) -> Path:
    return _configured('home', hermes_home) or _bootstrap_home(hermes_home)


def data_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('data_dir', hermes_home) or home(hermes_home) / 'data'


def db_path(hermes_home: str | Path | None = None) -> Path:
    """Default/private database; explicitly named banks retain their own paths."""
    return _configured('db_path', hermes_home) or data_dir(hermes_home) / 'mnemosyne.db'


def log_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('log_dir', hermes_home) or home(hermes_home) / 'logs'


def backup_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('backup_dir', hermes_home) or home(hermes_home) / 'backups'


def blob_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('blob_dir', hermes_home) or home(hermes_home) / 'blobs'


def model_cache_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('model_cache_dir', hermes_home) or home(hermes_home) / 'models'


def fastembed_cache_dir(hermes_home: str | Path | None = None) -> Path:
    return _configured('fastembed_cache_dir', hermes_home) or home(hermes_home) / 'cache' / 'fastembed'


def shared_db_path(hermes_home: str | Path | None = None) -> Path:
    return _configured('shared_db_path', hermes_home) or data_dir(hermes_home) / 'shared' / 'mnemosyne.db'


def persona_file(hermes_home: str | Path | None = None) -> Path:
    return _configured('persona_file', hermes_home) or home(hermes_home) / 'persona.md'
