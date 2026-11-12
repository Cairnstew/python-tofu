"""Enable Google APIs by short name, validated against Service Usage.

Run it with credentials available (ADC or GOOGLE_APPLICATION_CREDENTIALS):

    python-tofu plan  --config examples/gcp_apis/stack.py --workdir .tofu/apis
    python-tofu apis  --config examples/gcp_apis/stack.py --state enabled
    python-tofu apis  --config examples/gcp_apis/stack.py --resolve run

`ServiceCatalog.enable` resolves each name with the per-service
`services.get` endpoint, so this config does not consume the rate-limited
"list available services" quota.
"""

import os

from python_tofu import GcpProvider, GcpStack, StorageBucket
from python_tofu.providers.gcp.services import ServiceCatalog

PROJECT = os.environ.get("GOOGLE_PROJECT", "example-apis")

REQUIRED_APIS = (
    "compute",
    "run",
    "storage",
    "iam",
    "logging",
)

provider = GcpProvider(project=PROJECT, region="europe-west1")
catalog = ServiceCatalog(provider.project, credentials=provider.credentials)

stack = GcpStack(
    provider=provider,
    apis=catalog.enable(*REQUIRED_APIS),
    buckets=[
        StorageBucket(
            project=PROJECT,
            name=f"{PROJECT}-artifacts",
            location="EU",
            versioning=True,
        )
    ],
)
