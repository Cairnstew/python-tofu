# Nix-authored stacks

Nix can author a stack, but it does not generate HCL. The Nix layer composes
and evaluates; the same Python models validate the result, apply the free-tier
limits, drive `prune` and render the HCL. There is one schema, so a Nix stack
cannot silently drift from a Python stack.

```
stack.nix / stackFile
        │  lib.evalStack (Nix module system)
        ▼
   JSON in the GcpStack schema
        │  provider models (extra="forbid")
        ▼
   GcpStack → GcpRenderer → HCL → tofu
```

## Flake input

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    python-tofu = {
      url = "github:Cairnstew/python-tofu";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, python-tofu, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      modules = [
        python-tofu.nixosModules.default   # or .python-tofu
        ./configuration.nix
      ];
    };
  };
}
```

`python-tofu` exposes:

| Output | Purpose |
|---|---|
| `nixosModules.default` / `nixosModules.python-tofu` | The NixOS module (`services.python-tofu`) |
| `homeManagerModules.default` / `.python-tofu` | The Home Manager package module |
| `overlays.default` | `pkgs.python-tofu` |
| `packages.<system>.default` | The CLI |
| `packages.<system>.with-tofu` | CLI + OpenTofu with the mirrored provider |
| `packages.<system>.with-tofu-nix` | `with-tofu` + a Nix binary for `.nix` configs |
| `lib.stackModule` | Path to `nix/stack.nix`, for direct `lib.evalModules` |
| `lib.evalStack` | `{ modules, specialArgs ? {} } → JSON-ready stack` |
| `lib.mkStackJson` | `args → JSON string` (`{ stack = ...; }`) |
| `lib.mkStackFile` | `pkgs → name → args → store path` |

## Authoring surface

`nix/stack.nix` defines one option per `GcpStack` field:

```nix
{ ... }:
{
  provider = {
    project = "my-project";
    region = "europe-west1";
    default_labels.managed-by = "python-tofu";
  };

  backend = { kind = "local"; path = "terraform.tfstate"; };

  projects.my-project.name = "My Project";

  apis.storage = {
    project = "my-project";
    service = "storage.googleapis.com";
  };

  service_accounts.ci-runner = {
    project = "my-project";
    roles = [ "roles/storage.admin" ];
  };

  buckets.artifacts = {
    project = "my-project";
    location = "EU";
    versioning = true;
  };

  outputs.bucket.value = "\${google_storage_bucket.bucket_artifacts.name}";
}
```

Sections are attribute sets keyed by a local name. The key fills the resource
identity field when it is not set explicitly:

| Section | Identity field |
|---|---|
| `projects` | `project_id` |
| `billing_budgets` | `display_name` |
| `service_accounts` | `account_id` |
| `buckets`, `bucket_objects` | `name` |
| `cloud_run_services`, `cloud_run_functions`, `cloud_run_jobs`, `cloud_run_worker_pools` | `name` |
| `pubsub_topics`, `pubsub_subscriptions` | `name` |
| `artifact_registry_repositories` | `repository_id` |
| `outputs` | `name` |

`apis`, `iam_members` and `service_account_iam_members` have no single identity
field, so their declarations supply every model field.

All sections merge with the Nix module system, so a declaration can be split
across files with `imports`, `mkMerge` and `mkIf`:

```nix
{ ... }:
{
  imports = [ ./network.nix ./storage.nix ];

  buckets.artifacts = lib.mkIf config.enableCache {
    project = "my-project";
    location = "EU";
  };
}
```

## References

Nix and HCL share `${...}` syntax, so a reference is just a string. Escape the
interpolation so Nix does not evaluate it:

```nix
outputs.bucket.value = "\${google_storage_bucket.bucket_artifacts.name}";
```

The renderer emits the string verbatim and skips its declared-set rewrite for
`BucketObject.bucket`, `PubSubSubscription.topic`, IAM principals and service
accounts.

Identity fields that become HCL labels (`buckets.*.name`, `*.project_id`,
`pubsub_topics.*.name`, service-account ids, Cloud Run names) must be literals.
Python validation rejects an interpolation there with a message explaining
that the computed part belongs in an attribute or an `output`.

## Bucket objects and versioning

`BucketObject` has exactly one content source, and the Nix surface accepts the
same fields as the Python model:

```nix
let
  release = { version = "1.4.0"; channel = "stable"; };
  app = pkgs.writeText "app.js" ''console.log("hello");'';
