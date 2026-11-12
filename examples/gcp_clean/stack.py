"""Clean multi-file stack: one module per resource family.

This file only wires the parts together, so a change to storage touches
``parts/storage.py`` and nothing else.

    python-tofu plan  --config examples/gcp_clean/stack.py --workdir .tofu/clean
    python-tofu apply --config examples/gcp_clean/stack.py --workdir .tofu/clean

State is local by default; add ``backend=BackendConfig(kind="gcs", bucket=...)``
once several people need to share it.
"""

from parts.foundation import part as foundation
from parts.foundation import provider
from parts.iam import part as iam
from parts.storage import part as storage

from python_tofu import GcpStack, compose

# `compose` merges the parts and rejects the same bucket, topic or account
# declared twice, naming both parts in the error.
stack = GcpStack(provider=provider, **compose(foundation, storage, iam))
