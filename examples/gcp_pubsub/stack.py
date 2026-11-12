"""Pub/Sub: a topic with a pull worker, a dead-letter topic and a push target.

The push subscription points at a declared Cloud Run service through
``push_service``, which resolves to that service's ``uri``. The service grants
the push identity ``roles/run.invoker`` via ``invoker_service_accounts``; both
halves are required for a private service to accept the push.

    python-tofu render --config examples/gcp_pubsub/stack.py --workdir .tofu/pubsub
    python-tofu plan   --config examples/gcp_pubsub/stack.py --workdir .tofu/pubsub
    python-tofu apply  --config examples/gcp_pubsub/stack.py --workdir .tofu/pubsub
    python-tofu output --workdir .tofu/pubsub
"""

import os

from python_tofu import (
    CloudRunService,
    DeadLetter,
    GcpProvider,
    GcpStack,
    Output,
    PubSubSubscription,
    PubSubTopic,
    RetryPolicy,
    ServiceAccount,
    ref,
)

PROJECT = os.environ.get("GOOGLE_PROJECT", "example-pubsub")
LOCATION = "us-central1"
PUSH_ACCOUNT = "pubsub-push"
IMAGE = "us-docker.pkg.dev/cloudrun/container/hello"

provider = GcpProvider(project=PROJECT, region=LOCATION)

# `pubsub`, `run` and `iam` are enabled automatically from the resources below,
# and each resource is ordered after its google_project_service.
stack = GcpStack(
    provider=provider,
    service_accounts=[
        # OIDC identity attached to push requests; no project roles.
        ServiceAccount(project=PROJECT, account_id=PUSH_ACCOUNT),
    ],
    cloud_run_services=[
        CloudRunService(
            project=PROJECT,
            name="push-receiver",
            location=LOCATION,
            image=IMAGE,
            # Public ingress but IAM-protected: only the push identity may call it.
            ingress="all",
            allow_unauthenticated=False,
            invoker_service_accounts=[PUSH_ACCOUNT],
            deletion_protection=False,
        )
    ],
    pubsub_topics=[
        PubSubTopic(project=PROJECT, name="jobs"),
        PubSubTopic(project=PROJECT, name="jobs-dlq", message_retention_duration="86400s"),
    ],
    pubsub_subscriptions=[
        # Pull worker: filter out non-matching attributes, retry with backoff,
        # and dead-letter after ten attempts.
        PubSubSubscription(
            project=PROJECT,
            name="jobs-worker",
            topic="jobs",
            ack_deadline_seconds=60,
            filter='attributes.kind="work"',
            dead_letter=DeadLetter(topic="jobs-dlq", max_delivery_attempts=10),
            retry=RetryPolicy(minimum_backoff="10s", maximum_backoff="300s"),
            enable_message_ordering=True,
            # Explicit TTL: "" is dropped by the provider and expires in 31 days.
            expiration_ttl="315360000s",
        ),
        # Push receiver: Pub/Sub signs a JWT as PUSH_ACCOUNT and Cloud Run
        # checks run.invoker, which the service above grants.
        PubSubSubscription(
            project=PROJECT,
            name="jobs-push",
            topic="jobs",
            ack_deadline_seconds=30,
            push_service="push-receiver",
            push_service_account=PUSH_ACCOUNT,
        ),
    ],
    # Read these back with `python-tofu output --workdir <.tofu dir>`.
    outputs=[
        Output(
            "topic_id",
            ref("google_pubsub_topic.topic_jobs.id"),
            description="Resource name of the jobs topic",
        ),
        Output(
            "push_service_url",
            ref("google_cloud_run_v2_service.run_push_receiver.uri"),
            description="URL Pub/Sub pushes to",
        ),
        Output(
            "push_subscription",
            ref("google_pubsub_subscription.sub_jobs_push.id"),
            description="Resource name of the push subscription",
        ),
    ],
)
