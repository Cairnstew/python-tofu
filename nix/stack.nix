# A NixOS-module-system front-end for a python-tofu GCP stack.
#
# Import it next to a declaration module:
#
#   nixpkgs.lib.evalModules {
#     modules = [
#       python-tofu.lib.stackModule
#       {
#         provider.project = "demo-project";
#         buckets.artifacts = { location = "EU"; };
#       }
#     ];
#   }
#
# or use the flake helper, which returns the JSON-ready stack:
#
#   python-tofu.lib.evalStack { modules = [ ./infra.nix ]; }
#
# Option names mirror `GcpStack` exactly (with the exception of `_stack`),
# so the value is validated by the provider's Pydantic models and rendered by
# the same renderer as a Python-authored stack. Nix provides composition;
# Python still owns validation, limits and HCL.
#
# Resource sections are attribute sets keyed by a local name. The key fills the
# resource's identity field when it is not set explicitly:
#
#   buckets.artifacts = { project = "demo-project"; };
#   # -> buckets = [ { name = "artifacts"; project = "demo-project"; } ];
#
# A computed Terraform reference is a plain string with an escaped
# interpolation: `"\${google_storage_bucket.bucket_artifacts.name}"`.
{ config, lib, ... }:

let
  inherit (lib) mkOption types;

  # A JSON-compatible value. Same shape Terranix uses, minus the
  # __functor/__toString block magic: values here are data, never references.
  # `path` is accepted so a bucket object can point at `./dist/app.js`;
  # `builtins.toJSON` serialises both paths and derivations as their out path.
  valueType =
    with types;
    nullOr (oneOf [
      bool
      int
      float
      str
      path
      (attrsOf valueType)
      (listOf valueType)
    ]);

  section = description:
    mkOption {
      type = types.attrsOf valueType;
      default = { };
      inherit description;
    };

  # Turn a keyed section into a list, filling the identity field from the key
  # unless the declaration set it explicitly.
  withIdentity = identity: values:
    map
      (name:
        let value = values.${name}; in
        if builtins.isAttrs value && !(value ? ${identity})
        then value // { ${identity} = name; }
        else value)
      (builtins.attrNames values);

  # Sections with no obvious identity field stay keyed only for composition;
  # the declaration supplies the fields the model needs.
  plain = values: map (name: values.${name}) (builtins.attrNames values);

  optional = name: value: if value == null then { } else { ${name} = value; };
in
{
  options = {
    # ── envelope ──────────────────────────────────────────────────────
    required_version = mkOption {
      type = types.str;
      default = ">= 1.6.0";
      description = "OpenTofu version constraint (`terraform.required_version`).";
    };

    name = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Stack name, used for the default workdir and state prefix.";
    };

    provider = mkOption {
      type = types.attrsOf valueType;
      default = { };
      description = "The `google` provider block; `project` is required.";
    };

    backend = mkOption {
      type = types.nullOr (types.attrsOf valueType);
      default = null;
      description = "State backend (`kind` plus settings); null keeps the renderer default.";
    };

    profile = mkOption {
      type = types.enum [ "default" "preview" ];
      default = "default";
      description = "Documented default bundle; `preview` turns deletion protection off.";
    };

    google_provider_version = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Provider constraint; null uses the packaged/default value.";
    };

    limits_mode = mkOption {
      type = types.nullOr (types.enum [ "error" "warn" "off" ]);
      default = null;
      description = "Stack-level limit enforcement.";
    };

    prune = section "Prune config (`enabled`, `sections`, `include_service_accounts`).";

    extra_files = mkOption {
      type = types.attrsOf types.str;
      default = { };
      description = "Extra `.tf`/`.tf.json` files written verbatim into the workdir.";
    };

    usage_estimates = mkOption {
      type = types.attrsOf (types.either types.int types.float);
      default = { };
      description = "Estimated monthly usage keyed by limit key.";
    };

    external_projects = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Existing projects resources may reference without declaring them.";
    };

    external_buckets = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Existing buckets objects may target without declaring them.";
    };

    external_topics = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Existing topics subscriptions may target without declaring them.";
    };

    # ── resource sections ─────────────────────────────────────────────
    projects = section "`google_project` resources, keyed by project id.";
    billing_budgets = section "`google_billing_budget` resources, keyed by display name.";
    apis = section "`google_project_service` resources, keyed by a local name.";
    service_accounts = section "`google_service_account` resources, keyed by account id.";
    buckets = section "`google_storage_bucket` resources, keyed by bucket name.";
    bucket_objects = section "`google_storage_bucket_object` resources, keyed by object name.";
    iam_members = section "`google_project_iam_member` resources, keyed by a local name.";
    service_account_iam_members = section "`google_service_account_iam_member` resources, keyed by a local name.";
    cloud_run_services = section "`google_cloud_run_v2_service` resources, keyed by service name.";
    cloud_run_functions = section "Cloud Run function resources, keyed by function name.";
    cloud_run_jobs = section "Cloud Run job resources, keyed by job name.";
    cloud_run_worker_pools = section "Cloud Run worker-pool resources, keyed by pool name.";
    pubsub_topics = section "`google_pubsub_topic` resources, keyed by topic name.";
    pubsub_subscriptions = section "`google_pubsub_subscription` resources, keyed by name.";
    artifact_registry_repositories = section "Artifact Registry repositories, keyed by repository id.";
    outputs = section "OpenTofu outputs, keyed by output name.";

    # ── derived JSON view ─────────────────────────────────────────────
    _stack = mkOption {
      type = types.attrsOf valueType;
      readOnly = true;
      internal = true;
      description = "The configuration in the `GcpStack` JSON schema.";
    };
  };

  config._stack = {
    required_version = config.required_version;
    provider = config.provider;
    profile = config.profile;
    prune = config.prune;
    extra_files = config.extra_files;
    usage_estimates = config.usage_estimates;
    external_projects = config.external_projects;
    external_buckets = config.external_buckets;
    external_topics = config.external_topics;

    projects = withIdentity "project_id" config.projects;
    billing_budgets = withIdentity "display_name" config.billing_budgets;
    apis = plain config.apis;
    service_accounts = withIdentity "account_id" config.service_accounts;
    buckets = withIdentity "name" config.buckets;
    bucket_objects = withIdentity "name" config.bucket_objects;
    iam_members = plain config.iam_members;
    service_account_iam_members = plain config.service_account_iam_members;
    cloud_run_services = withIdentity "name" config.cloud_run_services;
    cloud_run_functions = withIdentity "name" config.cloud_run_functions;
    cloud_run_jobs = withIdentity "name" config.cloud_run_jobs;
    cloud_run_worker_pools = withIdentity "name" config.cloud_run_worker_pools;
    pubsub_topics = withIdentity "name" config.pubsub_topics;
    pubsub_subscriptions = withIdentity "name" config.pubsub_subscriptions;
    artifact_registry_repositories =
      withIdentity "repository_id" config.artifact_registry_repositories;
    outputs = withIdentity "name" config.outputs;
  }
  // optional "name" config.name
  // optional "backend" config.backend
  // optional "google_provider_version" config.google_provider_version
  // optional "limits_mode" config.limits_mode;
}
