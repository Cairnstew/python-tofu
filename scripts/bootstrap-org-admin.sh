#!/usr/bin/env bash
#
# bootstrap-org-admin.sh — one-time seed for a Google Cloud organization.
#
# Creates an org-level "seed" admin service account inside a host project,
# grants it organization-level admin roles, links billing, and downloads a
# JSON key.
#
# The run uses a TEMPORARY `gcloud auth login`: gcloud state lives in a fresh
# throwaway CLOUDSDK_CONFIG, so the login, account selection and cached tokens
# are discarded when the script exits. Your normal gcloud configuration is
# never touched. Pass --use-existing to run against the current gcloud session
# instead, or --keep-login to retain the temporary configuration for debugging.
#
# Run ONCE as a human who has (at the org level):
#   - roles/resourcemanager.organizationAdmin   (to grant org roles)
#   - roles/orgpolicy.policyAdmin               (only for --override-key-policy)
# and on the billing account:
#   - roles/billing.admin                       (to link billing + grant billing.user)
# and on the project:
#   - roles/owner (or enough to enable APIs and create service accounts)
#
# Usage:
#   ./scripts/bootstrap-org-admin.sh PROJECT_ID [options]
#   just bootstrap-admin PROJECT_ID [options]
#
# Options:
#   --org-id ID               Organization ID (auto-detected from project ancestry)
#   --billing-account ID      Billing account ID, e.g. 0X0X0X-0X0X0X-0X0X0X
#                             (auto-detected if you have exactly one open account)
#   --sa-name NAME            Service account name (default: org-admin)
#   --key-out PATH            JSON key path
#                             (default: .cache/gcp-keys/<sa-name>-<project>.json)
#   --no-key                  Do not create a key (use impersonation instead)
#   --override-key-policy     Turn OFF the org policy that blocks SA key creation
#   --impersonator EMAIL      Also grant this user serviceAccountTokenCreator on the SA
#   --use-existing            Reuse the current gcloud session instead of a temp login
#   --keep-login              Keep the temporary CLOUDSDK_CONFIG directory
#   --no-browser              Use `gcloud auth login --no-launch-browser`
#   --no-verify               Skip the post-create credential check
#   --force                   Allow writing the key outside a gitignored path
#   -h, --help                Show this help
#
# When `gcloud` is missing the script re-executes itself in `nix develop .#cloud`
# (set PYTHON_TOFU_CLOUD_SHELL=1 to disable that and fail instead).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
ORIG_ARGS=("$@")

# ---------- defaults ----------
PROJECT_ID=""
ORG_ID=""
BILLING_ID=""
SA_NAME="org-admin"
KEY_OUT=""
CREATE_KEY=true
OVERRIDE_KEY_POLICY=false
IMPERSONATOR=""
USE_EXISTING=false
KEEP_LOGIN=false
NO_BROWSER=false
VERIFY=true
FORCE=false
TMP_CONFIG=""
KEY_CREATED=false

# Roles granted on the ORGANIZATION.
ORG_ROLES=(
  roles/orgpolicy.policyAdmin           # set/manage org policies
  roles/resourcemanager.projectCreator  # create projects
  roles/resourcemanager.folderAdmin     # create/manage folders
  roles/iam.securityAdmin               # set IAM policy on org/folders/projects
  roles/iam.serviceAccountAdmin         # create per-project service accounts
  roles/iam.serviceAccountKeyAdmin      # manage SA keys (if you allow them)
  roles/serviceusage.serviceUsageAdmin  # enable/disable APIs (apply + prune)
  roles/resourcemanager.projectDeleter  # delete projects (prune projects section)
)

# APIs enabled on the host project.
APIS=(
  iam.googleapis.com
  iamcredentials.googleapis.com
  cloudresourcemanager.googleapis.com
  orgpolicy.googleapis.com
  cloudbilling.googleapis.com
  serviceusage.googleapis.com
)

