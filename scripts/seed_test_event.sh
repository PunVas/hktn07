#!/usr/bin/env bash
#
# seed_test_event.sh
# Send a sample SCM event to trigger PR analysis.
# Usage: ./scripts/seed_test_event.sh [pr_number] [repository]
#

set -euo pipefail

BASE_URL="${PR_GUARDIAN_URL:-http://localhost:8000}"
PR_NUMBER="${1:-119080}"
REPOSITORY="${2:-myorg/myrepo}"

echo "Sending SCM event for PR #${PR_NUMBER} in ${REPOSITORY}..."

curl -s -X POST "${BASE_URL}/api/events/scm" \
  -H "Content-Type: application/json" \
  -d "{
    \"provider\": \"harness\",
    \"event\": \"pr.opened\",
    \"repository\": \"${REPOSITORY}\",
    \"metadata\": {
      \"pr_number\": ${PR_NUMBER},
      \"action\": \"opened\"
    }
  }" | python3 -m json.tool

echo ""
echo "Check job status:"
echo "  GET ${BASE_URL}/api/pr/${PR_NUMBER}"
