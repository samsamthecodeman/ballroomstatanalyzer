# Hosting Ballroom Stats Analyzer on your Windows PC

This runs the site on your PC in Docker and makes it reachable at your subdomain, with HTTPS, through
your router. Four containers work together:

| Container | Job |
| --- | --- |
| **app** | The Ballroom Stats Analyzer site itself |
| **nginx** | Answers on your subdomain, handles HTTPS, passes visitors to the app |
| **certbot** | Gets a free HTTPS certificate from Let's Encrypt and renews it |
| **ddns** | Keeps your subdomain pointed at your home internet address when it changes |

```
visitor ──HTTPS──▶ your router (ports 80, 443) ──▶ your PC ──▶ nginx ──▶ app
```

Throughout, `stats.yoursite.com` stands for your subdomain.

## 1. Install Docker Desktop

1. Download Docker Desktop for Windows from <https://www.docker.com/products/docker-desktop/> and
   install it. Accept the WSL 2 option if it asks, and restart when it tells you to.
2. Open Docker Desktop, go to **Settings > General**, and turn on
   **Start Docker Desktop when you sign in to your computer**.

## 2. Keep the PC awake

The site is only up while the PC is on, awake and signed in.

- **Settings > System > Power** (Windows 11) or **Power & sleep** (Windows 10): set sleep
  **when plugged in** to **Never**. The screen can still turn off.
- After Windows Update restarts the PC, sign in so Docker Desktop starts again.

## 3. Make a Cloudflare API token

certbot and ddns use this to prove you own the domain and to update its address.

1. Sign in at <https://dash.cloudflare.com>. Click your profile icon (top right), then
   **My Profile > API Tokens > Create Token**.
2. Next to **Edit zone DNS**, click **Use template**.
3. Under **Zone Resources**, choose **Include > Specific zone > yoursite.com**.
4. Click **Continue to summary**, then **Create Token**, and copy the token. Cloudflare shows it only
   once.

While you're in Cloudflare, look at **DNS > Records** for your domain. If there's already a record for
your subdomain (`stats`), delete it; ddns creates the right one. Leave its proxy setting as
**DNS only** (grey cloud).

## 4. Unzip the files and fill in your settings

1. Unzip `comp-history.zip` somewhere permanent, for example `C:\comp-history`. Avoid OneDrive folders.
2. Open **PowerShell** and run:

```powershell
cd C:\comp-history
Copy-Item .env.example .env
notepad .env
```

3. Fill in your values and save:

```
DOMAIN=stats.yoursite.com
EMAIL=you@example.com
CF_API_TOKEN=the-token-you-copied
```

Keep the `.env` file private: anyone with that token can change your domain's DNS.

## 5. Set up your router

1. Find your PC's local address: in PowerShell run `ipconfig` and note the **IPv4 Address** of the
   connection you're using, for example `192.168.1.50`. A wired connection is more reliable than Wi-Fi.
2. Open your router's admin page (often `http://192.168.1.1` or `http://192.168.0.1`; it's usually on
   a sticker on the router).
3. Give the PC a **fixed address**: look for *DHCP reservation*, *Address reservation* or *Static
   lease*, and reserve the address from step 1 for this PC.
4. Add two **port forwarding** rules (sometimes called *Virtual server* or *NAT forwarding*):
   - TCP port **80** to your PC's address, port **80**
   - TCP port **443** to your PC's address, port **443**

## 6. Start it

In PowerShell, in the `C:\comp-history` folder:

```powershell
docker compose up -d --build
docker compose logs -f
```

The first build takes a few minutes. Then, in the logs, you should see:

1. **ddns:** `Created stats.yoursite.com -> <your home address>`
2. **certbot:** `Getting an HTTPS certificate...`, then about a minute later
   `Certificate in place for stats.yoursite.com`
3. **nginx:** `waiting for the HTTPS certificate...`, then `certificate found` once certbot is done

Press **Ctrl+C** to stop watching the logs; the site keeps running. Running `docker compose ps` should
show all four containers as running, with the app as "healthy".