# ---------- helpers ----------
log()  { printf '\033[1;34m[*]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[+]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
bootstrap-org-admin.sh — create the org-level seed admin service account.

Usage:
  bootstrap-org-admin.sh PROJECT_ID [options]

Options:
  --org-id ID               Organization ID (auto-detected from project ancestry)
  --billing-account ID      Billing account ID (auto-detected if exactly one open)
  --sa-name NAME            Service account name (default: org-admin)
  --key-out PATH            JSON key path (default: .cache/gcp-keys/<sa>-<project>.json)
  --no-key                  Do not create a key (use --impersonator instead)
  --override-key-policy     Turn OFF the org policy that blocks SA key creation
  --impersonator EMAIL      Grant this user serviceAccountTokenCreator on the SA
  --use-existing            Reuse the current gcloud session instead of a temp login
  --keep-login              Keep the temporary CLOUDSDK_CONFIG directory
  --no-browser              Use `gcloud auth login --no-launch-browser`
  --no-verify               Skip the post-create credential check
  --force                   Allow writing the key outside a gitignored path
  -h, --help                Show this help

PROJECT_ID is the host project the service account is created in. It must sit
inside the organization that will receive the role bindings.
EOF
  exit "${1:-0}"
}

# retry <attempts> <sleep-seconds> <command...>
# IAM and org-policy changes are eventually consistent; a short retry loop is
# cheaper than telling the user to re-run a half-finished bootstrap.
retry() {
  local attempts=$1 delay=$2
  shift 2
  local n=1
  until "$@"; do
    if (( n >= attempts )); then return 1; fi
    warn "Attempt $n/$attempts failed, retrying in ${delay}s..."
    sleep "$delay"
    n=$((n + 1))
  done
}

# A failed `keys create` can leave a partial file behind, which would make the
# next attempt fail with "file exists". Remove it before every try.
create_key() {
  rm -f -- "$KEY_OUT"
  gcloud iam service-accounts keys create "$KEY_OUT" \
    --iam-account="$SA_EMAIL" --project="$PROJECT_ID" --quiet
}

cleanup() {
  local status=$?
  if [[ $status -ne 0 && $KEY_CREATED == true && -n $KEY_OUT ]]; then
    rm -f -- "$KEY_OUT" || true
    warn "Removed the partially created key: $KEY_OUT"
  fi
  if [[ -n $TMP_CONFIG && $KEEP_LOGIN == false ]]; then
    rm -rf -- "$TMP_CONFIG" || true
  fi
}
trap cleanup EXIT

ensure_gcloud() {
  if command -v gcloud >/dev/null 2>&1; then return; fi
  if [[ ${PYTHON_TOFU_CLOUD_SHELL:-} != 1 ]] \
     && command -v nix >/dev/null 2>&1 \
     && [[ -f $REPO_ROOT/flake.nix ]]; then
    log "gcloud not found on PATH; re-executing in 'nix develop .#cloud'..."
    export PYTHON_TOFU_CLOUD_SHELL=1
    exec nix develop "$REPO_ROOT#cloud" --command bash \
      "$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")" "${ORIG_ARGS[@]}"
  fi
  die "gcloud CLI not found. Enter the cloud shell first: nix develop .#cloud"
}

# ---------- parse args ----------
[[ $# -ge 1 ]] || usage 1
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)              usage 0 ;;
    --org-id)               ORG_ID="${2:?--org-id needs a value}"; shift 2 ;;
    --billing-account)      BILLING_ID="${2:?--billing-account needs a value}"; shift 2 ;;
    --sa-name)              SA_NAME="${2:?--sa-name needs a value}"; shift 2 ;;
    --key-out)              KEY_OUT="${2:?--key-out needs a value}"; shift 2 ;;
    --impersonator)         IMPERSONATOR="${2:?--impersonator needs a value}"; shift 2 ;;
    --no-key)               CREATE_KEY=false; shift ;;
    --override-key-policy)  OVERRIDE_KEY_POLICY=true; shift ;;
    --use-existing)         USE_EXISTING=true; shift ;;
    --keep-login)           KEEP_LOGIN=true; shift ;;
    --no-browser)           NO_BROWSER=true; shift ;;
    --verify)               VERIFY=true; shift ;;
    --no-verify)            VERIFY=false; shift ;;
    --force)                FORCE=true; shift ;;
    -*)                     die "Unknown option: $1" ;;
    *)
      [[ -z $PROJECT_ID ]] || die "Unexpected argument: $1"
      PROJECT_ID="$1"; shift ;;
  esac
done

