#!/usr/bin/env python3
"""One-time, checked source edits for this fork; never imported at runtime.

Leaves unrelated code byte-for-byte intact. Parses and compiles every proposed
file before writing any of them. Re-running is a no-op for already edited code.
Does not inspect or migrate users' databases, .env files, or configuration.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    'hermes_memory_provider/__init__.py',
    'integrations/hermes/src/mnemosyne_hermes/__init__.py',
}
BODIES = {
    ('mnemosyne/diagnose.py', '_default_log_dir'): 'return _paths.log_dir()',
    ('mnemosyne/core/config.py', '_default_config_path'): 'return _paths.config_path()',
    ('mnemosyne/core/content_sanitizer.py', '_blob_root'): 'return _paths.blob_dir()',
    ('mnemosyne/cli.py', '_default_data_dir'): 'return str(_paths.data_dir())',
    ('mnemosyne/mcp_tools.py', '_shared_db_path'): 'return _paths.shared_db_path()',
    ('mnemosyne/dr/recovery.py', 'get_default_paths'):
        'return _paths.data_dir(), _paths.backup_dir(), _paths.db_path()',
}
for part in ('beam', 'memory', 'banks'):
    BODIES[(f'mnemosyne/core/{part}.py', '_default_data_dir')] = 'return _paths.data_dir()'
for part in ('beam', 'memory'):
    BODIES[(f'mnemosyne/core/{part}.py', '_default_db_path')] = 'return _paths.db_path()'
ASSIGNMENTS = {
    ('mnemosyne/core/cost_log.py', 'DEFAULT_LOG_DIR'): '_paths.log_dir()',
    ('mnemosyne/core/cost_log.py', 'DEFAULT_LOG_DB'): '_paths.log_dir() / "cost_log.db"',
    ('mnemosyne/core/embeddings.py', '_FASTEMBED_CACHE_DIR'): 'str(_paths.fastembed_cache_dir())',
    ('mnemosyne/core/local_llm.py', 'MODEL_CACHE_DIR'): '_paths.model_cache_dir()',
    ('mnemosyne/core/persona.py', 'DEFAULT_PERSONA_FILE'): '_paths.persona_file()',
    ('mnemosyne/integrations/hermes_persona_prompt.py', 'DEFAULT_PERSONA_FILE'): '_paths.persona_file()',
}
for part in ('beam', 'memory', 'banks', 'triples'):
    ASSIGNMENTS[(f'mnemosyne/core/{part}.py', 'DEFAULT_DATA_DIR')] = '_paths.data_dir()'
for part in ('beam', 'memory'):
    ASSIGNMENTS[(f'mnemosyne/core/{part}.py', 'DEFAULT_DB_PATH')] = '_paths.db_path()'


def dump(node):
    return ast.dump(node, include_attributes=False)


def text(node):
    return ast.unparse(node)


def literal(node, value):
    return isinstance(node, ast.Constant) and node.value == value


def parts(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return parts(node.left) + [node.right]
    return [node]


def path_expression(node, prefix='_paths', hint=''):
    values = parts(node)
    base, tail = text(values[0]), values[1:]
    if base == 'Path.home()':
        if len(tail) >= 3 and all(literal(tail[i], s) for i, s in enumerate(('.hermes', 'memory', 'persona.md'))):
            return f'{prefix}.persona_file({hint})'
        if len(tail) >= 2 and literal(tail[0], '.hermes') and literal(tail[1], 'mnemosyne'):
            tail = tail[2:]
        elif tail and literal(tail[0], '.mnemosyne'):
            tail = tail[1:]
        else:
            return None
    elif base in {'_DEFAULT_ROOT', 'Path(_HERMES_HOME)', 'Path(self._hermes_home)',
                  'Path(hermes_home)', 'Path(hermes_home).expanduser()'}:
        if not tail or not literal(tail[0], 'mnemosyne'):
            return None
        tail = tail[1:]
        if 'self._hermes_home' in base:
            hint = 'self._hermes_home'
        elif base in {'Path(hermes_home)', 'Path(hermes_home).expanduser()'}:
            hint = 'hermes_home'
    elif base in {'_mnemosyne_root', 'Path(_MNEMOSYNE_HOME)'}:
        # These names also occur in source/import discovery. Only storage
        # suffixes belong to this policy, not the bare root or plugin paths.
        if (not tail or not isinstance(tail[0], ast.Constant)
                or tail[0].value not in {'data', 'logs', 'models', 'blobs', 'backups'}):
            return None
    else:
        return None
    names = {'data': 'data_dir', 'logs': 'log_dir', 'models': 'model_cache_dir',
             'backups': 'backup_dir', 'blobs': 'blob_dir'}
    if len(tail) >= 3 and all(literal(tail[i], s) for i, s in enumerate(('data', 'shared', 'mnemosyne.db'))):
        method, tail = 'shared_db_path', tail[3:]
    elif len(tail) >= 2 and literal(tail[0], 'data') and literal(tail[1], 'mnemosyne.db'):
        method, tail = 'db_path', tail[2:]
    elif tail and isinstance(tail[0], ast.Constant) and tail[0].value in names:
        method, tail = names[tail[0].value], tail[1:]
    else:
        method = 'home'
    return f'{prefix}.{method}({hint})' + ''.join(' / ' + text(item) for item in tail)


def transform(source, filename):
    tree = ast.parse(source)
    raw = source.encode('utf-8')
    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    provider = filename in PROVIDERS
    prefix = '_pleasant_paths()' if provider else '_paths'
    seen = set()

    def edit(node, replacement):
        if dump(node) == dump(ast.parse(replacement, mode='eval').body):
            return
        edits.append((offsets[node.lineno-1]+node.col_offset,
                      offsets[node.end_lineno-1]+node.end_col_offset, replacement.encode()))

    def visit(node, in_function=False):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = (filename, node.name)
            if key in BODIES:
                seen.add(key)
                body = BODIES[key]
                expected = ast.parse(body).body
                if [dump(n) for n in node.body] != [dump(n) for n in expected]:
                    indent = ' ' * node.body[0].col_offset
                    start = offsets[node.body[0].lineno-1]
                    end = offsets[node.body[-1].end_lineno]
                    edits.append((start, end, (''.join(indent+s+'\n' for s in body.splitlines())).encode()))
                return
            in_function = True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            name = targets[0].id if len(targets) == 1 and isinstance(targets[0], ast.Name) else None
            key = (filename, name)
            if key in ASSIGNMENTS:
                edit(node.value, ASSIGNMENTS[key])
                return
            # The root provider relies on BeamMemory's implicit default, while
            # the packaged provider has the explicit db_path ternary below.
            # Handle the known call here instead of a workflow-only pre-edit.
            if (provider and in_function and len(targets) == 1
                    and text(targets[0]) == 'self._beam'
                    and isinstance(node.value, ast.Call)
                    and text(node.value) == 'BeamMemory(session_id=self._session_id)'):
                edit(node.value,
                     f'BeamMemory(session_id=self._session_id, '
                     f'db_path={prefix}.db_path(self._hermes_home))')
                return
            if provider and in_function and name == 'db_path':
                candidate = node.value.body if isinstance(node.value, ast.IfExp) else node.value
                route = path_expression(candidate, prefix)
                if route and '.db_path(' in route:
                    edit(node.value, f'{prefix}.db_path(self._hermes_home)')
                    return
            if provider and in_function and name == 'shared_path' and isinstance(node.value, ast.BoolOp):
                if text(node.value.values[0]) == 'self._shared_surface_path':
                    edit(node.value, f'self._shared_surface_path or {prefix}.shared_db_path(self._hermes_home)')
                    return
        if (not in_function and isinstance(node, ast.If)
                and text(node.test) in {'os.environ.get("MNEMOSYNE_DATA_DIR")', "os.environ.get('MNEMOSYNE_DATA_DIR')"}
                and not node.orelse and all(isinstance(n, ast.Assign) for n in node.body)
                and all(isinstance(t, ast.Name) and t.id in {'DEFAULT_DATA_DIR', 'DEFAULT_DB_PATH', 'BANKS_DIR'}
                        for n in node.body for t in n.targets)):
            edits.append((offsets[node.lineno-1], offsets[node.end_lineno], b''))
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            replacement = path_expression(node, prefix)
            if replacement:
                if provider and not in_function:
                    old = ast.get_source_segment(source, node)
                    replacement = old.replace('".hermes" / "mnemosyne"', '".hermes" / "memories" / "mnemosyne"')
                    replacement = replacement.replace('".hermes" / "memory" / "persona.md"', '".hermes" / "memories" / "mnemosyne" / "persona.md"')
                    if replacement != old:
                        edit(node, replacement)
                else:
                    edit(node, replacement)
                return
        if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
            callee = text(node.func)
            value = node.args[0]
            if callee in {'Path', 'os.path.expanduser'} and isinstance(value, ast.Constant) and isinstance(value.value, str):
                for old in ('~/.hermes/mnemosyne', '~/.mnemosyne'):
                    if value.value == old or value.value.startswith(old+'/'):
                        tail = value.value[len(old):].strip('/')
                        expression = f'{prefix}.home()' + (f' / {tail!r}' if tail else '')
                        if not provider or in_function:
                            edit(node, f'str({expression})' if callee == 'os.path.expanduser' else expression)
                        return
        for child in ast.iter_child_nodes(node):
            visit(child, in_function)

    visit(tree)
    missing = {k for k in BODIES if k[0] == filename} - seen
    if missing:
        raise ValueError(f'Required resolver missing from {filename}: {missing}')
    edits.sort()
    for a, b in zip(edits, edits[1:]):
        if a[1] > b[0]:
            raise ValueError(f'Overlapping edits in {filename}')
    for start, end, new in reversed(edits):
        raw = raw[:start] + new + raw[end:]
    updated = raw.decode('utf-8')
    if edits:
        if provider:
            if 'def _pleasant_paths(' not in updated:
                updated += '\n\ndef _pleasant_paths():\n    """Import core paths only when storage is actually needed."""\n    from mnemosyne import paths\n    return paths\n'
        elif 'from mnemosyne import paths as _paths' not in updated:
            parsed = ast.parse(updated)
            count = 0
            for n in parsed.body:
                if ((isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
                        or (isinstance(n, ast.ImportFrom) and n.module == '__future__')):
                    count = n.end_lineno
                else:
                    break
            split = updated.splitlines(keepends=True)
            split.insert(count, '\nfrom mnemosyne import paths as _paths\n')
            updated = ''.join(split)
    if filename == 'mnemosyne/core/local_llm.py':
        updated = patch_local(updated)
    compile(updated, filename, 'exec')
    return updated


def patch_local(source):
    if 'def _local_llm_enabled(' in source:
        return source
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_load_llm')
    declarations = [n for n in fn.body if isinstance(n, ast.Global)]
    if len(declarations) != 1 or '_llm_instance' not in declarations[0].names:
        raise ValueError('Unrecognized local LLM loader; refusing a partial edit')
    lines = source.splitlines(keepends=True)
    lines.insert(declarations[0].end_lineno,
        '\n    # Local inference is an explicit opt-in, separate from host/remote LLMs.\n'
        '    if not LLM_ENABLED or not _local_llm_enabled():\n'
        '        _llm_available = False\n'
        '        return None\n')
    source = ''.join(lines)
    source += '\n\ndef _local_llm_enabled() -> bool:\n'
    source += '    """Local GGUF inference/downloads are disabled by default in this fork."""\n'
    source += '    from mnemosyne.core.config import get_config\n'
    source += '    return get_config().get_bool("local_llm_enabled", False)\n'
    return source


def patch_schema(source):
    additions = {
        'ENV_VAR_MAP': {'log_dir': 'MNEMOSYNE_LOG_DIR', 'model_cache_dir': 'MNEMOSYNE_MODEL_CACHE_DIR',
                        'persona_file': 'MNEMOSYNE_PERSONA_FILE', 'local_llm_enabled': 'MNEMOSYNE_LOCAL_LLM_ENABLED'},
        'DEFAULTS': {'log_dir': '', 'model_cache_dir': '', 'persona_file': '', 'local_llm_enabled': False},
    }
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    inserts = []
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if len(targets) != 1 or not isinstance(targets[0], ast.Name):
            continue
        name = targets[0].id
        if name in additions:
            if not isinstance(n.value, ast.Dict):
                raise ValueError(f'Unexpected {name} schema')
            existing = {k.value for k in n.value.keys if isinstance(k, ast.Constant)}
            missing = {k: v for k, v in additions[name].items() if k not in existing}
            if missing:
                inserts.append((n.value.lineno, ''.join(f'    {k!r}: {v!r},\n' for k,v in missing.items())))
    for line, data in sorted(inserts, reverse=True):
        lines.insert(line, data)
    return ''.join(lines)


def main():
    if not (ROOT / 'mnemosyne/paths.py').is_file():
        raise SystemExit('Canonical path module is missing')
    plan = []
    roots = ('mnemosyne', 'hermes_memory_provider', 'integrations/hermes/src/mnemosyne_hermes')
    for root in roots:
        for file in sorted((ROOT/root).rglob('*.py')):
            if file == ROOT/'mnemosyne/paths.py':
                continue
            name = file.relative_to(ROOT).as_posix()
            source = file.read_text(encoding='utf-8')
            result = transform(source, name)
            if name == 'mnemosyne/core/config.py':
                result = patch_schema(result)
            compile(result, name, 'exec')
            if result != source:
                plan.append((file, result))
    proposed = {p: s for p, s in plan}
    for name in PROVIDERS:
        file = ROOT/name
        source = proposed.get(file, file.read_text())
        for call in ('_pleasant_paths().db_path(self._hermes_home)',
                     '_pleasant_paths().shared_db_path(self._hermes_home)'):
            if call not in source:
                raise ValueError(f'Provider route not patched: {name}: {call}')
    for file, result in plan:
        file.write_text(result, encoding='utf-8')
        print(file.relative_to(ROOT))
    print(f'{len(plan)} source files updated; no user data was moved.')


if __name__ == '__main__':
    main()