The first `docker compose up` agrees to the Let's Encrypt Subscriber Agreement on your behalf, which is
what lets certbot get the free certificate: <https://letsencrypt.org/repository/>.

## 7. Check it from outside your home

On your phone, **turn off Wi-Fi** and open `https://stats.yoursite.com`. You should see the Comp
history page with a padlock.

On your home Wi-Fi the subdomain may not open, because many routers can't loop back to their own
address. On the PC itself you can always use <http://localhost:8765>.

If Windows asks whether to allow Docker Desktop through the firewall, allow it. If the site still isn't
reachable from outside, open PowerShell **as administrator** and run:

```powershell
New-NetFirewallRule -DisplayName "Ballroom Stats Analyzer (web)" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow
```

## Everyday tasks

Run these in PowerShell from `C:\comp-history`:

| To | Run |
| --- | --- |
| See whether everything's running | `docker compose ps` |
| Watch activity and errors | `docker compose logs -f` (or `docker compose logs -f app`) |
| Update to a new version | Replace the `.py` files, then `docker compose up -d --build` |
| Stop the site | `docker compose down` (saved pages and the certificate are kept) |
| Start it again | `docker compose up -d` |
| Clear saved pages (rarely needed) | `docker volume rm comp-history_cache` while stopped |

Certificate renewal and address updates happen on their own.

## Changing settings

The app's options are on its `command:` line in `docker-compose.yml`. After editing, run
`docker compose up -d`.

| Option | What it does |
| --- | --- |
| `--public` | Public mode: one search reads Comp Express at a time (others wait in line), one running search per visitor, hourly limits, dancer ID required. |
| `--max-per-hour 20` | Searches one visitor can start per hour. |
| `--max-total-per-hour 200` | Searches the whole site will start per hour, from everyone. |
| `--delay 0.6` | Seconds between requests to ballroomcompexpress.com. Raise it to be gentler on their site. |
| `--visitor-id ip+browser` | Tells visitors apart by address plus a random ID kept in their browser. Needed because Docker Desktop can hide visitors' real addresses from containers. |
| `--allow-name-search` | Also allow name-only searches. Each can read thousands of Comp Express pages and take hours; leave it off unless they've said it's fine. |

## If something's wrong

- **"port is already allocated" for 80 or 443:** another program on the PC is using that port. Run
  `netstat -ano | findstr ":80 :443"` to find its process ID, then look it up in Task Manager's
  **Details** tab. A common one is IIS (World Wide Web Publishing Service), which you can stop under
  **Services**.
- **certbot says it couldn't get the certificate:** check `DOMAIN` and `CF_API_TOKEN` in `.env`, then
  run `docker compose up -d` and `docker compose restart certbot`. Make sure the token's zone is your
  domain.
- **ddns says "no Cloudflare zone found":** copy the **Zone ID** from your domain's **Overview** page in
  Cloudflare (right-hand side, under **API**) into `CF_ZONE_ID=` in `.env`, then `docker compose up -d`.
- **Works on the PC but not from your phone on mobile data:**
  - Check the port forwarding rules point at the PC's current address (`ipconfig`), and the firewall
    step in section 7.
  - Compare the address in the ddns log with the **WAN/Internet address** on your router's status
    page. If they're different (the router's often starts with `100.` or `10.`), your provider shares
    one address between customers, and port forwarding can't work on that connection. Cloudflare
    Tunnel works around this; ask and I'll set that up instead.
  - Some providers block incoming ports 80 and 443 on home plans. Their support page or a quick call
    will tell you.

## Safety notes

Opening ports on your router puts this PC on the internet. To keep that small:

- Only nginx is reachable from outside, and it answers only for your subdomain.
- The app runs read-only, with no extra permissions.
- Keep Windows and Docker Desktop updated, and keep `.env` private.

## Before you share the link

Let Ballroom Comp Express know about the site (inquiries@ballroomcompexpress.com). It reads their public
results pages, so a public tool sends them traffic they didn't plan for.
