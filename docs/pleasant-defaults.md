# Pleasant defaults: storage and local LLM policy

This fork keeps Mnemosyne-owned runtime data under one root and requires explicit consent before running or downloading a local GGUF model. It does not move Hermes's own configuration, plugin registration, pending write approvals, or agent logs. Messages emitted through Hermes's logging handlers still follow Hermes's policy.

## Default layout

With `HERMES_HOME` unset, the root is `~/.hermes/memories/mnemosyne`. With a custom Hermes home/profile it is `$HERMES_HOME/memories/mnemosyne`. `MNEMOSYNE_HOME` names the Mnemosyne root itself, not its parent.

```text
~/.hermes/memories/mnemosyne/
  data/
    config.yaml
    mnemosyne.db
    banks/<name>/mnemosyne.db
    shared/mnemosyne.db
  logs/
    diagnose_*.jsonl
    cost_log.db
  backups/
  blobs/
  models/                 # only used by explicitly enabled local GGUF inference
  cache/fastembed/         # only used by local embedding models
  persona.md
  plugins/                # Mnemosyne extensions, not Hermes plugin registration
```

The shared store, bank resolver, CLI, recovery helpers, diagnostics, and both Hermes provider implementations use `mnemosyne.paths`. A regular Hermes provider no longer bypasses the configured data directory. **Profile isolation is not needed as a storage-path workaround.** Keep it enabled when per-profile banks are actually intended; changing it can select a different database.

## Overrides

Nonblank path values in the flat Mnemosyne YAML override nonblank environment values, which override derived defaults. Empty seeded YAML entries do not mask environment overrides. Paths expand `~` and environment variables and must resolve to absolute paths. Bad YAML/path values fail rather than select a different store.

| YAML key | Environment override | Derived default |
|---|---|---|
| `home` | `MNEMOSYNE_HOME` | Hermes home / memories / mnemosyne |
| `data_dir` | `MNEMOSYNE_DATA_DIR` | home / data |
| `db_path` | `MNEMOSYNE_DB_PATH` | data_dir / mnemosyne.db |
| `shared_db_path` | `MNEMOSYNE_SHARED_DB_PATH` | data_dir / shared / mnemosyne.db |
| `log_dir` | `MNEMOSYNE_LOG_DIR` | home / logs |
| `backup_dir` | `MNEMOSYNE_BACKUP_DIR` | home / backups |
| `blob_dir` | `MNEMOSYNE_BLOB_DIR` | home / blobs |
| `model_cache_dir` | `MNEMOSYNE_MODEL_CACHE_DIR` | home / models |
| `fastembed_cache_dir` | `MNEMOSYNE_FASTEMBED_CACHE_DIR` | home / cache / fastembed |
| `persona_file` | `MNEMOSYNE_PERSONA_FILE` | home / persona.md |

`db_path` controls the default/private database, not every named bank. Explicit constructor database/data-directory arguments still take precedence; named banks retain separate files. A `data_dir` override moves databases and the default shared surface, not the independently rooted logs/backups/caches. Set `home` to relocate all derived defaults together.

Config-file discovery is environment-only, avoiding a recursive dependency on the file being located. `MNEMOSYNE_CONFIG_PATH` selects a file explicitly. Otherwise, the file is `MNEMOSYNE_DATA_DIR/config.yaml`, or the environment-derived Mnemosyne home's `data/config.yaml`. Setting `home` or `data_dir` inside YAML does not relocate that same YAML file. No legacy config/database discovery or migration runs automatically. Restart Hermes after changing storage settings.

## Hermes/Codex without local fallback

Keep the existing host routing in Hermes's `.env`:

```dotenv
MNEMOSYNE_LLM_ENABLED=true
MNEMOSYNE_HOST_LLM_ENABLED=true
MNEMOSYNE_HOST_LLM_PROVIDER=openai-codex
MNEMOSYNE_LOCAL_LLM_ENABLED=false
```

`local_llm_enabled` defaults to `false`; the last environment entry merely makes that choice explicit. Its YAML equivalent is `local_llm_enabled: false`. An existing YAML value overrides the environment, so do not leave a conflicting `true` there.

The local loader returns before looking for a cached model, downloading one, or constructing either local inference backend. Successful host/remote calls are unchanged. Host failure degrades to the existing non-LLM memory path instead of silently running a local model. Existing cached GGUF files are left untouched. Setting the global `MNEMOSYNE_LLM_ENABLED=false` still disables host LLM work too; it is not the switch to use for this policy. Local inference can be deliberately re-enabled with `local_llm_enabled: true` and the appropriate optional dependencies. Restart after changing the policy. The new switch does not disable embeddings; custom embedding-server configuration remains independent.

## Installation and migration

Install **both packages from this fork**, in the Python environment Hermes uses. From a checkout of the selected fork branch:

```bash
python -m pip install --upgrade . ./integrations/hermes
```

Do not reinstall only `mnemosyne-hermes` from PyPI afterward: that can leave the provider and core from different codebases. No additional `[llm]` dependency is needed to use the authenticated Hermes host route.

Before starting with changed paths, stop Hermes and any other process using the same SQLite files. Back up existing stores, then deliberately relocate the desired existing Mnemosyne data into the new tree. Preserve the database and its `-wal` / `-shm` sidecars together when copying an existing store; do not merge two active SQLite databases by copying files over one another. Named banks, shared storage, blobs, generated persona data, and any wanted old cost logs may have lived in separate legacy locations and should be reviewed individually.

Explicit old paths are still authoritative. Remove or correct old YAML/.env entries, including accidentally duplicated `/.hermes/.hermes/` segments. The fork never rewrites those settings, deletes old files, or silently chooses an old store. A new empty location will produce a new empty database on first use.

The resolver itself is read-only. Inspect selected paths without opening a model or a memory database:

```bash
python - <<'PY'
from mnemosyne import paths
for name in ('home', 'config_path', 'data_dir', 'db_path', 'shared_db_path', 'log_dir'):
    print(f'{name}: {getattr(paths, name)()}')
PY
```
