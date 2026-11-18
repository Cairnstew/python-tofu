#!/usr/bin/env bash
# Live end-to-end test of the NixOS module against real GCP.
#
# Builds the `tofu-live` system from nix/live-vm.nix, boots it under QEMU and
# lets `python-tofu.service` run a real `apply` at activation — the same code
# path as `nixos-rebuild switch`. No stub binary, no mocked `tofu`.
#
#   ./scripts/live-module-vm.sh            # build, boot, verify
#   ./scripts/live-module-vm.sh --destroy  # delete the created resources
#
# The target is the throwaway project in nix/live-vm-stack.nix; the host
# project is never touched. Requirements:
#
#   - /dev/kvm
#   - /run/agenix/gcloud-auth. It is copied to a 0400 file in the run directory
#     (removed on exit) and shared into the VM as /run/agenix; the real agenix
#     directory is `drwxr-x--x root:keys`, which QEMU cannot open as a 9p source.
#   - outbound network from QEMU user-mode networking
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

project=pt-live-0361f9
bucket=pt-live-0361f9-livevm
account=livevm-runtime
run_dir=$(realpath -m "${RUN_DIR:-.tofu/live-vm}")
workdir="$run_dir/workdir"
log="$run_dir/console.log"

mkdir -p "$run_dir"

stack_json=$(nix build .#live-stack --print-out-paths --no-link)

cloud() {
  local mode=$1
  PYTHONPATH="$repo_root/src" python3 - "$project" "$bucket" "$account" "$mode" <<'PY'
import json
import sys
import urllib.error
import urllib.request

from python_tofu.providers.gcp.live import access_token_for, get_json, post_json
from python_tofu.providers.gcp.prune import get_project_iam_bindings

project, bucket, account, mode = sys.argv[1:5]
token = access_token_for("/run/agenix/gcloud-auth")
email = f"{account}@{project}.iam.gserviceaccount.com"
member = f"serviceAccount:{email}"
headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
bucket_url = f"https://storage.googleapis.com/storage/v1/b/{bucket}"
account_url = f"https://iam.googleapis.com/v1/projects/{project}/serviceAccounts/{email}"
policy_url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}"


def call(method: str, url: str, body: dict | None = None) -> dict | None:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def delete_binding() -> bool:
    policy = post_json(f"{policy_url}:getIamPolicy", token, {"options": {"requestedPolicyVersion": 3}})
    changed = False
    for item in policy.get("bindings", []):
        if item.get("role") == "roles/viewer" and member in item.get("members", []):
            item["members"] = [value for value in item["members"] if value != member]
            changed = True
    policy["bindings"] = [item for item in policy.get("bindings", []) if item.get("members")]
    if changed:
        post_json(f"{policy_url}:setIamPolicy", token, {"policy": policy})
    return changed


if mode == "reset":
    # Make the run repeatable: a previous failed apply leaks resources because
    # the VM state is thrown away. Only these test-specific names are touched.
    if delete_binding():
        print(f"  removed IAM roles/viewer for {email}")
    if call("DELETE", account_url) is not None:
        print(f"  deleted service account {email}")
    if call("DELETE", bucket_url) is not None:
        print(f"  deleted bucket {bucket}")
    raise SystemExit(0)

bucket_data = None
try:
    bucket_data = get_json(bucket_url, token, {})
except Exception:  # a 404 is the "absent" signal we are looking for
    pass
account_data = None
try:
    account_data = get_json(account_url, token, {})
except Exception:
    pass
binding = any(
    item.get("role") == "roles/viewer" and member in item.get("members", [])
    for item in get_project_iam_bindings(project, token)
)

problems = []
for label, present in {
    f"bucket {bucket}": bucket_data is not None,
    f"service account {email}": account_data is not None,
    f"IAM roles/viewer for {email}": binding,
}.items():
    if mode == "present" and not present:
        problems.append(f"missing {label}")
    elif mode == "absent" and present:
        problems.append(f"still present: {label}")
    else:
        print(f"  {label}: {'present' if present else 'absent'}")

if problems:
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    raise SystemExit(1)
PY
}

if [ "${1:-}" = "--destroy" ]; then
  if [ ! -s "$workdir/terraform.tfstate" ]; then
    echo "no state in $workdir; nothing to destroy" >&2
    exit 1
  fi
  echo "==> destroying the live-module resources"
  nix run .#with-tofu -- destroy \
    --config "$stack_json" \
    --workdir "$workdir" \
    --auto-approve
  cloud absent
  exit 0
fi

echo "==> building the live NixOS system"
nix build .#nixosConfigurations.tofu-live.config.system.build.vm -o "$run_dir/vm"

if [ ! -r /run/agenix/gcloud-auth ]; then
  echo "missing /run/agenix/gcloud-auth" >&2
  exit 1
fi

# QEMU's 9p backend must be able to open the directory it serves, and agenix
# keeps secrets in `drwxr-x--x root:keys` directories. Share a private copy so
# the guest still sees the path the stack declares; remove it on exit.
cred_dir="$run_dir/credential"
rm -rf "$cred_dir"
install -d -m 0700 "$cred_dir"
install -m 0400 /run/agenix/gcloud-auth "$cred_dir/gcloud-auth"
trap 'rm -rf "$cred_dir"' EXIT
export LIVE_VM_CRED_DIR="$cred_dir"

vm=$(find "$run_dir/vm/bin" -maxdepth 1 -name 'run-*-vm' -print -quit)
if [ -z "$vm" ]; then
  echo "no run-*-vm script in $run_dir/vm/bin" >&2
  exit 1
fi

# Start from a clean workdir: a fresh state is what makes the VM create the
# resources instead of colliding with anything the host rendered before.
rm -rf "$workdir"
mkdir -p "$workdir"
export LIVE_VM_WORKDIR="$workdir"

echo "==> resetting leftovers from an earlier run"
cloud reset

echo "==> booting (serial console: $log)"
: >"$log"
# The run script resolves a relative disk image against the caller's cwd; keep
# the generated qcow2 inside the run directory instead of the repo root.
export NIX_DISK_IMAGE="$run_dir/disk.qcow2"
set +e
# Redirect rather than pipe: `-nographic` uses stdio, and a pipe/EOF makes QEMU
# exit before the guest boots.
timeout --foreground "${LIVE_VM_TIMEOUT:-1200}" "$vm" >"$log" 2>&1
status=$?
set -e

if [ "$status" = "124" ]; then
  echo "FAIL: the VM did not stop within ${LIVE_VM_TIMEOUT:-1200}s" >&2
  tail -n 40 "$log" >&2
  exit 1
fi
if [ "$status" != "0" ]; then
  echo "FAIL: qemu exited with status $status" >&2
  tail -n 40 "$log" >&2
  exit 1
fi
if ! grep -q "LIVE-VM result=success" "$log"; then
  echo "FAIL: python-tofu.service did not succeed (see $log)" >&2
  exit 1
fi
if ! grep -q "Apply complete" "$log"; then
  echo "FAIL: no 'Apply complete' in the VM console (see $log)" >&2
  exit 1
fi

echo "==> verifying cloud state from the host"
cloud present

cat <<EOF

Live module test passed. The infrastructure is still up:
  bucket          gs://$bucket
  service account $account@$project.iam.gserviceaccount.com

State and rendered HCL: $workdir
Clean up with:          ./scripts/live-module-vm.sh --destroy
EOF
