#!/bin/sh
# Reload nginx every 6 hours so renewed certificates are picked up
( while :; do sleep 21600; nginx -s reload; done ) &
