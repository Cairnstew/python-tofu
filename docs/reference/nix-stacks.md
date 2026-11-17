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

`apis` and `iam_members` have no single identity field, so their declarations
supply every model field.

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
