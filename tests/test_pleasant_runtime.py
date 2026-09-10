"""Subprocess integration checks: no production HOME, credentials, or network."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_probe(tmp_path, code, **overrides):
    if not (ROOT / 'mnemosyne/core/beam.py').exists():
        pytest.skip('Full fork checkout required')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('MNEMOSYNE_') and k not in {'HERMES_HOME', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY'}}
    env.update(HOME=str(tmp_path), PYTHONPATH=str(ROOT), MNEMOSYNE_NO_EMBEDDINGS='1',
               MNEMOSYNE_HOST_LLM_ENABLED='true', MNEMOSYNE_LLM_ENABLED='true')
    env.update(overrides)
    result = subprocess.run([sys.executable, '-c', code], env=env, cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / '.hermes/mnemosyne').exists()
    assert not (tmp_path / '.mnemosyne').exists()
    return result


def test_real_databases_and_logs_are_contained(tmp_path):
    run_probe(tmp_path, '''
from pathlib import Path
from mnemosyne import paths
from mnemosyne.core.beam import BeamMemory
from mnemosyne.core.banks import BankManager
from mnemosyne.core.cost_log import _get_conn
from mnemosyne.diagnose import _log_path
root = Path.home() / '.hermes/memories/mnemosyne'
beam = BeamMemory(session_id='contained-test')
assert Path(beam.db_path) == root / 'data/mnemosyne.db', beam.db_path
beam.remember('A durable test fact', scope='global')
banks = BankManager()
assert banks.create_bank('work') == root / 'data/banks/work/mnemosyne.db'
cost = _get_conn()
cost.execute('CREATE TABLE IF NOT EXISTS pleasant_probe (id INTEGER)')
cost.commit()
cost.close()
log = _log_path()
log.write_text('test')
assert log.parent == root / 'logs'
assert (root / 'logs/cost_log.db').exists()
assert paths.blob_dir() == root / 'blobs'
assert not (root / 'models').exists()
''')


def test_actual_host_failure_never_loads_local(tmp_path):
    run_probe(tmp_path, '''
from mnemosyne.core import local_llm
from mnemosyne.core.llm_backends import set_host_llm_backend
class Backend:
    name = 'test-host'
    def complete(self, *args, **kwargs):
        return None
set_host_llm_backend(Backend())
def forbidden(*args, **kwargs):
    raise AssertionError('local model filesystem or download was touched')
local_llm._model_path = forbidden
local_llm._download_model = forbidden
assert local_llm.llm_available()
assert local_llm.summarize_memories(['The project uses SQLite.']) is None
assert local_llm._load_llm() is None
''')


def test_actual_host_success_is_preserved(tmp_path):
    run_probe(tmp_path, '''
from mnemosyne.core import local_llm
from mnemosyne.core.llm_backends import set_host_llm_backend
class Backend:
    name = 'test-host'
    def complete(self, *args, **kwargs):
        return 'The project uses SQLite.'
set_host_llm_backend(Backend())
def forbidden(*args, **kwargs):
    raise AssertionError('local model was requested for a successful host call')
local_llm._load_llm = forbidden
assert local_llm.summarize_memories(['The project uses SQLite.']) == 'The project uses SQLite.'
''')


def test_default_bank_honors_custom_database_without_merging_named_banks(tmp_path):
    run_probe(tmp_path, '''
from pathlib import Path
from mnemosyne import paths
from mnemosyne.core.banks import BankManager
from mnemosyne.core.memory import Mnemosyne
bank = BankManager()
assert bank.get_bank_db_path('default') == paths.db_path()
assert bank.create_bank('separate') != paths.db_path()
mem = Mnemosyne()
assert Path(mem.db_path) == paths.db_path()
''', MNEMOSYNE_DB_PATH=str(tmp_path / '.hermes/memories/mnemosyne/data/custom.db'))
