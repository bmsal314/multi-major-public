# Importing the original owner's decisions

Nothing is automatically adopted by the first account. No migration has been run.

1. Back up the ignored local SQLite database and original PDFs privately. Keep them out of source control and deployment directories.
2. Create and confirm your hosted account. Upload your own current reports and review the generated map.
3. Obtain your verified account UUID and target map UUID. The utility refuses to proceed if the signed-in account differs from `--expected-user`.
4. Run the utility first without `--apply`. Password entry is hidden and credentials remain only in process memory.

```sh
backend/.venv/bin/python -m scripts.migrate_local_decisions \
  --database backend/degreemap.db --scenario-id LOCAL_ID \
  --origin https://YOUR-TRUSTED-APP-DOMAIN \
  --expected-user YOUR_ACCOUNT_UUID --plan-id YOUR_PLAN_UUID
```

`--apply` creates a separate map and copies unambiguous compatible moves, term settings and custom courses. It never overwrites the local database or an existing hosted map. `--personal-defaults` explicitly enables the original owner's Finance sequencing/equivalence, dance, pre-med and 13-credit minimum, using the selected scenario's date window. Review workload and MCAT settings after import.

The utility opens SQLite with `mode=ro`, reads only decision tables, and never queries account, session or audit-filename tables. Old opaque placeholder IDs are not guessed: unmatched choices/removals are counted and must be recreated after reviewing the new audit. Any error leaves the original data untouched; a partially created hosted alternative can be deleted normally.
