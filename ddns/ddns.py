#!/usr/bin/env python3
"""
Keeps your subdomain pointed at your home internet address.

Home internet addresses change now and then. Every few minutes this checks your current public address
and, if it's different from what Cloudflare has, updates the subdomain's A record. If the record doesn't
exist yet, it creates it ("DNS only", not proxied).

Settings come from the .env file: DOMAIN, CF_API_TOKEN, and optionally CF_ZONE_ID and DDNS_INTERVAL.
Uses only Python's standard library.
"""
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.cloudflare.com/client/v4"
TRACE_URL = "https://1.1.1.1/cdn-cgi/trace"   # Cloudflare's "what's my address" page


def setting(name, default=""):
    return (os.environ.get(name) or default).strip().strip('"').strip("'")


TOKEN = setting("CF_API_TOKEN")
NAME = setting("DOMAIN").lower().rstrip(".")
ZONE_ID = setting("CF_ZONE_ID") or None
try:
    INTERVAL = max(60, int(setting("DDNS_INTERVAL", "300")))
except ValueError:
    INTERVAL = 300


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


class CloudflareError(Exception):
    pass


def cf(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.load(exc)
        except ValueError:
            raise CloudflareError(f"HTTP {exc.code}") from None
    if not payload.get("success"):
        msgs = "; ".join(e.get("message", "?") for e in payload.get("errors") or []) or "unknown error"
        raise CloudflareError(msgs)
    return payload["result"]


def public_ip():
    with urllib.request.urlopen(TRACE_URL, timeout=15) as resp:
        text = resp.read().decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("ip="):
            ip = ipaddress.ip_address(line[3:].strip())
            if ip.version == 4:
                return str(ip)
    raise RuntimeError("couldn't read this connection's public IPv4 address")


def find_zone():
    """The zone is the registered domain: try stats.example.com, then example.com, ..."""
    if ZONE_ID:
        return ZONE_ID
    labels = NAME.split(".")
    for i in range(len(labels) - 1):
        candidate = ".".join(labels[i:])
        result = cf("GET", "/zones?" + urllib.parse.urlencode({"name": candidate}))
        if result:
            return result[0]["id"]
    raise CloudflareError(f"no Cloudflare zone found for {NAME}. Add CF_ZONE_ID to .env "
                          "(it's on your domain's Overview page in Cloudflare).")


def main():
    if not TOKEN or not NAME or "." not in NAME:
        log("DOMAIN and CF_API_TOKEN need to be set in the .env file. Waiting an hour before trying again.")
        time.sleep(3600)
        sys.exit(1)
    log(f"Keeping {NAME} pointed at this connection (checking every {INTERVAL // 60} min)")
    zone, last_ip, warned_proxied = None, None, False
    while True:
        try:
            zone = zone or find_zone()
            ip = public_ip()
            if ip != last_ip:
                query = urllib.parse.urlencode({"type": "A", "name": NAME})
                records = cf("GET", f"/zones/{zone}/dns_records?{query}")
                if not records:
                    cf("POST", f"/zones/{zone}/dns_records",
                       {"type": "A", "name": NAME, "content": ip, "ttl": 300, "proxied": False})
                    log(f"Created {NAME} -> {ip}")
                else:
                    rec = records[0]
                    if rec["content"] != ip:
                        cf("PATCH", f"/zones/{zone}/dns_records/{rec['id']}", {"content": ip})
                        log(f"Updated {NAME}: {rec['content']} -> {ip}")
                    else:
                        log(f"{NAME} already points to {ip}")
                    if rec.get("proxied") and not warned_proxied:
                        log("Note: this record is proxied (orange cloud) in Cloudflare. The setup guide "
                            "recommends DNS only (grey cloud).")
                        warned_proxied = True
                last_ip = ip
        except CloudflareError as exc:
            hint = ""
            if "auth" in str(exc).lower() or "token" in str(exc).lower():
                hint = " Check CF_API_TOKEN in .env (it needs Zone > DNS > Edit for your domain)."
            log(f"Cloudflare said: {exc}.{hint}")
        except Exception as exc:  # network hiccups: try again next round
            log(f"Couldn't check or update the address this time ({exc}). Will retry.")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
