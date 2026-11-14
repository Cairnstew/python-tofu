# BigLake (Lakehouse API) example

`biglake.googleapis.com` is the **Lakehouse API** — Google Cloud's data-lake
service. This example enables it through Service Usage and declares a Hive
catalog, database and table.

```bash
python-tofu apis  --config examples/gcp_biglake/stack.py --resolve biglake
python-tofu render --config examples/gcp_biglake/stack.py --workdir .tofu/biglake
python-tofu plan   --config examples/gcp_biglake/stack.py --workdir .tofu/biglake
python-tofu apply  --config examples/gcp_biglake/stack.py --workdir .tofu/biglake
```

`apply` enables `biglake.googleapis.com`, `bigquery.googleapis.com` and
`storage.googleapis.com`, then creates:

- a GCS bucket with `metadata/` and `data/` folder-placeholder objects;
- `google_biglake_catalog` (`lake_catalog`, location `US`);
- `google_biglake_database` (`lake_database`, Hive);
- `google_biglake_table` (`lake_table`, managed Hive table over `gs://.../data/`).

## Why `extra_files`?

The typed DSL does not model `google_biglake_*` resources yet, so
`examples/gcp_biglake/stack.py` puts them in `extra_files` as raw HCL. The bucket
and objects are still typed models. The renderer writes `biglake.tf` verbatim
next to `main.tf`.

## Provider-version note

Provider docs track `main`, but this repo pins `~> 7.0` (the Nix build mirrors
the provider nixpkgs ships, currently 7.33.0). The example deliberately omits
version-specific fields inside the table's `storage_descriptor`; run
`tofu validate` against the rendered workdir before applying if you add fields
from the online docs.

## Querying

Creating the catalog/database/table needs only the Lakehouse (+ Storage) API.
To query the table you also need BigQuery, and for external data a BigQuery
connection with access to the bucket. Add `bigqueryconnection.googleapis.com`
and a `google_bigquery_connection` if you go that route.
