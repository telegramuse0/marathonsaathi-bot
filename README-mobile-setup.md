# Marathon Saathi: mobile setup

## Telegram secrets

1. Open the repository on GitHub, then go to **Settings → Secrets and variables → Actions**.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Keep both private.
3. Add the bot to the destination Telegram chat and allow it to send photos.

## Automatic scanner

- GitHub Actions checks every two hours. Scheduled runs send future events automatically when both Telegram secrets exist.
- Each run sends up to three events, with the original event image and its event-specific page link. Already sent events are skipped.
- A manual run with `send_telegram` set to `false` is scan-only. Choose `true` only when you want an immediate Telegram send.

## Add or edit a website from your phone

1. Open this repository on GitHub and create a Codespace on the `main` branch (**Code → Codespaces → Create codespace on main**).
2. In the Codespace terminal, run `python admin.py --host 0.0.0.0`.
3. Open the **Ports** tab. Open port `8765`; keep its visibility set to **Private**. Open the forwarded address on your phone.
4. Paste the access code printed in the terminal.
5. Fill in the website name, listing URL, domain, and event path patterns. Tap **Preview scan** to see detected event images and exact event-page links.
6. Tap **Save website**, then **Publish config to GitHub**. This publishes only `sources.json`; Actions runs a scan-only check.

Select a saved site to edit it, or tap **New** to add one. The preview checks the listing and up to eight event pages; it never sends Telegram messages. Stop the server or close the Codespace when finished.

The bot sends an event only when it finds an original event image, an event-specific registration link, and a future date. It does not generate posters or post to Facebook or Instagram.
