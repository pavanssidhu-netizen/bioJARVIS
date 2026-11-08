#!/usr/bin/env bash
# Build + deploy LABMATE to a Vercel PREVIEW deployment (protected by Vercel Authentication), then verify
# that an anonymous request is DENIED before printing the URL.
#   Prereqs (once): npx vercel login ; TURSO_* and GEMINI_API_KEY in .env ; scripts/deploy_vercel.sh --sync-env
set -euo pipefail
cd "$(dirname "$0")/.."
VERCEL="npx --yes --registry https://registry.npmjs.org vercel@65.12.1"

if [[ "${1:-}" == "--sync-env" ]]; then
  # Push server-side secrets to the Vercel project's *preview* environment without echoing them.
  exec .venv/bin/python scripts/vercel_env_sync.py
fi

grep -qE '^TURSO_DATABASE_URL=.+' .env || { echo "TURSO_DATABASE_URL missing in .env: Vercel has no persistent disk"; exit 1; }

scripts/build_web.sh >/dev/null
rm -rf public && cp -r app/build/web public

# Hard guard: refuse to publish if the Gemini key (or any key-shaped string) is in the static files.
KEY=$(grep -E '^GEMINI_API_KEY=' .env | cut -d= -f2-)
if { [[ -n "$KEY" ]] && grep -rqF -- "$KEY" public; } || grep -rqE 'AIza[0-9A-Za-z_-]{30,}' public; then
  echo "STOP: API key material found in public/ - not deploying."; rm -rf public; exit 1
fi
[[ -e public/.env ]] && { echo "STOP: .env in public/"; exit 1; }

URL=$($VERCEL deploy --yes 2>/dev/null | tail -1) || true   # preview (NOT --prod): covered by deployment protection
echo "Deployed: $URL"
state=$($VERCEL inspect "$URL" 2>&1 | grep -m1 -E '^\s+status' | awk '{print $NF}' || true)
[[ "$state" == "Ready" ]] || { echo "Deployment not ready (status: $state). Logs: $VERCEL inspect $URL --logs"; exit 1; }

code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/api/health")
hdr=$(curl -sI "$URL/api/health" | tr -d '\r' | grep -iE '^(location|set-cookie|www-authenticate|x-vercel)' | head -3 || true)
if [[ "$code" == "401" || "$code" == "403" || "$code" == "302" ]] && grep -qiE 'vercel|sso|_vercel' <<<"$hdr"; then
  echo "OK: anonymous request denied by Vercel Authentication ($code)."
  # Stable URL: move the fixed alias to this (protected) preview deployment, then re-verify protection on the alias.
  ALIAS="${LARVIS_ALIAS:-larvis-demo.vercel.app}"
  $VERCEL alias set "$URL" "$ALIAS" >/dev/null 2>&1 || { echo "alias failed; use $URL"; exit 0; }
  acode=$(curl -s -o /dev/null -w '%{http_code}' "https://$ALIAS/api/health")
  if [[ "$acode" == "302" || "$acode" == "401" || "$acode" == "403" ]]; then
    echo "Stable protected URL (sign in to Vercel once): https://$ALIAS"
  else
    echo "WARNING: alias https://$ALIAS returned $acode anonymously - not protected; removing alias"
    $VERCEL alias rm "$ALIAS" --yes >/dev/null 2>&1 || true
  fi
  echo "This deployment: $URL"
else
  echo "STOP: anonymous request returned $code - deployment is NOT protected."
  echo "Enable Vercel Authentication (Project > Settings > Deployment Protection) and redeploy."
  echo "Removing the unprotected deployment..."
  $VERCEL remove "$URL" --yes >/dev/null 2>&1 || true
  exit 1
fi
