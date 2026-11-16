# Matryoshka pilot notifications

Program start: 2026-11-13 00:00 Europe/Moscow. Pilot shops: 8889, 7745, 9107.
Destination: the existing verified test Telegram group only.

Run `bash tools/install_matryoshka_monitor.sh` on the VPS as root after pulling
source. This enables `courier-matryoshka.timer`, starts a check immediately,
and repeats five minutes after each completed run. Corporate VPN contention
causes a failed check and a later timer retry; other VPN processes are never killed.

The source recognizes explicit Matryoshka types 24–31 in successful orders,
with a blank partner per the confirmed business rule. It notifies once on first
observation, then when the observed type is behind the 100/300/600 thresholds,
or when the 1000-order program has ended. It never edits courier cards.

Counts start at the first successful Matryoshka delivery since launch, across
all shops and later courier types. This is an observable delivery-based start,
not a verified connection date. The latest successful order provides the
observed type, not a live courier-card read. Notices explicitly state this.
Automatic eligibility inference for ordinary-type couriers (new or returning
after two years) is NOT enabled by this installer. Existing explicit program
assignments are the enrollment signal; they are not reclassified from a
partial historical window.

The private snapshot and SQLite delivery journal live under
`/opt/courier-analytics/private`. Credentials remain under
`/etc/superset-telegram`. No participant data goes into Git.

Check operation:

```
systemctl status courier-matryoshka.timer --no-pager
journalctl -u courier-matryoshka.service -n 30 --no-pager
```

`Matryoshka notices sent=N` confirms Telegram acknowledged N messages.
A failed collector prevents any old snapshot being sent. Source refresh timing
still depends on Superset; the five-minute timer is not an instant-update promise.

Each event is claimed in SQLite before network I/O. Crashes or failed responses
leave `inflight` / `uncertain` records. These are deliberately not retried. Check
the group before an operator changes such a record; deleting the whole journal
would resend previous notices. The log reports the count requiring review.

Stop further checks with `systemctl disable --now courier-matryoshka.timer`.
A currently running service may finish; stop that service separately if needed.
