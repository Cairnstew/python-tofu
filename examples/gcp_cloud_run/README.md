# Cloud Run: image-based service and source-based function

Both paths are now typed DSL resources.

1. **Cloud Run service (`CloudRunService` → `google_cloud_run_v2_service`)** —
   takes a container image reference. OpenTofu does **not** build images. Build
   and push in CI (Docker, `ko`, buildpacks, `gcloud builds submit`) and
   reference a digest:

   ```python
   IMAGE = "us-docker.pkg.dev/PROJECT/REPO/APP@sha256:..."
   ```

   `gcloud run deploy --source .` is a CLI/Cloud Build feature, not a Terraform
   resource. For source deploys, use CI or a `google_cloudbuild_trigger` that
   builds on push.

2. **Cloud Run function, 2nd gen (`CloudRunFunction` →
   `google_cloudfunctions2_function`)** — accepts a source zip in GCS. `stack.py`
   zips `hello/` deterministically, uploads it with a typed `BucketObject`, and
   the renderer references the object's bucket/name/generation. This is the
   "source piped into tofu" path.

## Background worker pool

`CloudRunWorkerPool` deploys a pull-based worker: no ingress, no URL, no
requests. The container starts with the instance and runs until replaced.

```python
CloudRunWorkerPool(
    project=PROJECT,
    name="queue-worker",
    image=IMAGE,
    command=["python", "-m", "worker"],
    manual_instance_count=1,
)
```

Instances bill per instance-second with a one-minute minimum, so set
`manual_instance_count=0` (or destroy the pool) when it is idle. Unlike a
service, a worker pool cannot use startup or liveness probes.

## Volumes and probes

Both are declared on the service: a `Volume` names its source and mount path, so
the renderer can never emit a `volume_mounts` entry without a matching `volumes`
block.

```python
volumes=[
    Volume(name="scratch", mount_path="/tmp/scratch", empty_dir=EmptyDirVolume()),
    Volume(name="assets", mount_path="/mnt/assets", gcs=GcsVolume(bucket="my-assets")),
],
startup_probe=Probe(http_get=HttpProbe(path="/health"), period_seconds=5),
liveness_probe=Probe(tcp_socket=TcpProbe(port=8080), period_seconds=30),
```

## Batch runner

`CloudRunJob` deploys a one-shot task runner from the same image:

```python
CloudRunJob(
    project=PROJECT,
    name="nightly-runner",
    image=IMAGE,
    command=["python", "-m", "job"],
    env={"MODE": "batch"},
    max_retries=0,
)
```

Declaring the job does not run it; trigger it with the Cloud Run API
(`jobs:run`) or the console. It scales to zero between executions.

## Hardened defaults

`CloudRunService` and `CloudRunFunction` are private and cost-capped unless you
opt out:

- internal-only ingress;
- no `allUsers` invoker binding;
- `deletion_protection = true` (services);
- scale-to-zero, `max_instance_count = 10`;
- 1 vCPU / 512 MiB (service), 256 MB (function);
- a declared runtime service account with no project roles (least privilege).

To expose a service publicly, opt in explicitly:

```python
CloudRunService(
    ...,
    allow_unauthenticated=True,   # adds allUsers / roles/run.invoker
    ingress="all",                # or internal-and-load-balancer
)
```

## Run it

```bash
python-tofu render --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
python-tofu plan   --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
python-tofu apply  --config examples/gcp_cloud_run/stack.py --workdir .tofu/cloudrun
```

`deletion_protection=True` blocks `destroy`. To tear the service down, set
`deletion_protection=False` and apply before destroying.

## Prerequisites

- Replace `IMAGE` with your own image for production. The public
  `us-docker.pkg.dev/cloudrun/container/hello` image is used so the example
  works without a registry.
- 2nd-gen functions build through Cloud Build; the Cloud Functions service agent
  may need `roles/storage.objectViewer` on the source bucket, and Cloud Build /
  Artifact Registry need their normal permissions.
- APIs enabled by the stack: `run`, `cloudfunctions`, `cloudbuild`,
  `artifactregistry`, `eventarc`, `storage`, `iam`.

## Free tier

A scale-to-zero service such as this can stay inside the Cloud Run free tier
(request-based: 2M requests, 180k vCPU-s, 360k GiB-s per billing account per
month). 2nd-gen functions run as Cloud Run services and use the same tier.
