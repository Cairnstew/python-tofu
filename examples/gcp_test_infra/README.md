# Free-tier test infrastructure

A minimal stack for exercising the real apply → inspect state → prune/destroy
loop without leaving the GCP Always Free tier.

| Resource | Free-tier allowance |
|---|---|
| `StorageBucket` in `us-central1` + one tiny object | 5 GB-months regional storage |
| `PubSubTopic` + pull `PubSubSubscription` (empty) | 10 GiB-months |
| `ServiceAccount` (no project roles) | free |
| Derived `google_project_service` resources | free |

State is local unless `.tofu/test-infra/terraform.tfstate` is pointed at a
backend. The project comes from `GOOGLE_PROJECT`; the bucket name embeds it so
two projects cannot collide.

```bash
python-tofu plan   --config examples/gcp_test_infra/stack.py
python-tofu apply  --config examples/gcp_test_infra/stack.py --auto-approve
python-tofu output --config examples/gcp_test_infra/stack.py
python-tofu limits --config examples/gcp_test_infra/stack.py
```

## Prune is on

The stack sets `prune=PruneConfig(enabled=True)`, so `apply` also deletes live
resources it does not declare. Start with the dry run, because this is
project-wide:

```bash
python-tofu plan  --config examples/gcp_test_infra/stack.py   # includes the prune plan
python-tofu prune --config examples/gcp_test_infra/stack.py --all
python-tofu prune --config examples/gcp_test_infra/stack.py --apply --section buckets
```

Two guards limit the blast radius:

- **API baseline.** `GcpProvider.default_apis` (defaults in
  `providers/gcp/service_names.py`) is enabled on every owned project and never
  pruned. Add workload APIs with `default_apis=(...)` or `apis=[ProjectApi(...)]`
  if other infrastructure needs them; everything else is prunable.
- **Service accounts are two-key.** `prune --all` skips them unless the stack
  sets `prune.include_service_accounts=True` **and** the run passes
  `--allow-service-accounts`. Deleting the identity that runs `tofu` is
  irreversible.

## Deleting it

`destroy` removes only the resources above; it does not prune unrelated live
infrastructure:

```bash
python-tofu destroy --config examples/gcp_test_infra/stack.py --auto-approve
```
