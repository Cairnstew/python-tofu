"""Enable BigLake (the "Lakehouse API") and declare a Hive catalog, database and table.

BigLake resources are not part of the typed DSL yet, so they live in
``extra_files`` as raw HCL. The bucket and its metadata/data folder placeholders
are still declared with the typed models.

    python-tofu render --config examples/gcp_biglake/stack.py --workdir .tofu/biglake
    python-tofu plan   --config examples/gcp_biglake/stack.py --workdir .tofu/biglake
    python-tofu apply  --config examples/gcp_biglake/stack.py --workdir .tofu/biglake

`biglake.googleapis.com` (Lakehouse API) is enabled through Service Usage;
`bigquery.googleapis.com` is needed to query the tables.
"""

import os

from python_tofu import (
    BucketObject,
    GcpProvider,
    GcpStack,
    StorageBucket,
)
from python_tofu.providers.gcp.services import ServiceCatalog

PROJECT = os.environ.get("GOOGLE_PROJECT", "example-biglake")
LOCATION = "US"
BUCKET = f"{PROJECT}-biglake"
CATALOG = "lake_catalog"
DATABASE = "lake_database"
TABLE = "lake_table"

BIGLAKE_TF = (
    """\
resource "google_biglake_catalog" "default" {
  name     = "__CATALOG__"
  location = "__LOCATION__"

  # The raw HCL does not reference the typed google_project_service block, so
  # make the API ordering explicit; otherwise the catalog can race enablement.
  depends_on = [google_project_service.api_biglake_googleapis_com]
}

resource "google_biglake_database" "default" {
  name    = "__DATABASE__"
  catalog = google_biglake_catalog.default.id
  type    = "HIVE"

  hive_options {
    location_uri = "gs://__BUCKET__/metadata/"
    parameters = {
      owner = "data-team"
    }
  }
}

resource "google_biglake_table" "default" {
  name     = "__TABLE__"
  database = google_biglake_database.default.id
  type     = "HIVE"

  hive_options {
    table_type = "MANAGED_TABLE"

    storage_descriptor {
      location_uri  = "gs://__BUCKET__/data/"
      input_format  = "org.apache.hadoop.mapred.SequenceFileInputFormat"
      output_format = "org.apache.hadoop.hive.ql.io.HiveSequenceFileOutputFormat"
    }

    parameters = {
      owner = "data-team"
    }
  }
}
""".replace("__CATALOG__", CATALOG)
    .replace("__DATABASE__", DATABASE)
    .replace("__TABLE__", TABLE)
    .replace("__BUCKET__", BUCKET)
    .replace("__LOCATION__", LOCATION)
)

provider = GcpProvider(project=PROJECT, region="us-central1")
catalog = ServiceCatalog(PROJECT, credentials=provider.credentials)

stack = GcpStack(
    provider=provider,
    apis=catalog.enable("biglake", "bigquery", "storage"),
    buckets=[
        StorageBucket(
            project=PROJECT,
            name=BUCKET,
            location=LOCATION,
            force_destroy=True,
        )
    ],
    bucket_objects=[
        BucketObject(bucket=BUCKET, name="metadata/", content=" "),
        BucketObject(bucket=BUCKET, name="data/", content=" "),
    ],
    extra_files={"biglake.tf": BIGLAKE_TF},
)
