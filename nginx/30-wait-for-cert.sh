#!/bin/sh
# Wait for certbot to fetch the HTTPS certificate before nginx starts (first run only)
CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
if [ -z "${DOMAIN}" ]; then
  echo "comp-history: DOMAIN isn't set. Put it in the .env file and run: docker compose up -d" >&2
  exit 1
fi
n=0
while [ ! -f "$CERT" ]; do
  [ $((n % 12)) -eq 0 ] && echo "comp-history: waiting for the HTTPS certificate for ${DOMAIN} (the certbot container is getting it)..."
  n=$((n + 1))
  sleep 5
done
echo "comp-history: certificate found for ${DOMAIN}"
