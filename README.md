# Histloc3 location schema

Note about the location division schema.

- `from`/`to` define authoritative validity windows for each division.
- `was`/`became` describe lineage so parsers can traverse reforms.

## Linting the dataset

Use the lint script before committing changes to verify ids, parent links, lineage symmetry, and timeline ordering.

### Install dependencies

```pwsh
pip install -r requirements.txt
```

### Run the lint

```pwsh
python tools/schema_lint.py
```

Optional flags: `--country` to target another dataset, `--countries-root` if you store the YAML elsewhere.