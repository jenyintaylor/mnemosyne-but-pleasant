"""Regression tests for materializing both upstream Hermes provider layouts.

Routing excerpts are from upstream f4a3a0386d0c0446859773696aa572d210f24d15.
These tests intentionally avoid importing Mnemosyne or downloading models.
"""
import ast
import importlib.util
from pathlib import Path
import types
import unittest

_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/apply_pleasant_defaults.py'
_SPEC = importlib.util.spec_from_file_location('pleasant_patcher_under_test', _SCRIPT)
patcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(patcher)

ROOT_NAME = 'hermes_memory_provider/__init__.py'
PACKAGED_NAME = 'integrations/hermes/src/mnemosyne_hermes/__init__.py'
ROOT_PROVIDER = '''from pathlib import Path
_mnemosyne_root = Path(__file__).resolve().parent.parent
class Provider:
    def _initialize_locked(self):
        BeamMemory = _get_beam_class()
        self._beam = BeamMemory(session_id=self._session_id)

    def _ensure_surface_beam_locked(self):
        shared_path = self._shared_surface_path or (_mnemosyne_root / "data" / "shared" / "mnemosyne.db")
        return shared_path
'''
PACKAGED_PROVIDER = '''from pathlib import Path
class Provider:
    def _initialize_locked(self):
        db_path = (
            Path(self._hermes_home) / "mnemosyne" / "data" / "mnemosyne.db"
            if self._hermes_home
            else None
        )
        beam_kwargs = {"session_id": self._session_id, "db_path": db_path}
        if self._channel_id:
            beam_kwargs["channel_id"] = self._channel_id
        self._beam = _get_beam_class()(**beam_kwargs)

    def _ensure_surface_beam_locked(self):
        shared_path = self._shared_surface_path or (Path.home() / ".mnemosyne" / "data" / "shared" / "mnemosyne.db")
        return shared_path
'''


class ProviderPatcherTests(unittest.TestCase):
    def test_legacy_implicit_constructor_is_patched_without_workflow_prestep(self):
        result = patcher.transform(ROOT_PROVIDER, ROOT_NAME)
        self.assertIn('db_path=_pleasant_paths().db_path(self._hermes_home)', result)
        self.assertIn('_pleasant_paths().shared_db_path(self._hermes_home)', result)
        self.assertIn('_mnemosyne_root = Path(__file__).resolve().parent.parent', result)

    def test_packaged_ternary_is_patched(self):
        result = patcher.transform(PACKAGED_PROVIDER, PACKAGED_NAME)
        self.assertIn('_pleasant_paths().db_path(self._hermes_home)', result)
        self.assertNotIn('if self._hermes_home', result)
        self.assertIn('_pleasant_paths().shared_db_path(self._hermes_home)', result)
        self.assertIn('beam_kwargs["channel_id"] = self._channel_id', result)

    def test_both_provider_transforms_are_idempotent(self):
        for source, name in ((ROOT_PROVIDER, ROOT_NAME), (PACKAGED_PROVIDER, PACKAGED_NAME)):
            with self.subTest(name=name):
                once = patcher.transform(source, name)
                self.assertEqual(patcher.transform(once, name), once)
                self.assertEqual(once.count('def _pleasant_paths('), 1)

    def test_source_discovery_paths_are_not_storage_paths(self):
        for expression in ('_mnemosyne_root', '_mnemosyne_root / "plugins"',
                           '_mnemosyne_root / "mnemosyne" / "__init__.py"',
                           'Path(_MNEMOSYNE_HOME)'):
            with self.subTest(expression=expression):
                self.assertIsNone(patcher.path_expression(ast.parse(expression, mode='eval').body))

    def test_shared_storage_suffix_is_recognized(self):
        expression = ast.parse('_mnemosyne_root / "data" / "shared" / "mnemosyne.db"', mode='eval').body
        self.assertEqual(patcher.path_expression(expression), '_paths.shared_db_path()')

    def test_explicit_constructor_override_is_untouched(self):
        source = ROOT_PROVIDER.replace('BeamMemory(session_id=self._session_id)',
                                       'BeamMemory(session_id=self._session_id, db_path=custom_db)')
        result = patcher.transform(source, ROOT_NAME)
        self.assertIn('db_path=custom_db', result)

    def test_named_bank_construction_is_untouched(self):
        source = ROOT_PROVIDER.replace('BeamMemory(session_id=self._session_id)',
                                       'Mnemosyne(session_id=self._session_id, bank=bank_name)')
        result = patcher.transform(source, ROOT_NAME)
        self.assertIn('Mnemosyne(session_id=self._session_id, bank=bank_name)', result)

    def test_native_materialized_root_provider_is_unchanged(self):
        source = ROOT_PROVIDER.replace('BeamMemory(session_id=self._session_id)',
                                       'BeamMemory(session_id=self._session_id, db_path=_pleasant_paths().db_path(self._hermes_home))')
        source = source.replace('(_mnemosyne_root / "data" / "shared" / "mnemosyne.db")',
                                '_pleasant_paths().shared_db_path(self._hermes_home)')
        source += '\n\ndef _pleasant_paths():\n    from mnemosyne import paths\n    return paths\n'
        self.assertEqual(patcher.transform(source, ROOT_NAME), source)

    def test_transformed_calls_preserve_profile_and_explicit_shared_override(self):
        for source, name in ((ROOT_PROVIDER, ROOT_NAME), (PACKAGED_PROVIDER, PACKAGED_NAME)):
            with self.subTest(name=name):
                result = patcher.transform(source, name)
                ns = {'__file__': '/checkout/' + name}
                exec(compile(result, name, 'exec'), ns)
                calls = []
                def db_path(home):
                    calls.append(home)
                    return Path(home) / 'memories/mnemosyne/data/mnemosyne.db'
                ns['_pleasant_paths'] = lambda: types.SimpleNamespace(
                    db_path=db_path,
                    shared_db_path=lambda home: Path(home) / 'memories/mnemosyne/data/shared/mnemosyne.db',
                )
                ns['_get_beam_class'] = lambda: lambda **kwargs: types.SimpleNamespace(**kwargs)
                provider = ns['Provider']()
                provider._session_id = 'session'
                provider._hermes_home = '/profile'
                provider._channel_id = 'channel'
                provider._shared_surface_path = Path('/explicit/shared.db')
                provider._initialize_locked()
                self.assertEqual(calls, ['/profile'])
                self.assertEqual(provider._beam.db_path, Path('/profile/memories/mnemosyne/data/mnemosyne.db'))
                self.assertEqual(provider._beam.session_id, 'session')
                self.assertEqual(provider._ensure_surface_beam_locked(), Path('/explicit/shared.db'))


if __name__ == '__main__':
    unittest.main()
