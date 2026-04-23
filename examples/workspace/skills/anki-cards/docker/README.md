# Headless Anki for ZeroClaw

Runs Anki 25.9.2 in Xvfb on the Pi with the AnkiConnect plugin (addon `2055492159`) patched to bind `0.0.0.0:8765`. Port 8765 is exposed on loopback only — the ZeroClaw agent on the same Pi reaches it at `http://127.0.0.1:8765`.

## One-time setup

AnkiConnect's addon files are pre-seeded under `./data/addons21/2055492159/` (with `webBindAddress` already patched to `0.0.0.0`), so no build is needed — we just pull the prebuilt image.

```bash
cd <HOME>/.zeroclaw/workspace/skills/anki-cards/docker
docker compose up -d
```

Takes ~2 min to pull.

If the addon needs a refresh (new AnkiConnect release), re-seed from the host:

```bash
cd /tmp && curl -sL -o ankiconnect.zip "https://ankiweb.net/shared/download/2055492159?v=2.1&p=250902"
unzip -oq /tmp/ankiconnect.zip -d <HOME>/.zeroclaw/workspace/skills/anki-cards/docker/data/addons21/2055492159/
# re-apply the webBindAddress patch if config.json got overwritten
```

## One-time AnkiWeb first sync (via VNC)

The sync credentials are already saved in the profile (set programmatically from the Python-anki backend). However, the **first full sync** between the container and AnkiWeb cannot be triggered automatically — Anki's full-sync HTTP call requires an `Anki-Original-Size` header that only the GUI client sets. So one manual VNC session is needed to complete the first full sync. After that, every incremental sync works headlessly via AnkiConnect.

From your laptop:

```bash
ssh -L 5900:127.0.0.1:5900 shaba@<pi-address>
```

Open any VNC viewer to `localhost:5900` (no password). In the Anki window:
1. File menu → Switch Profile → pick `User 1` if prompted (usually already loaded)
2. Tools → Preferences → Network → confirm AnkiWeb account is shown; check "on profile open/close, sync automatically"
3. Click the **Sync** button (blue arrows, top-right) → when the dialog asks "Upload to AnkiWeb" or "Download from AnkiWeb", pick **Upload** if your AnkiWeb account is empty / you want this container as source of truth, or **Download** to pull existing content.
4. Close VNC.

From this point on, cards added via AnkiConnect auto-sync.

## Health check

```bash
curl -s http://127.0.0.1:8765 -d '{"action":"version","version":6}'
# → {"result":6,"error":null}
```

## Logs / restart

```bash
docker compose logs -f anki
docker compose restart anki
```

## Data

Collection + addons live in `./data` (bind-mounted to `/data`). Back this up alongside the rest of the Pi.
