#!/usr/bin/env python3
"""One-off helper: prints the chat id(s) that have messaged your Telegram bot (so you can copy yours into the TELEGRAM_CHAT_ID secret), and can send a test message.
Needs the TELEGRAM_BOT_TOKEN secret. The token is never printed. Send your bot any message in Telegram first (Telegram only keeps messages for about 24 hours)."""
import os, json, urllib.parse, urllib.request
tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(); chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not tok: raise SystemExit("TELEGRAM_BOT_TOKEN secret is missing")
def call(method, data=None):
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=urllib.parse.urlencode(data).encode() if data else None)
    try: return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except urllib.error.HTTPError as e: return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e: return {"ok": False, "error": type(e).__name__}
me = call("getMe"); print("Bot check:", "OK, bot username @" + me["result"]["username"] if me.get("ok") else f"FAILED {me.get('error')} (check the token secret)")
u = call("getUpdates"); seen = {}
for x in (u.get("result") or []):
    m = x.get("message") or x.get("channel_post") or {}; c = m.get("chat") or {}
    if c.get("id") is not None: seen[c["id"]] = (c.get("type"), " ".join(filter(None, [c.get("first_name"), c.get("last_name"), c.get("title"), ("@" + c["username"]) if c.get("username") else None])))
if seen:
    print("Chats that have messaged your bot (use YOUR own; ignore any you do not recognise):")
    for cid, (tp, nm) in seen.items(): print(f"  chat id {cid}   type {tp}   name {nm}")
else: print("No messages found. Open your bot in Telegram, send it any message (for example 'hi'), then run this again.")
if chat:
    r = call("sendMessage", {"chat_id": chat, "text": "Test message from your alert system. If you can read this, Telegram alerts are set up."})
    print("Test message to TELEGRAM_CHAT_ID:", "SENT" if r.get("ok") else f"FAILED {r.get('error')}")
