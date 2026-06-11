#!/usr/bin/env bash
# IndexNow bulk submitter for analook.com  (canonical host = www.analook.com)
# Pushes URLs to the IndexNow network (Bing, Yandex, Seznam) for near-instant indexing.
# Bing's index feeds ChatGPT Search / Copilot / Perplexity, so this also accelerates AI citations.
#
# Usage:
#   ./scripts/indexnow-submit.sh                 # submit every URL in the live sitemap
#   ./scripts/indexnow-submit.sh URL [URL ...]   # submit only the given URLs (e.g. just-changed pages)
#
# The IndexNow key is public by design (served at the keyLocation URL), so nothing secret lives here.
set -euo pipefail

HOST="www.analook.com"
KEY_LOCATION="https://www.analook.com/ceb743f3910e42b0ab39db1c7481abb8.txt"

KEY="$(curl -fsS --max-time 15 "$KEY_LOCATION" | tr -d '[:space:]')"
if [ -z "$KEY" ]; then echo "ERROR: could not read IndexNow key from $KEY_LOCATION" >&2; exit 1; fi

TMP="$(mktemp)"
if [ "$#" -gt 0 ]; then
  printf '%s\n' "$@" > "$TMP"
else
  curl -fsS --max-time 20 "https://$HOST/sitemap.xml" \
    | grep -oE '<loc>[^<]+</loc>' | sed -E 's#</?loc>##g' > "$TMP"
fi

COUNT="$(grep -c . "$TMP" || true)"
if [ "$COUNT" -eq 0 ]; then echo "No URLs to submit." >&2; exit 1; fi
echo "Submitting $COUNT URL(s) to IndexNow..."

PAYLOAD="$(python3 - "$KEY" "$KEY_LOCATION" "$HOST" "$TMP" <<'PY'
import json, sys
key, keyloc, host, path = sys.argv[1:5]
urls = [l.strip() for l in open(path) if l.strip()]
print(json.dumps({"host": host, "key": key, "keyLocation": keyloc, "urlList": urls}))
PY
)"

HTTP="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
  -X POST "https://api.indexnow.org/indexnow" \
  -H "Content-Type: application/json; charset=utf-8" \
  --data-binary "$PAYLOAD")"

rm -f "$TMP"
echo "IndexNow response: HTTP $HTTP"
case "$HTTP" in
  200|202) echo "OK — accepted." ;;
  *) echo "WARNING: unexpected status (400=bad request, 403=key mismatch, 422=invalid URLs, 429=rate limited)" >&2; exit 1 ;;
esac