[[ -n $PROJECT_ID ]] || die "PROJECT_ID is required"
[[ $SA_NAME =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] \
  || die "Invalid --sa-name '$SA_NAME' (6-30 chars, lowercase letters/digits/hyphens, starts with a letter)"
ensure_gcloud

# ---------- temporary gcloud login ----------
if [[ $USE_EXISTING == false ]]; then
  TMP_CONFIG="$(mktemp -d "${TMPDIR:-/tmp}/python-tofu-gcloud.XXXXXX")"
  export CLOUDSDK_CONFIG="$TMP_CONFIG"
  log "Temporary gcloud config: $TMP_CONFIG (discarded on exit)"
else
  log "Using the existing gcloud session"
fi
# Keep every gcloud call pointed at the target project even when .envrc has
# exported CLOUDSDK_CORE_PROJECT from the agenix service-account key.
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"

if [[ $USE_EXISTING == false ]]; then
  LOGIN_ARGS=()
  if [[ $NO_BROWSER == true || -z ${DISPLAY:-}${WAYLAND_DISPLAY:-} ]]; then
    LOGIN_ARGS+=(--no-launch-browser)
  fi
  log "Signing in with a temporary gcloud account (your normal session is untouched)..."
  gcloud auth login "${LOGIN_ARGS[@]}" || die "gcloud auth login failed"
fi

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1 || true)"
[[ -n $ACTIVE_ACCOUNT ]] || die "No active gcloud account. Run: gcloud auth login"
case "$ACTIVE_ACCOUNT" in
  *.gserviceaccount.com)
    warn "Active account is a service account ($ACTIVE_ACCOUNT); expected a human org admin." ;;
esac
log "Running as: $ACTIVE_ACCOUNT"

# ---------- preflight ----------
log "Checking access to project '$PROJECT_ID'..."
RESOLVED_PROJECT="$(gcloud projects describe "$PROJECT_ID" --format='value(projectId)' 2>/dev/null)" \
  || die "Cannot access project '$PROJECT_ID' (does it exist, and do you have access?)"
PROJECT_ID="$RESOLVED_PROJECT"
[[ -n $PROJECT_ID ]] || die "Could not resolve a canonical project ID for '$PROJECT_ID'"

# ---------- resolve organization ----------
if [[ -z $ORG_ID ]]; then
  log "Detecting organization from project ancestry..."
  if ! ORG_ID="$(gcloud projects get-ancestors "$PROJECT_ID" --format='value(id,type)' \
      | awk '$2 == "organization" { print $1; exit }')"; then
    die "Could not read the ancestry of '$PROJECT_ID' (missing resourcemanager.projects.get?)"
  fi
  [[ -n $ORG_ID ]] || die "Project '$PROJECT_ID' is not inside an organization. Pass --org-id, or check 'gcloud organizations list'."
else
  ORG_ID="${ORG_ID#organizations/}"
fi
[[ $ORG_ID =~ ^[0-9]+$ ]] || die "Organization ID must be numeric (got '$ORG_ID')"
ok "Organization: $ORG_ID"

