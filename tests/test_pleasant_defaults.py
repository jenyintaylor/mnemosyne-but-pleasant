"""Fork storage and no-local-model contracts. Tests never contact model services."""
import ast
import importlib.util
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for key in tuple(os.environ):
        if key.startswith('MNEMOSYNE_') or key == 'HERMES_HOME':
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))
    return tmp_path


@pytest.fixture
def paths(isolated):
    file = ROOT / 'mnemosyne' / 'paths.py'
    assert file.exists(), 'A canonical storage resolver is required'
    spec = importlib.util.spec_from_file_location('pleasant_test_paths', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('method,suffix', [
    ('home', ''), ('data_dir', 'data'), ('db_path', 'data/mnemosyne.db'),
    ('log_dir', 'logs'), ('backup_dir', 'backups'), ('blob_dir', 'blobs'),
    ('model_cache_dir', 'models'), ('fastembed_cache_dir', 'cache/fastembed'),
    ('shared_db_path', 'data/shared/mnemosyne.db'), ('persona_file', 'persona.md'),
    ('config_path', 'data/config.yaml'),
])
def test_default_tree(paths, isolated, method, suffix):
    root = isolated / '.hermes/memories/mnemosyne'
    assert getattr(paths, method)() == root / suffix
    assert not root.exists(), 'Resolving a path must not create it'


def test_root_override_and_profile_hint(paths, isolated, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(isolated / 'profile-a'))
    assert paths.home() == isolated / 'profile-a/memories/mnemosyne'
    assert paths.home(isolated / 'profile-b') == isolated / 'profile-b/memories/mnemosyne'
    monkeypatch.setenv('MNEMOSYNE_HOME', str(isolated / 'chosen'))
    assert paths.home(isolated / 'profile-b') == isolated / 'chosen'
    assert paths.log_dir() == isolated / 'chosen/logs'


@pytest.mark.parametrize('method,key', [
    ('data_dir', 'MNEMOSYNE_DATA_DIR'), ('db_path', 'MNEMOSYNE_DB_PATH'),
    ('log_dir', 'MNEMOSYNE_LOG_DIR'), ('backup_dir', 'MNEMOSYNE_BACKUP_DIR'),
    ('blob_dir', 'MNEMOSYNE_BLOB_DIR'), ('model_cache_dir', 'MNEMOSYNE_MODEL_CACHE_DIR'),
    ('fastembed_cache_dir', 'MNEMOSYNE_FASTEMBED_CACHE_DIR'),
    ('shared_db_path', 'MNEMOSYNE_SHARED_DB_PATH'), ('persona_file', 'MNEMOSYNE_PERSONA_FILE'),
    ('config_path', 'MNEMOSYNE_CONFIG_PATH'),
])
def test_explicit_overrides(paths, isolated, monkeypatch, method, key):
    monkeypatch.setenv(key, str(isolated / 'explicit'))
    assert getattr(paths, method)() == isolated / 'explicit'


def test_blank_values_and_expansion(paths, isolated, monkeypatch):
    monkeypatch.setenv('MNEMOSYNE_HOME', '  ')
    assert paths.home() == isolated / '.hermes/memories/mnemosyne'
    monkeypatch.setenv('MNEMOSYNE_HOME', '${HOME}/chosen')
    assert paths.home() == isolated / 'chosen'
    monkeypatch.setenv('MNEMOSYNE_HOME', '~/other')
    assert paths.home() == isolated / 'other'


def test_relative_override_rejected(paths, monkeypatch):
    monkeypatch.setenv('MNEMOSYNE_LOG_DIR', 'relative/logs')
    with pytest.raises(ValueError, match='absolute'):
        paths.log_dir()


def test_data_override_moves_config_and_shared_not_logs(paths, isolated, monkeypatch):
    monkeypatch.setenv('MNEMOSYNE_DATA_DIR', str(isolated / 'database'))
    assert paths.config_path() == isolated / 'database/config.yaml'
    assert paths.shared_db_path() == isolated / 'database/shared/mnemosyne.db'
    assert paths.log_dir() == isolated / '.hermes/memories/mnemosyne/logs'


def test_yaml_path_precedence_and_blank_fallback(paths, isolated, monkeypatch):
    config = paths.config_path()
    config.parent.mkdir(parents=True)
    config.write_text(f'log_dir: {isolated}/yaml-logs\nblob_dir: ""\n')
    monkeypatch.setenv('MNEMOSYNE_LOG_DIR', str(isolated / 'env-logs'))
    monkeypatch.setenv('MNEMOSYNE_BLOB_DIR', str(isolated / 'env-blobs'))
    assert paths.log_dir() == isolated / 'yaml-logs'
    assert paths.blob_dir() == isolated / 'env-blobs'


def test_yaml_data_does_not_move_config_bootstrap(paths, isolated):
    config = paths.config_path()
    config.parent.mkdir(parents=True)
    config.write_text(f'data_dir: {isolated}/yaml-data\n')
    assert paths.data_dir() == isolated / 'yaml-data'
    assert paths.db_path() == isolated / 'yaml-data/mnemosyne.db'
    assert paths.config_path() == config


def test_bad_yaml_fails_instead_of_selecting_another_store(paths):
    config = paths.config_path()
    config.parent.mkdir(parents=True)
    config.write_text('log_dir: [broken')
    with pytest.raises(ValueError, match='config'):
        paths.log_dir()


def test_old_tree_not_migrated_or_touched(paths, isolated):
    old = isolated / '.hermes/mnemosyne/data'
    old.mkdir(parents=True)
    sentinel = old / 'mnemosyne.db'
    sentinel.write_bytes(b'preserve existing data')
    assert paths.db_path() != sentinel
    assert sentinel.read_bytes() == b'preserve existing data'
    assert not paths.home().exists()


def _source(path):
    file = ROOT / path
    if not file.exists():
        pytest.skip('Full fork checkout required for runtime integration checks')
    return file.read_text()


def test_default_resolvers_use_canonical_paths():
    required = {
        'mnemosyne/diagnose.py': '_default_log_dir',
        'mnemosyne/core/config.py': '_default_config_path',
        'mnemosyne/core/content_sanitizer.py': '_blob_root',
        'mnemosyne/core/beam.py': '_default_db_path',
        'mnemosyne/core/memory.py': '_default_db_path',
        'mnemosyne/mcp_tools.py': '_shared_db_path',
        'mnemosyne/dr/recovery.py': 'get_default_paths',
    }
    for file, name in required.items():
        tree = ast.parse(_source(file))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        assert '_paths.' in ast.unparse(fn), file


@pytest.mark.parametrize('file', [
    'hermes_memory_provider/__init__.py',
    'integrations/hermes/src/mnemosyne_hermes/__init__.py',
])
def test_provider_uses_configured_db_without_profile_workaround(file):
    source = _source(file)
    assert '_pleasant_paths().db_path(self._hermes_home)' in source
    assert '_pleasant_paths().shared_db_path(self._hermes_home)' in source


def test_local_loader_disabled_before_cached_model_or_download(monkeypatch):
    source = _source('mnemosyne/core/local_llm.py')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_load_llm')
    for cached in (None, object()):
        model_path = Mock(side_effect=AssertionError('local filesystem access'))
        download = Mock(side_effect=AssertionError('unexpected download'))
        ns = dict(LLM_ENABLED=True, _llm_instance=cached, _llm_available=None,
                  _llm_backend=None, _local_llm_enabled=lambda: False,
                  _model_path=model_path, _download_model=download)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<loader>', 'exec'), ns)
        assert ns['_load_llm']() is None
        assert ns['_llm_available'] is False
        model_path.assert_not_called()
        download.assert_not_called()


def test_local_opt_in_keeps_loader_available():
    source = _source('mnemosyne/core/local_llm.py')
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_load_llm')
    model = object()
    ns = dict(LLM_ENABLED=True, _llm_instance=model, _llm_available=None,
              _llm_backend=None, _local_llm_enabled=lambda: True)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<loader>', 'exec'), ns)
    assert ns['_load_llm']() is model


def test_host_availability_does_not_load_local():
    source = _source('mnemosyne/core/local_llm.py')
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'llm_available')
    load = Mock(side_effect=AssertionError('local loader called for host'))
    ns = dict(_host_backend_will_handle_call=lambda: True, _load_llm=load,
              _llm_available=False, LLM_ENABLED=True, LLM_BASE_URL='')
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<available>', 'exec'), ns)
    assert ns['llm_available']() is True
    load.assert_not_called()
