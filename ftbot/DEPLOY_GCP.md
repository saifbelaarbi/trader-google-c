# Deploy Fqtrader on GCP (Compute Engine VM)

Run the freqtrade `ClaudeBreakout` bot 24/7 in the cloud instead of on your PC — a
self-managed VM that does exactly what a trading VPS (QuantVPS/ForexVPS) does, for a
fraction of the price, in the GCP project you already use (`tradingbot-496815`).

> **Why a VM, not Cloud Run / a trading VPS.** `ClaudeBreakout` acts once per **4h
> candle** on Bybit — latency is irrelevant, so the "low-latency trading VPS" pitch buys
> you nothing. What you need is boring **24/7 uptime + persistent local state**. Cloud
> Run is stateless/scale-to-zero and request-driven (great for the relay, wrong for a
> long-running bot with a local SQLite DB). A small Compute Engine VM is the right tool.

> **Still dry-run.** Moving to a VM is a dress rehearsal for go-live deployment; it does
> **not** change the Phase-3 gates (`OVERHAUL_PLAN.md §4`). Keep paper-trading until they
> pass. And **stop the PC bot when the VM takes over** — Telegram allows only one
> consumer per bot token (see §8).

**Rough cost:** `e2-small` ≈ $12–14/mo + ~$2 disk. (`e2-micro` is cheaper/free-tier in
some regions but 1 GB RAM is tight for freqtrade — `e2-small` is the safe floor.)

---

## 0. Prerequisites (once)

```bash
# set your project/region (matches the existing Cloud Run deployment)
gcloud config set project tradingbot-496815
gcloud config set compute/region europe-west1
gcloud config set compute/zone europe-west1-b

# enable the APIs you'll use
gcloud services enable compute.googleapis.com iap.googleapis.com
# (add secretmanager.googleapis.com later, for live keys — §10)
```

---

## 1. Lock SSH to IAP (no public SSH port)

Allow SSH only from Google's Identity-Aware Proxy range, not the open internet:

```bash
gcloud compute firewall-rules create allow-iap-ssh \
  --network=default --direction=INGRESS --action=ALLOW \
  --rules=tcp:22 --source-ranges=35.235.240.0/20
```

The VM keeps an ephemeral **public IP for outbound** HTTPS to Bybit (default egress),
but nothing inbound except IAP-tunnelled SSH.

---

## 2. Create the VM

```bash
gcloud compute instances create ftbot-vm \
  --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=20GB --boot-disk-type=pd-balanced \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring
```

SSH in (tunnelled through IAP):

```bash
gcloud compute ssh ftbot-vm --tunnel-through-iap
```

---

## 3. Install Docker + clone the repo (on the VM)

```bash
sudo apt-get update && sudo apt-get install -y docker.io git
sudo usermod -aG docker "$USER"     # then log out/in so docker works without sudo
exit
gcloud compute ssh ftbot-vm --tunnel-through-iap   # reconnect

git clone https://github.com/saifbelaarbi/trader-google-c.git
cd trader-google-c
```

---

## 4. Fill in your secrets (on the VM, never committed)

Edit `ftbot/config.dry.json` and set your real values:

```bash
nano ftbot/config.dry.json
# telegram.token   -> a NEW @BotFather token (NOT saif_trader_bot — see PC_GUIDE §3a)
# telegram.chat_id -> your chat id
# telegram.enabled -> true
# api_server.jwt_secret_key / ws_token / password -> random strings
```

Then tell git to ignore your local edits so `git pull` (updates) won't clobber them:

```bash
git update-index --skip-worktree ftbot/config.dry.json
```

> For real Bybit keys later, use Secret Manager instead of putting them in the file — §10.

---

## 5. Run the bot (Docker, auto-restart)

```bash
docker run -d --name ftbot --restart unless-stopped \
  -v "$PWD/ftbot:/freqtrade/user_data" \
  -p 127.0.0.1:8080:8080 \
  freqtradeorg/freqtrade:stable \
  trade \
    --userdir /freqtrade/user_data \
    --config /freqtrade/user_data/config.dry.json \
    --strategy ClaudeBreakout
```

- `--restart unless-stopped` → survives crashes and VM reboots.
- The dry-run DB (`ftbot/tradesv3.dryrun.sqlite`) lives on the VM disk and persists.
- Port bound to `127.0.0.1` only — the FreqUI/API is not exposed publicly.