# ---------- resolve billing account ----------
BILLING_ID="${BILLING_ID#billingAccounts/}"
if [[ -z $BILLING_ID ]]; then
  log "Detecting billing account..."
  mapfile -t ACCTS < <(gcloud billing accounts list --filter='open=true' \
    --format='value(name)' | sed 's#.*/##')
  if (( ${#ACCTS[@]} == 1 )); then
    BILLING_ID="${ACCTS[0]}"
  elif (( ${#ACCTS[@]} == 0 )); then
    die "No open billing accounts visible to '$ACTIVE_ACCOUNT'. Pass --billing-account."
  else
    die "Multiple open billing accounts found (${ACCTS[*]}). Pass --billing-account."
  fi
fi
ok "Billing account: $BILLING_ID"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if [[ -z $KEY_OUT ]]; then
  if [[ -f $REPO_ROOT/flake.nix ]]; then
    KEY_OUT="$REPO_ROOT/.cache/gcp-keys/${SA_NAME}-${PROJECT_ID}.json"
  else
    KEY_OUT="$PWD/${SA_NAME}-${PROJECT_ID}.json"
  fi
fi

# ---------- key path preflight (before mutating IAM) ----------
if [[ $CREATE_KEY == true ]]; then
  [[ ! -e $KEY_OUT ]] || die "Key file already exists: $KEY_OUT (move it or pass --key-out). Not overwriting."
  KEY_DIR="$(dirname -- "$KEY_OUT")"
  if [[ ! -d $KEY_DIR ]]; then
    mkdir -p -- "$KEY_DIR"
    chmod 700 -- "$KEY_DIR" 2>/dev/null || true
  fi

  if [[ $FORCE == false ]] && command -v git >/dev/null 2>&1 \
     && command -v realpath >/dev/null 2>&1 \
     && git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    KEY_ABS="$(realpath -m -- "$KEY_OUT")"
    case "$KEY_ABS" in
      "$REPO_ROOT"/*)
        KEY_REL="${KEY_ABS#"$REPO_ROOT"/}"
        if ! git -C "$REPO_ROOT" check-ignore -q -- "$KEY_REL"; then
          die "Refusing to write a service-account key to '$KEY_OUT' (not gitignored). Move it under .cache/ or pass --force."
        fi
        ;;
    esac
  fi
  ok "Key will be written to $KEY_OUT"
fi

# ---------- 1. link billing to the project ----------
CURRENT_BILLING="$(gcloud billing projects describe "$PROJECT_ID" \
  --format='value(billingAccountName)' 2>/dev/null | sed 's#.*/##' || true)"
if [[ $CURRENT_BILLING == "$BILLING_ID" ]]; then
  ok "Project already linked to billing account $BILLING_ID"
else
  log "Linking billing account to project..."
  gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ID" --quiet >/dev/null \
    || die "Failed to link billing (you need billing.admin on $BILLING_ID)"
  ok "Billing linked"
fi

# ---------- 2. enable APIs ----------
log "Enabling APIs on $PROJECT_ID (this can take a minute)..."
retry 3 10 gcloud services enable "${APIS[@]}" --project="$PROJECT_ID" --quiet >/dev/null \
  || die "Failed to enable APIs on $PROJECT_ID (needs serviceusage.services.enable)"
ok "APIs enabled"

# ---------- 3. create service account ----------
if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  ok "Service account already exists: $SA_EMAIL"
else
  log "Creating service account $SA_EMAIL..."
  gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" \
    --display-name="Org admin (seed) service account" \
    --description="Bootstrap SA with org-level admin roles. Handle with care." \
    --quiet >/dev/null \
    || die "Failed to create $SA_EMAIL"
  # SA creation is eventually consistent; wait until it is visible.
  retry 10 3 gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null \
    || die "Service account not visible after creation"
  ok "Service account created"
fi

# ---------- 4. grant org-level roles ----------
log "Granting organization-level roles..."
for role in "${ORG_ROLES[@]}"; do
  retry 5 5 gcloud organizations add-iam-policy-binding "$ORG_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet >/dev/null \
    || die "Failed to grant $role on organization $ORG_ID (do you have organizationAdmin?)"
  ok "  $role"
done

# Lets the SA use APIs with its host project as the quota project.
log "Granting serviceUsageConsumer on host project..."
retry 3 5 gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/serviceusage.serviceUsageConsumer" \
  --condition=None --quiet >/dev/null \
  || die "Failed to grant serviceUsageConsumer on $PROJECT_ID"
ok "  roles/serviceusage.serviceUsageConsumer (project)"

# ---------- 5. billing account permissions ----------
log "Granting billing permissions on billing account $BILLING_ID..."
gcloud billing accounts add-iam-policy-binding "$BILLING_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/billing.user" \
  --quiet >/dev/null \
  || die "Failed to grant billing.user (you need billing.admin on $BILLING_ID)"
ok "  roles/billing.user (billing account)"

# ---------- 6. optional: let a human impersonate the SA ----------
if [[ -n $IMPERSONATOR ]]; then
  MEMBER="$IMPERSONATOR"
  [[ $MEMBER == *:* ]] || MEMBER="user:${MEMBER}"
  log "Granting $MEMBER permission to impersonate the SA..."
  gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
    --project="$PROJECT_ID" \
    --member="$MEMBER" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --quiet >/dev/null \
    || die "Failed to grant serviceAccountTokenCreator to $MEMBER"
  ok "Impersonation granted"
fi

# ---------- 7. optional: disable the key-creation block ----------
if [[ $CREATE_KEY == true && $OVERRIDE_KEY_POLICY == true ]]; then
  log "Disabling the org policy that blocks service-account key creation..."
  POLICY_FILE="$(mktemp "${TMPDIR:-/tmp}/python-tofu-orgpolicy.XXXXXX.yaml")"
  # Orgs created after May 2024 enforce the legacy constraint by default; the
  # managed variant is newer. Try both and ignore constraints that do not exist.
  for constraint in \
    iam.disableServiceAccountKeyCreation \
    iam.managed.disableServiceAccountKeyCreation; do
    cat > "$POLICY_FILE" <<EOF
name: organizations/${ORG_ID}/policies/${constraint}
spec:
  rules:
  - enforce: false
EOF
    if gcloud org-policies set-policy "$POLICY_FILE" --quiet >/dev/null 2>&1; then
      ok "  $constraint -> not enforced"
    else
      warn "  could not set $constraint (needs orgpolicy.policyAdmin, or it does not apply)"
    fi
  done
  rm -f -- "$POLICY_FILE"
  log "Waiting for org policy to propagate..."
  sleep 20
fi

# ---------- 8. create the JSON key ----------
if [[ $CREATE_KEY == true ]]; then
  log "Creating JSON key -> $KEY_OUT"
  umask 077
  if retry 6 15 create_key; then
    chmod 600 -- "$KEY_OUT"
    KEY_CREATED=true
    ok "Key saved to $KEY_OUT (mode 600)"
  else
    rm -f -- "$KEY_OUT"
    warn "Key creation failed. Most likely the org policy still blocks it."
    warn "Re-run with --override-key-policy (needs orgpolicy.policyAdmin), or use --no-key --impersonator EMAIL."
    exit 2
  fi
fi

# ---------- 9. verify the credential ----------
if [[ $VERIFY == true && $CREATE_KEY == true ]]; then
  log "Verifying the key against organization $ORG_ID..."
  VERIFY_CONFIG="$(mktemp -d "${TMPDIR:-/tmp}/python-tofu-verify.XXXXXX")"
  if CLOUDSDK_CONFIG="$VERIFY_CONFIG" gcloud auth activate-service-account \
       --key-file="$KEY_OUT" --quiet >/dev/null 2>&1 \
     && retry 6 10 env CLOUDSDK_CONFIG="$VERIFY_CONFIG" \
          gcloud organizations get-iam-policy "$ORG_ID" --format='value(version)' >/dev/null; then
    ok "Key authenticates and can read the organization IAM policy"
    rm -rf -- "$VERIFY_CONFIG"
  else
    warn "Could not verify the key yet (IAM propagation can take a minute)."
    warn "Scratch config kept for a retry: CLOUDSDK_CONFIG=$VERIFY_CONFIG"
  fi
fi

# ---------- summary ----------
cat <<EOF

================ DONE ================
Service account : $SA_EMAIL
Organization    : $ORG_ID
Billing account : $BILLING_ID
Org roles       : ${ORG_ROLES[*]}
EOF

if [[ $CREATE_KEY == true ]]; then
  cat <<EOF
Key file        : $KEY_OUT
EOF
  cat <<EOF

Use the key with:
  gcloud auth activate-service-account --key-file="$KEY_OUT"
  export GOOGLE_APPLICATION_CREDENTIALS="$KEY_OUT"

This key is effectively ORG-ADMIN. Do not commit it. Store it in a secret
manager (agenix/sops) and rotate or delete it once impersonation is in place.
EOF
else
  cat <<EOF

Impersonate it from your normal session:
  gcloud auth login
  gcloud config set auth/impersonate_service_account $SA_EMAIL
  # OpenTofu: provider "google" { impersonate_service_account = "$SA_EMAIL" }
  # (your user needs roles/iam.serviceAccountTokenCreator on it; see --impersonator)
EOF
fi

if [[ $USE_EXISTING == false ]]; then
  cat <<EOF

The temporary login used for this run was discarded.
EOF
fi

if [[ -n $TMP_CONFIG && $KEEP_LOGIN == true ]]; then
  cat <<EOF

Temporary gcloud config kept at: $TMP_CONFIG
  CLOUDSDK_CONFIG=$TMP_CONFIG gcloud auth list
EOF
fi
