#!/usr/bin/env bash
# Discord LLM Connector // by:buf0rd
# One installer. Ollama or Open WebUI. Tavily or SearXNG for explicit web searches.
set -Eeuo pipefail
connector_source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
connector_reconfigure=0
connector_test_only=0
for connector_argument in "$@"; do
  case "$connector_argument" in
    --reconfigure) connector_reconfigure=1 ;;
    --test-only) connector_test_only=1 ;;
    --help|-h)
      echo 'Usage: sudo bash install.sh [--reconfigure]'
      echo 'Local tests only: bash install.sh --test-only'
      exit 0 ;;
    *) echo "Unknown argument: $connector_argument" >&2; exit 1 ;;
  esac
done
if [[ "$connector_test_only" -eq 0 && "$EUID" -ne 0 ]]; then
  echo 'Run with sudo. The service itself runs as discord-llm, not root.' >&2
  exit 1
fi
umask 077
connector_stage=$(mktemp -d /tmp/discord-connector.XXXXXXXX)
connector_restore_runtime=0
export CONNECTOR_WAS_ACTIVE=0
connector_cleanup() {
  connector_exit_code=$?
  trap - EXIT
  if [[ "$connector_exit_code" -ne 0 && "$connector_restore_runtime" -eq 1 && "$CONNECTOR_WAS_ACTIVE" -eq 1 ]]; then
    systemctl start discord-llm || true
  fi
  rm -rf -- "$connector_stage"
  exit "$connector_exit_code"
}
trap connector_cleanup EXIT
install -m 600 "$connector_source_dir/src/settings.py" "$connector_stage/settings.py"
install -m 600 "$connector_source_dir/src/backend.py" "$connector_stage/backend.py"
install -m 600 "$connector_source_dir/src/bot.py" "$connector_stage/bot.py"
install -m 600 "$connector_source_dir/src/websearch.py" "$connector_stage/websearch.py"
install -m 600 "$connector_source_dir/src/configure.py" "$connector_stage/configure.py"
install -m 600 "$connector_source_dir/src/install.py" "$connector_stage/install.py"
install -m 600 "$connector_source_dir/systemd/discord-llm.service" "$connector_stage/discord-llm.service"
install -m 600 "$connector_source_dir/README.md" "$connector_stage/README.md"
install -m 600 "$connector_source_dir/tools/patch_bot.py" "$connector_stage/patch_bot.py"
install -m 600 "$connector_source_dir/tests/test_original.py" "$connector_stage/test_original.py"
install -m 600 "$connector_source_dir/tests/test_search.py" "$connector_stage/test_search.py"
install -m 600 "$connector_source_dir/tests/test_setup.py" "$connector_stage/test_setup.py"
install -m 600 "$connector_source_dir/tests/test_tavily.py" "$connector_stage/test_tavily.py"

# --test-only uses mock HTTP endpoints. No Discord messages or external search requests.
if [[ "$connector_test_only" -eq 1 ]]; then
  connector_python=python3
  if [[ -x /opt/discord-llm/venv/bin/python ]]; then
    connector_python=/opt/discord-llm/venv/bin/python
  fi
  "$connector_python" -m unittest discover -s "$connector_stage" -p 'test_*.py' -v
  exit 0
fi
command -v apt-get >/dev/null || { echo 'This installer needs Ubuntu/Debian.' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'Run this on a host with systemd.' >&2; exit 1; }
if systemctl is-active --quiet discord-llm; then
  export CONNECTOR_WAS_ACTIVE=1
fi
# Install the runtime. No apt upgrade, no model downloads, no vhost changes.
apt-get update
apt-get install -y python3 python3-venv ca-certificates
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required."'
if ! id discord-llm >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/discord-llm --shell /usr/sbin/nologin discord-llm
fi
install -d -o root -g root -m 755 /opt/discord-llm
install -d -o root -g discord-llm -m 750 /etc/discord-llm
install -d -o discord-llm -g discord-llm -m 700 /var/lib/discord-llm
if [[ ! -x /opt/discord-llm/venv/bin/python ]]; then
  python3 -m venv /opt/discord-llm/venv
fi
connector_python=/opt/discord-llm/venv/bin/python
# Leave an already-working environment alone. Install missing supported dependencies.
if ! "$connector_python" -c 'import discord, aiohttp, nacl, davey; from packaging.version import Version; assert Version("2.4") <= Version(discord.__version__) < Version("3"); assert Version("3.10") <= Version(aiohttp.__version__) < Version("4")' >/dev/null 2>&1; then
  connector_restore_runtime=1
  if [[ "$CONNECTOR_WAS_ACTIVE" -eq 1 ]]; then
    systemctl stop discord-llm
  fi
  "$connector_python" -m pip install --disable-pip-version-check -r "$connector_source_dir/requirements.txt"
  if [[ "$CONNECTOR_WAS_ACTIVE" -eq 1 ]]; then
    systemctl start discord-llm
  fi
  connector_restore_runtime=0
fi
"$connector_python" -m pip freeze > /opt/discord-llm/installed-requirements.txt
"$connector_python" -m unittest discover -s "$connector_stage" -p 'test_*.py' -v
# Keep existing credentials on a normal rerun. Use --reconfigure to change them.
if [[ -f /etc/discord-llm/config.json && "$connector_reconfigure" -eq 0 ]]; then
  "$connector_python" "$connector_stage/configure.py" --keep-existing --output "$connector_stage/ready-config.json"
else
  "$connector_python" "$connector_stage/configure.py" --output "$connector_stage/ready-config.json"
fi
# The installer now owns rollback of managed source, config, and service files.
connector_restore_runtime=0
"$connector_python" "$connector_stage/install.py"
