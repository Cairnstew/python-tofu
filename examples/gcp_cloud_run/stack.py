"""Cloud Run: a hardened image-based service and a source-based function.

Both resources are now modelled by the DSL. Defaults are hardened: internal
ingress, no unauthenticated invoker, deletion protection, scale-to-zero with a
bounded maximum, and 1 vCPU / 512 MiB. The example keeps those defaults; see the
comments for the explicit opt-in to public traffic.

    python-tofu render --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
    python-tofu plan   --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
    python-tofu apply  --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
"""

import io
import os
import zipfile
from pathlib import Path

from python_tofu import (
    BucketObject,
    CloudRunFunction,
    CloudRunService,
    CloudRunWorkerPool,
    EmptyDirVolume,
    GcpProvider,
    GcpStack,
    HttpProbe,
    Probe,
    ServiceAccount,
    StorageBucket,
    Volume,
)

PROJECT = os.environ.get("GOOGLE_PROJECT", "example-cloud-run")
LOCATION = "us-central1"
SOURCE_BUCKET = f"{PROJECT}-cloudrun-src"
RUNTIME_ACCOUNT = "hello-runtime"

# Use a digest for reproducible deploys:
# us-docker.pkg.dev/PROJECT/REPO/APP@sha256:...
IMAGE = "us-docker.pkg.dev/cloudrun/container/hello"

HELLO_DIR = Path(__file__).parent / "hello"


def zip_dir(path: Path) -> bytes:
    """Deterministic zip: fixed timestamps keep the object hash stable."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(path.rglob("*")):
            if item.is_file():
                info = zipfile.ZipInfo(str(item.relative_to(path)), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, item.read_bytes())
    return buffer.getvalue()


provider = GcpProvider(project=PROJECT, region=LOCATION)

# APIs are derived from the declared resources (functions pull in Cloud Build,
# Eventarc, Artifact Registry and Storage). Set auto_enable_apis=False on the
# provider if API enablement belongs to another team or pipeline.
stack = GcpStack(
    provider=provider,
    service_accounts=[
        # Least privilege: the workload identity has no project roles.
        ServiceAccount(project=PROJECT, account_id=RUNTIME_ACCOUNT),
    ],
    buckets=[
        StorageBucket(
            project=PROJECT,
            name=SOURCE_BUCKET,
            location="US",
            uniform_bucket_level_access=True,
        )
    ],
    bucket_objects=[
        BucketObject(
            bucket=SOURCE_BUCKET,
            name="hello.zip",
            content=zip_dir(HELLO_DIR),
        )
    ],
    cloud_run_services=[
        CloudRunService(
            project=PROJECT,
            name="pt-hello-service",
            location=LOCATION,
            image=IMAGE,
            service_account=RUNTIME_ACCOUNT,
            # Hardened defaults: internal ingress, private invoker, capped scaling.
            # To expose publicly set allow_unauthenticated=True and ingress="all".
            volumes=[
                Volume(
                    name="scratch",
                    mount_path="/tmp/scratch",
                    empty_dir=EmptyDirVolume(size_limit="256Mi"),
                )
            ],
            startup_probe=Probe(http_get=HttpProbe(path="/"), period_seconds=5),
            liveness_probe=Probe(http_get=HttpProbe(path="/"), period_seconds=30),
        )
    ],
    cloud_run_worker_pools=[
        CloudRunWorkerPool(
            project=PROJECT,
            name="pt-hello-worker",
            location=LOCATION,
            image=IMAGE,
            service_account=RUNTIME_ACCOUNT,
            # Pull-based worker: no ingress, no URL. One instance by default.
            manual_instance_count=1,
            env={"MODE": "worker"},
            volumes=[
                Volume(
                    name="scratch",
                    mount_path="/tmp/scratch",
                    empty_dir=EmptyDirVolume(size_limit="256Mi"),
                )
            ],
        )
    ],
    cloud_run_functions=[
        CloudRunFunction(
            project=PROJECT,
            name="pt-hello-function",
            location=LOCATION,
            runtime="python312",
            entry_point="hello_http",
            source_bucket=SOURCE_BUCKET,
            source_object="hello.zip",
            service_account=RUNTIME_ACCOUNT,
            # Hardened defaults: internal ingress, private invoker, capped scaling.
            # To expose publicly set allow_unauthenticated=True and ingress="all".
        )
    ],
)
