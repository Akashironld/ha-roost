#!/bin/sh
# What GitHub CI checks, locally: lint, types, the tests (pure and inside Home Assistant), the card, hassfest (in
# docker) and the closed-loop simulation against its baseline.
#   tools/ci_local.sh            everything
#   tools/ci_local.sh quick      without hassfest and the simulation
# Environment:
#   ROOST_VENV       a virtualenv with requirements_test.txt (default: .venv in the repository)
#   ROOST_DOCKER_CT  run hassfest's docker inside this Proxmox container (pct) instead of the local docker
set -e
cd "$(dirname "$0")/.."
V=${ROOST_VENV:-.venv}/bin
MYPY_MAX=0              # the type checker finds nothing; keep it so
echo "== ruff";   $V/ruff check custom_components tools/sim --select F,E9,B,I001
echo "== mypy";   n=$($V/mypy custom_components/roost --ignore-missing-imports --no-error-summary 2>&1 | grep -c ": error:" || true)
echo "$n findings (max $MYPY_MAX)"; [ "$n" -le "$MYPY_MAX" ]
echo "== pure tests"; for t in tests/test_*.py; do python3 "$t" | tail -1; done
echo "== pytest";  $V/python -m pytest -q -p no:cacheprovider -p no:logging tests 2>/dev/null | tail -1
echo "== card";    node --check custom_components/roost/frontend/roost-card.js && node --test tests/frontend_savings.test.mjs tests/frontend_card.test.mjs 2>&1 | grep -E "^# (pass|fail)"
[ "$1" = quick ] && exit 0
echo "== hassfest"
if [ -n "$ROOST_DOCKER_CT" ]; then
  tar czf /tmp/roost-hassfest.tgz custom_components hacs.json
  pct push "$ROOST_DOCKER_CT" /tmp/roost-hassfest.tgz /tmp/roost-hassfest.tgz && rm /tmp/roost-hassfest.tgz
  pct exec "$ROOST_DOCKER_CT" -- sh -c 'rm -rf /tmp/hassfest && mkdir -p /tmp/hassfest && tar xzf /tmp/roost-hassfest.tgz -C /tmp/hassfest &&
    docker run --rm -v /tmp/hassfest:/github/workspace ghcr.io/home-assistant/hassfest 2>&1 | tail -2; rm -rf /tmp/hassfest /tmp/roost-hassfest.tgz'
else
  docker run --rm -v "$PWD":/github/workspace ghcr.io/home-assistant/hassfest 2>&1 | tail -2
fi
echo "== simulation";  $V/python tools/sim/regress.py
