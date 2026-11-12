"""Storage: buckets and their objects, in one place.

``bucket()`` supplies the project and location so a new bucket is one line and
cannot drift from the foundation settings. Objects are declared with inline
content, a local file or a URL; Terraform only re-uploads when that content
changes.
"""

from typing import Any

from python_tofu import BucketObject, StorageBucket

from .foundation import LOCATION, PROJECT


def bucket(name: str, **options: Any) -> StorageBucket:
    return StorageBucket(
        project=PROJECT,
        name=f"{PROJECT}-{name}",
        location=LOCATION,
        **options,
    )


buckets = [
    bucket("artifacts", versioning=True, labels={"purpose": "ci"}),
    bucket("model-cache", labels={"purpose": "cache"}),
]

bucket_objects = [
    BucketObject(
        bucket=f"{PROJECT}-artifacts",
        name="config/release.json",
        content='{"release": "v1", "channel": "stable"}',
        content_type="application/json",
        cache_control="no-store",
        metadata={"managed-by": "python-tofu"},
    ),
    BucketObject(
        bucket=f"{PROJECT}-model-cache",
        name="README.txt",
        content="Managed by python-tofu; edits here are overwritten.\n",
        content_type="text/plain",
    ),
]
