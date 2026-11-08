#!/usr/bin/env bash
# Create a Vultr cloud instance and ship The Gilded Ace Streamlit app.
# Usage:
#   export VULTR_API_KEY=...
#   ./scripts/vultr_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/deploy/state"
BIN="$ROOT/deploy/bin"
mkdir -p "$STATE" "$BIN"

API="${VULTR_API_KEY:-${VULTR_API_TOKEN:-}}"
if [[ -z "$API" ]]; then
  echo "Set VULTR_API_KEY first (Account → API → Enable API on my.vultr.com)." >&2
  exit 1
fi
export VULTR_API_KEY="$API"

os="$(uname -s)-$(uname -m)"
case "$os" in
  Darwin-arm64) asset="vultr-cli_v3.11.0_macOs_arm64.tar.gz" ;;
  Darwin-x86_64) asset="vultr-cli_v3.11.0_macOs_amd64.tar.gz" ;;
  Linux-x86_64) asset="vultr-cli_v3.11.0_linux_amd64.tar.gz" ;;
  Linux-aarch64) asset="vultr-cli_v3.11.0_linux_arm64.tar.gz" ;;
  *) echo "Unsupported OS/arch: $os" >&2; exit 1 ;;
esac

CLI="$BIN/vultr-cli"
if [[ ! -x "$CLI" ]]; then
  echo "Installing vultr-cli…"
  curl -fsSL "https://github.com/vultr/vultr-cli/releases/download/v3.11.0/$asset" -o "$BIN/cli.tgz"
  tar -xzf "$BIN/cli.tgz" -C "$BIN"
  rm -f "$BIN/cli.tgz"
  chmod +x "$CLI"
fi

KEY_PATH="$STATE/id_ed25519"
if [[ ! -f "$KEY_PATH" ]]; then
  ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "gilded-ace-vultr"
fi
PUB="$(cat "${KEY_PATH}.pub")"

echo "Ensuring SSH key is registered with Vultr…"
KEY_ID=""
while IFS= read -r line; do
  if [[ "$line" == *"$PUB"* ]] || [[ "$line" == *"gilded-ace"* ]]; then
    KEY_ID="$(echo "$line" | awk '{print $1}')"
    break
  fi
done < <("$CLI" ssh-key list 2>/dev/null || true)

if [[ -z "$KEY_ID" ]]; then
  "$CLI" ssh-key create --name "gilded-ace" --key "$PUB" >/dev/null
  sleep 1
  KEY_ID="$("$CLI" ssh-key list | awk 'NR>1 && /gilded-ace/ {print $1; exit}')"
fi
if [[ -z "$KEY_ID" ]]; then
  echo "Could not register SSH key with Vultr." >&2
  exit 1
fi
echo "SSH key id: $KEY_ID"

REGION="${VULTR_REGION:-ewr}"
PLAN="${VULTR_PLAN:-vc2-1c-2gb}"
OS_ID="${VULTR_OS_ID:-2284}" # Ubuntu 24.04 x64 (confirm via vultr-cli os list)

INSTANCE_ID=""
if [[ -f "$STATE/instance_id" ]]; then
  INSTANCE_ID="$(cat "$STATE/instance_id")"
  echo "Reusing instance $INSTANCE_ID"
else
  echo "Creating Vultr instance ($PLAN in $REGION)…"
  CREATE_OUT="$("$CLI" instance create \
    --region "$REGION" \
    --plan "$PLAN" \
    --os "$OS_ID" \
    --label "gilded-ace" \
    --host "gilded-ace" \
    --ssh-keys "$KEY_ID" \
    --tags "gilded-ace,datathon")"
  echo "$CREATE_OUT"
  INSTANCE_ID="$(echo "$CREATE_OUT" | awk '/^ID/{print $2; exit}')"
  if [[ -z "$INSTANCE_ID" ]]; then
    INSTANCE_ID="$(echo "$CREATE_OUT" | awk 'NR==2 {print $1; exit}')"
  fi
  if [[ -z "$INSTANCE_ID" ]]; then
    echo "Failed to parse instance id." >&2
    exit 1
  fi
  echo "$INSTANCE_ID" > "$STATE/instance_id"
fi

echo "Waiting for instance to become active…"
IP=""
for _ in $(seq 1 60); do
  INFO="$("$CLI" instance get "$INSTANCE_ID")"
  STATUS="$(echo "$INFO" | awk '/^STATUS/{print $2; exit}')"
  IP="$(echo "$INFO" | awk '/^MAIN IP/{print $3; exit}')"
  if [[ -z "$IP" ]]; then
    IP="$(echo "$INFO" | awk '/MAIN IP/{print $NF; exit}')"
  fi
  echo "  status=$STATUS ip=${IP:-pending}"
  if [[ "$STATUS" == "active" && -n "$IP" && "$IP" != "0.0.0.0" ]]; then
    break
  fi
  sleep 5
done
if [[ -z "$IP" || "$IP" == "0.0.0.0" ]]; then
  echo "Instance did not become ready in time." >&2
  exit 1
fi
echo "$IP" > "$STATE/ip"

SSH=(ssh -i "$KEY_PATH" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes root@"$IP")
echo "Waiting for SSH on $IP…"
for _ in $(seq 1 36); do
  if "${SSH[@]}" "echo ok" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
"${SSH[@]}" "echo ssh-ready"

echo "Syncing app to /opt/gilded-ace…"
"${SSH[@]}" "mkdir -p /opt/gilded-ace"
RSYNC_SSH="ssh -i $KEY_PATH -o StrictHostKeyChecking=accept-new"
rsync -az --delete \
  -e "$RSYNC_SSH" \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude 'data/3_guests' \
  --exclude 'data/4_context' \
  --exclude 'data/5_optional' \
  --exclude 'data/**/*.csv.gz' \
  --exclude 'deploy/bin' \
  --exclude 'deploy/state' \
  --exclude '.DS_Store' \
  "$ROOT/" root@"$IP":/opt/gilded-ace/

echo "Installing and starting Streamlit…"
"${SSH[@]}" "bash /opt/gilded-ace/deploy/remote-setup.sh"

URL="http://${IP}:8501"
echo "$URL" > "$STATE/url"
echo
echo "Deployed on Vultr."
echo "Public URL: $URL"
echo "Instance:   $INSTANCE_ID"
echo "SSH:        ssh -i $KEY_PATH root@$IP"
