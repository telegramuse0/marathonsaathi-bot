[README-mobile-setup.md](https://github.com/user-attachments/files/34134357/README-mobile-setup.md)
# Marathon Saathi: mobile setup

Scanner inputs are the public listing pages for MarathonMitra, Townscript, India Running, MySamay, fstr, RunnersDuniya, and MarathonTracks. To add a source, add one entry to `SOURCES` in `bot.py` with its listing URL, host, and event URL path prefixes. The scanner sends only the source page's `og:image` and a discovered registration link; it never creates artwork or posts to Facebook/Instagram.

## Add the Telegram secrets from a phone

1. Open `github.com/telegramuse0/marathonsaathi-bot` in a mobile browser and sign in.
2. Open **Settings → Secrets and variables → Actions → New repository secret**.
3. Add `TELEGRAM_BOT_TOKEN` (from BotFather) and `TELEGRAM_CHAT_ID` (your chat ID or the target group's chat ID). Keep both private.
4. Open **Actions → Marathon Saathi scanner** and enable workflows if GitHub shows that button.
5. A scheduled run occurs every three hours and is scan-only. To explicitly send new events, tap **Run workflow**, set **Send new events to Telegram** to `true`, and run it. The `seen.json` history is committed after the run to prevent repeat sends.
6. To pause the schedule, open the workflow's **…** menu in Actions and choose **Disable workflow**.

Telegram bot must first be added to the target chat; in a group, grant it permission to send photos. Telegram delivery requires both secrets. Scan-only scheduled runs do not need Telegram secrets.

## Notes

- The scanner requires an original `og:image` and a distinct link whose label indicates registration. It skips pages without both.
- Cross-site duplicates are detected by normalized event title. If a listing site changes markup, update that site's URL paths or extraction logic and run the workflow manually in scan-only mode to inspect its logs.
- GitHub Actions schedules can start late during high load. Workflow files are read from the default branch.