Check it:

```bash
docker logs -f ftbot          # watch startup; Ctrl-C to detach
docker ps                     # STATUS should say "Up ... (healthy)"
```

You should get the Telegram breakout-radar push within one 4h candle.

---

## 6. Alternative: systemd (pip install, no Docker)

If you prefer a native install:

```bash
sudo apt-get install -y python3-venv build-essential
python3 -m venv ~/ft-env && ~/ft-env/bin/pip install freqtrade
sudo tee /etc/systemd/system/ftbot.service >/dev/null <<'EOF'
[Unit]
Description=Freqtrade ClaudeBreakout (dry-run)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_VM_USER
WorkingDirectory=/home/YOUR_VM_USER/trader-google-c
ExecStart=/home/YOUR_VM_USER/ft-env/bin/freqtrade trade \
  --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now ftbot
journalctl -u ftbot -f
```

---

## 7. Updating the bot (mirror of `watch-bot`)

When you push strategy/config changes to `main`, refresh the VM:

```bash
cd ~/trader-google-c
git pull origin main          # your filled config is protected by skip-worktree (§4)
docker restart ftbot          # or: sudo systemctl restart ftbot
```

Optional one-liner script `~/update-ftbot.sh`:

```bash
#!/usr/bin/env bash
set -e
cd ~/trader-google-c && git pull origin main && docker restart ftbot
echo "ftbot updated @ $(date -u)"
```

---

## 8. Migrating off your PC

Run the bot in **exactly one place**. When the VM is confirmed healthy:

1. On the PC, stop the bot (`/stop` in Telegram, then close the process / container).
2. Confirm only the VM is polling the Telegram token (`/status` should answer once).

Running both on the same token causes Telegram update conflicts (one consumer per token).

---

## 9. Backups & housekeeping

```bash
# snapshot the disk (captures the dry-run trade history)
gcloud compute disks snapshot ftbot-vm --snapshot-names="ftbot-$(date +%Y%m%d)"

# stop/start to save money while not testing (dry-run only!)
gcloud compute instances stop  ftbot-vm
gcloud compute instances start ftbot-vm

# tear down completely
gcloud compute instances delete ftbot-vm
```

A scheduled snapshot policy (`gcloud compute resource-policies create snapshot-schedule …`)
can automate daily backups.

---

## 10. Hardening for go-live (only after the gates pass)

When you switch to **real** Bybit keys and `dry_run: false`:

- **Secret Manager**, not the config file, for `BYBIT_API_KEY` / `BYBIT_API_SECRET`:
  ```bash
  echo -n "REAL_KEY"    | gcloud secrets create BYBIT_API_KEY    --data-file=-
  echo -n "REAL_SECRET" | gcloud secrets create BYBIT_API_SECRET --data-file=-
  ```
  Grant the VM's service account `roles/secretmanager.secretAccessor`, then fetch at
  startup and export into the container env (`--env`), so keys never sit on disk.
- Give the VM a **dedicated service account** with least privilege (not the default).
- Consider **Cloud NAT + `--no-address`** so the VM has no public IP at all (egress via
  NAT), removing the inbound attack surface entirely.
- Tighten the strategy's `MaxDrawdown` protection and start at half size (per
  `OVERHAUL_PLAN.md §4`).
- Bybit API key: enable IP allow-listing to the VM's egress IP; disable withdrawals.

---

## 11. Quick reference

```bash
# create
gcloud compute instances create ftbot-vm --machine-type=e2-small \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB
# connect
gcloud compute ssh ftbot-vm --tunnel-through-iap
# run
docker run -d --name ftbot --restart unless-stopped \
  -v "$PWD/ftbot:/freqtrade/user_data" -p 127.0.0.1:8080:8080 \
  freqtradeorg/freqtrade:stable trade --userdir /freqtrade/user_data \
  --config /freqtrade/user_data/config.dry.json --strategy ClaudeBreakout
# logs / update / stop
docker logs -f ftbot
git pull origin main && docker restart ftbot
docker stop ftbot
```

---

*Companion docs: `PC_GUIDE.md` (run it on your PC), `RESEARCH_returns.md` (strategy
rationale), `OVERHAUL_PLAN.md` (gates). This guide is for hosting the same dry-run bot on
GCP — no trading-logic changes.*
