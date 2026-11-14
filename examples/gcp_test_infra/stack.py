"""Free-tier test stack for exercising state, prune and destroy.

Every resource below stays inside the GCP Always Free tier:

- one regional bucket in ``us-central1`` with one tiny object (5 GB free);
- one Pub/Sub topic and pull subscription (10 GiB free, empty here);
- one service account (free);
- the control-plane API baseline plus the workload APIs those resources need
  (``storage``, ``pubsub``, ``iam``).

The stack is deliberately local-state and uses its own workdir, so it cannot
touch a shared backend. Prune is enabled and defaults to every section, so an
``apply`` also deletes undeclared buckets, topics, subscriptions and APIs.
Service accounts are the exception: they need both
``include_service_accounts=True`` here and ``--allow-service-accounts`` on the
run. Inspect the dry run before applying:

    python-tofu plan   --config examples/gcp_test_infra/stack.py
    python-tofu apply  --config examples/gcp_test_infra/stack.py --auto-approve
    python-tofu output --config examples/gcp_test_infra/stack.py
    python-tofu destroy --config examples/gcp_test_infra/stack.py --auto-approve

``prune`` is not the inverse of ``destroy``: it deletes live resources this
stack does **not** declare, which in a shared project also means unrelated
buckets, topics or APIs. The default API baseline is protected; everything
else is fair game. Use ``--section`` and inspect the dry run first;
``docs/reference/cli.md`` has the full warning.
"""

import os

from python_tofu import (
    BucketObject,
    GcpProvider,
    GcpStack,
    Output,
    PruneConfig,
    PubSubSubscription,
    PubSubTopic,
    ServiceAccount,
    StorageBucket,
    ref,
)
from python_tofu.providers.gcp.quirks import slug

# The project comes from the dev-shell environment. The placeholder keeps the
# example importable without credentials; apply only with a real project.
PROJECT = os.environ.get("GOOGLE_PROJECT", "example-free-tier")
REGION = "us-central1"
SUFFIX = "tofu-test-infra"

BUCKET = f"{PROJECT}-{SUFFIX}"
TOPIC = "tofu-test-topic"
SUBSCRIPTION = "tofu-test-sub"
ACCOUNT = "tofu-test-runner"

provider = GcpProvider(
    project=PROJECT,
    region=REGION,
    default_labels={"managed-by": "python-tofu", "purpose": "free-tier-test"},
)

stack = GcpStack(
    name="test-infra",
    provider=provider,
    # Prune is authoritative for every section except service accounts. The
    # SA gate is deliberately two-key: set include_service_accounts=True here
    # *and* pass --allow-service-accounts on the run.
    prune=PruneConfig(enabled=True),
    service_accounts=[
        ServiceAccount(
            project=PROJECT,
            account_id=ACCOUNT,
            display_name="python-tofu free-tier test",
            description="Created by examples/gcp_test_infra; safe to delete.",
        )
    ],
    buckets=[
        StorageBucket(
            project=PROJECT,
            name=BUCKET,
            location=REGION,
            # Counted by the free-tier policy (us-central1, 5 GB free).
            estimated_size_gb=0.001,
            # Test bucket: let `destroy` remove the object with the bucket.
            force_destroy=True,
            labels={"purpose": "free-tier-test"},
        )
    ],
    bucket_objects=[
        BucketObject(
            bucket=BUCKET,
            name="hello.txt",
            content="Managed by the python-tofu free-tier test stack.\n",
            content_type="text/plain",
            metadata={"managed-by": "python-tofu"},
        )
    ],
    pubsub_topics=[PubSubTopic(project=PROJECT, name=TOPIC)],
    pubsub_subscriptions=[
        PubSubSubscription(
            project=PROJECT,
            name=SUBSCRIPTION,
            topic=TOPIC,
            ack_deadline_seconds=10,
            # Explicit TTL: the provider drops an empty value and expires in 31 days.
            expiration_ttl="2678400s",
        )
    ],
    # Read these back with `python-tofu output`.
    outputs=[
        Output(
            "bucket_name",
            ref(f"google_storage_bucket.bucket_{slug(BUCKET)}.name"),
            description="Regional free-tier bucket",
        ),
        Output(
            "topic_id",
            ref(f"google_pubsub_topic.topic_{slug(TOPIC)}.id"),
            description="Resource name of the test topic",
        ),
        Output(
            "subscription_id",
            ref(f"google_pubsub_subscription.sub_{slug(SUBSCRIPTION)}.id"),
            description="Resource name of the pull subscription",
        ),
        Output(
            "service_account_email",
            ref(f"google_service_account.sa_{slug(ACCOUNT)}.email"),
            description="Email of the test service account",
        ),
    ],
)