in
{
  buckets.artifacts = {
    project = "my-project";
    location = "EU";
    versioning = true;
  };

  bucket_objects = {
    # Text generated in Nix: inline `content`, no derivation.
    "config/release.json" = {
      bucket = "artifacts";
      content = builtins.toJSON release;
      content_type = "application/json";
      cache_control = "no-store";
    };

    # A build artifact or binary: pass its store path as `source`.
    "dist/app.js" = {
      bucket = "artifacts";
      source = "${app}";
      content_type = "application/javascript";
    };

    # A local file: a Nix path literal is copied into the store as well.
    "assets/logo.png" = {
      bucket = "artifacts";
      source = ./logo.png;
      content_type = "image/png";
    };
  };
}
```

`content = builtins.readFile ./config.json;` is the pure way to inline a file
that already exists in the tree. `source = "${drv}";` (or `source = drv;`, which
Nix serialises as its out path) is the way to pass a derivation; `source =
./path` is accepted too.

A path literal inside a flake is already a store path. If the declaration lives
outside a flake, wrap it in `builtins.path` so the service can read it and it
becomes part of the system closure:

```nix
source = builtins.path { path = ./logo.png; name = "logo.png"; };
```

### Data or derivation?

| Content | Use | Why |
|---|---|---|
| Small text, JSON/YAML, generated config | `content` | Self-contained in the stack JSON, diffable, no store path |
| Binary, tarball, compiled asset, large file | `source` (derivation/store path) | Nix strings are text; binaries belong in the store |
| Remote/mutable URL | `source_url` | Terraform fetches at plan/apply; not hermetic |

Passing the derivation is the better default for artifacts: the file is built
hermetically, the stack JSON stays small, and OpenTofu hashes the file at
`source` so an unchanged file is a no-op. Its downside is that a store path can
change when unrelated derivation inputs change (for example a nixpkgs update)
even when the bytes are identical, which causes a re-upload. If that matters,
use a content-addressed path (`builtins.path`, `builtins.toFile`, or a
fixed-output derivation) or inline the bytes with `content` when they are
text.

### Versioning

Terraform identifies `google_storage_bucket_object` by object name and compares
the declared content/file hash with state. There are two useful patterns:

- **Same name + bucket versioning** — set `StorageBucket.versioning = true` and
  keep the object key stable. A content change updates the live object and GCS
  retains the previous generation.
- **Content-addressed name** — put a hash/version in the key, e.g.
  `"dist/app-${builtins.substring 0 12 (builtins.hashString "sha256" appText)}.js"`.
  Every version is a distinct object. Note that `prune` does not include bucket
  objects (`GCP_PRUNE_SECTIONS` covers buckets, subscriptions, topics,
  project IAM, service accounts, APIs and projects), so old keys accumulate;
  use a GCS lifecycle rule to expire them.

For a directory of assets:

```nix
bucket_objects = lib.mapAttrs'
  (name: _type: lib.nameValuePair "assets/${name}" {
    bucket = "artifacts";
    source = builtins.path {
      path = ./assets/${name};
      name = builtins.baseNameOf name;
    };
  })
  (lib.filterAttrs (_: type: type == "regular") (builtins.readDir ./assets));
```

`source` is resolved to an absolute path at render time, so a store path is
what you want; a bare relative string would resolve against the process working
directory instead of the config file.

## Evaluate without NixOS

```nix
let
  stack = python-tofu.lib.evalStack { modules = [ ./infra.nix ]; };
in
python-tofu.lib.mkStackFile pkgs "stack.json" { modules = [ ./infra.nix ]; }
```

The JSON file is in the `GcpStack` schema, so every command works:

```bash
python-tofu render --config stack.json --workdir .tofu/demo
python-tofu plan   --config stack.json --workdir .tofu/demo
```

For a standalone `.nix` file evaluated by `nix eval --file`, use the array
schema directly (see `examples/gcp_nix/stack.nix`):

```nix
{
  stack = {
    provider = { project = "my-project"; };
    buckets = [ { project = "my-project"; name = "artifacts"; } ];
  };
}
```

`python-tofu` accepts `.py`, `.json` and `.nix` configs. A `.nix` config is
evaluated with `nix eval --json`; use `packages.<system>.with-tofu-nix` (or put
`nix` on `PATH`) for that form. NixOS `stack`/`stackFile` declarations are
evaluated at build time and do **not** need `nix` on the host.

## Rebuild-time apply

```nix
services.python-tofu = {
  enable = true;
  stackFile = ./infra.nix;
  settings = {
    command = "apply";
    autoApprove = true;
  };
};
```

The module evaluates the declaration at build time, writes JSON to the store,
and passes it as `--config`. `restartTriggers` makes `nixos-rebuild switch`
restart the boot-time oneshot when the evaluated stack or package changes, so
the rebuild reconciles the declared infrastructure. `autoApprove` is off by
default: an accidental `command = "apply"` still stops at the approval prompt.

## Limits and pruning

The Nix JSON is validated into the same `GcpStack`, so free-tier limits,
`prune` sections and `doctor` behave exactly as they do for a Python stack.
`extra_files` (raw `.tf`/`.tf.json`) is still the untyped escape hatch and is
not visible to limits or prune.
