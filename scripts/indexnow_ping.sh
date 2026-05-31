#!/usr/bin/env bash
# IndexNow ping for analook.com
#
# Pushes new/updated URLs to Bing + IndexNow protocol partners (also picked up
# by Yandex, Seznam, and increasingly by AI search engines that crawl Bing's index).
#
# Usage:
#   ./scripts/indexnow_ping.sh <url1> [url2 ...]
#
# Examples:
#   ./scripts/indexnow_ping.sh https://www.analook.com/
#   ./scripts/indexnow_ping.sh \
#     https://www.analook.com/compare/similarweb.html \
#     https://www.analook.com/comparison.html
#
# When to run:
#   - After publishing a new /blog/ post
#   - After major edits to /compare/*.html or /alternatives/*.html
#   - After sitemap.xml is updated
#   - NOT on every push (rate-limit yourself: max ~10 URLs per day for the same site)

set -euo pipefail

KEY="ceb743f3910e42b0ab39db1c7481abb8"
HOST="www.analook.com"
KEY_LOCATION="https://www.analook.com/${KEY}.txt"

if [ $# -eq 0 ]; then
  cat <<EOF
Usage: $0 <url1> [url2 ...]

Pings IndexNow with the given URLs.

Examples:
  $0 https://www.analook.com/
  $0 https://www.analook.com/compare/similarweb.html https://www.analook.com/comparison.html

The IndexNow key file at $KEY_LOCATION must remain accessible (it proves ownership).
EOF
  exit 1
fi

# Build JSON array of URLs
URLS=""
for url in "$@"; do
  if [ -n "$URLS" ]; then URLS="${URLS},"; fi
  URLS="${URLS}\"${url}\""
done

PAYLOAD=$(cat <<EOF
{
  "host": "${HOST}",
  "key": "${KEY}",
  "keyLocation": "${KEY_LOCATION}",
  "urlList": [${URLS}]
}
EOF
)

echo "IndexNow payload:"
echo "$PAYLOAD" | python3 -m json.tool 2>/dev/null || echo "$PAYLOAD"
echo

# Submit to both endpoints — IndexNow protocol shares submissions across partners,
# but explicit submission to multiple endpoints is faster and more reliable.
for endpoint in "https://api.indexnow.org/indexnow" "https://www.bing.com/indexnow"; do
  echo "→ POST $endpoint"
  curl -sS -o /tmp/indexnow_response.txt -w "  HTTP %{http_code} | time=%{time_total}s\n" \
    -X POST "$endpoint" \
    -H "Content-Type: application/json; charset=utf-8" \
    -H "User-Agent: analook-indexnow/1.0" \
    -d "$PAYLOAD" || echo "  (request failed)"
  if [ -s /tmp/indexnow_response.txt ]; then
    echo "  Response: $(cat /tmp/indexnow_response.txt | head -c 200)"
  fi
done

echo
echo "Done. Note: 200/202 = accepted. 422 = invalid URL. 429 = rate limited."
