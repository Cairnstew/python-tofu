"""Clean multi-file stack: one module per resource family.

This file only wires the parts together, so a change to storage touches
``parts/storage.py`` and nothing else.

    python-tofu plan  --config examples/gcp_clean/stack.py --workdir .tofu/clean
    python-tofu apply --config examples/gcp_clean/stack.py --workdir .tofu/clean

State is local by default; add ``backend=BackendConfig(kind="gcs", bucket=...)``
once several people need to share it.
"""

from parts.foundation import apis, projects, provider
from parts.iam import iam_members, service_accounts
from parts.storage import bucket_objects, buckets

from python_tofu import GcpStack

stack = GcpStack(
    provider=provider,
    projects=projects,
    apis=apis,
    service_accounts=service_accounts,
    iam_members=iam_members,
    buckets=buckets,
    bucket_objects=bucket_objects,
)
