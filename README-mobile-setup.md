# Mobile setup

## Telegram secrets

1. Open the repository on GitHub, then go to **Settings → Secrets and variables → Actions**.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste either secret into an issue or chat.
3. Add the bot to the destination Telegram chat and allow it to send photos.

## Run the scanner

- Scheduled runs run every three hours in scan-only mode; they never send Telegram messages.
- To verify the scanner, open **Actions → Marathon Saathi scanner → Run workflow** and leave `send_telegram` set to `false`.
- To send events, choose `true` only after adding both secrets. Each manual send run is limited to three upcoming events. It sends the listing's original image and registration link only.

## Sources

The source list is in `bot.py`: MarathonMitra, India Running, MySamay, fstr, RunnersDuniya, MarathonTracks, and runINDIA. Add a site in the `SOURCES` list with its listing URL, hostname, event path prefixes, and optional direct-registration hosts. The scanner logs a warning if a source has no parseable links.

The bot requires an original event image, a registration link, and a future event date. It skips records without them. It does not generate posters or post to Facebook or Instagram.