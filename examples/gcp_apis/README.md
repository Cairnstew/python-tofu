# Declaring enabled Google APIs

The Service Usage API knows which services a project can enable and which are
already on. `python_tofu.providers.gcp.services` wraps that into a small catalog
so configs can use short, validated names instead of hand-written
`*.googleapis.com` strings.

## 1. Validated short names (recommended)

```python
import os

from python_tofu import GcpProvider, GcpStack
from python_tofu.providers.gcp.services import ServiceCatalog

PROJECT = os.environ["GOOGLE_PROJECT"]
provider = GcpProvider(project=PROJECT)
catalog = ServiceCatalog(PROJECT, credentials=provider.credentials)

stack = GcpStack(
    provider=provider,
    apis=catalog.enable("compute", "run", "storage", "iam", "logging"),
)
```

`enable(...)`:

- accepts short (`run`) or full (`run.googleapis.com`) names;
- resolves each with `services.get`, so it does **not** consume the
  rate-limited listing quota;
- deduplicates while preserving order;
- returns `ProjectApi` objects (already enabled services included — re-declaring
  one is an OpenTofu no-op); pass `disable_on_destroy=True` to also disable the
  API when the resource is destroyed;
- raises `UnknownService` with suggestions for a typo, and `AmbiguousService`
  when a partial name matches several services.

If the config should stay usable without network access, pass plain
`ProjectApi`s instead:

```python
from python_tofu import ProjectApi

stack = GcpStack(
    provider=provider,
    apis=[ProjectApi(project=PROJECT, service="compute.googleapis.com")],
)
```

## 2. One-shot helper

```python
from python_tofu import enable_apis

stack = GcpStack(provider=provider, apis=enable_apis(PROJECT, "compute", "storage"))
```

## 3. Inspect what is available

```bash
# Enabled services (unrestricted listing, safe to run often)
python-tofu apis --config examples/gcp_apis/stack.py --state enabled
python-tofu apis --project my-project --state enabled --filter storage

# Services that can still be enabled (rate-limited by Google)
python-tofu apis --project my-project --state available --filter compute

# Everything
python-tofu apis --project my-project --state all --json

# Resolve one short name without a listing
python-tofu apis --project my-project --resolve run
# run.googleapis.com  Cloud Run Admin API  [disabled]
```

With user credentials (ADC), pass the quota project:

```bash
python-tofu apis --project my-project --quota-project my-project --state enabled
```

## Quotas

Service Usage throttles the **available/disabled** listing hard — often one
request per minute. `--state enabled` and `--resolve NAME` do not use it.
`available()`, `all()` and fuzzy resolution do, and report a clear 429 hint when
the quota is exhausted. The catalog caches each listing for the process, so a
config that calls `available()` twice only makes one request.

## Programmatic API

```python
from python_tofu.providers.gcp.services import (
    ServiceCatalog,
    canonical_service,
    get_service,
    list_services,
)

catalog = ServiceCatalog(PROJECT)
catalog.enabled()                 # tuple[Service, ...]
catalog.available("compute")      # filtered disabled services
catalog.all()                     # enabled + disabled
catalog.resolve("run")            # exactly one Service
catalog.lookup("run")             # Service | None (services.get)

canonical_service("run")          # "run.googleapis.com"
get_service(PROJECT, token, "run")  # Service | None, no listing
list_services(PROJECT, token, state="ENABLED")
```
