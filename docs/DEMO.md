# 90-second demo

**Goal:** in 90 seconds, show that it's a real voice agent, that it's wired to a real API, and that it's
*safe*. The confirmation guardrail and audit trail are what make it stand out, so give them the most time.

**Screen layout:** left 60%: ElevenLabs agent widget (or the call UI). Right 40%: a terminal running
`watch -n1 'curl -s -H "X-Admin-Key: $ADMIN_KEY" localhost:8000/admin/audit?limit=8 | jq -r ".data[] | [.event, .target, .details.utterance // \"\"] | @tsv"'`
so audit events appear live during the call.

**Before recording:** `rm servicedesk.db` (fresh seed → ticket is INC-1001), start the API + ngrok, do one
throwaway call to warm up, then reset again. Record with headphones to avoid echo.

| Time | On screen | Audio |
|---|---|---|
| **0:00–0:08** | Title card: *Voice IT Service Desk: ElevenLabs + Python API*. | You (voice-over): "This is Nova, an IT help desk agent you can call. Watch the right side: that's the live audit log." |
| **0:08–0:25** | Start call. Audit shows `device.lookup`. | **Caller:** "Hi, I think I left my work laptop in a taxi." **Nova:** "Okay, let's get that secured. What's your work email?" **Caller:** "priya dot shah at northwind dot example." **Nova:** "I found two devices for Priya Shah: a MacBook Pro and an iPhone 15. Is it the MacBook?" |
| **0:25–0:38** | `ticket.created INC-1001` appears. | **Caller:** "Yes." **Nova:** "I've opened ticket I N C one zero zero one with high priority. I can remotely lock it so nobody can get in. Want me to do that?" **Caller:** "Please." |
| **0:38–0:58** | `action.requested`, then `action.confirm_rejected  "um, which one?"`. **Zoom on the terminal.** | **Nova:** "Just to confirm: you want me to remotely lock the MacBook Pro, asset tag N W one zero four two… Shall I go ahead?" **Caller:** "Um, which one?" **Nova:** "Sorry, I need a clear yes or no…" **Caller:** "Yes, go ahead." |
| **0:58–1:08** | `action.confirmed "Yes, go ahead."` → `action.executed CMD-…`. | **Nova:** "Done. Your MacBook Pro is locked now. I've added this to ticket I N C one zero zero one." |
| **1:08–1:20** | Cut to terminal: `pytest -q` → **62 passed**, then `curl …/admin/audit/verify` → `"valid": true`. Optional 2-second flash of `MDM_FAULT=outage` producing the "nothing has been changed" line. | Voice-over: "The API, not the prompt, enforces confirmation: two steps, the caller's exact words, a two-minute expiry, owner checks. Wipes need the asset tag read back. Every step is hash-chained, so tampering is detectable." |
| **1:20–1:30** | Architecture diagram from README + repo URL. | "ElevenLabs for voice, FastAPI for the integration, and a pluggable MDM layer that could point at Jamf or Intune tomorrow." |

**Backup plan:** if the live call misbehaves, record `python scripts/demo_call.py --pause 1.5` with
the same right-hand audit pane, and use ElevenLabs TTS for both voices. The tool calls and audit trail are real either way.

**Edit notes:** cut dead air between turns (voice agents have ~0.5–1s latency, and that's fine to show once).
Burn in captions, since many people watch muted. Keep the "um, which one?" moment: it's the whole pitch.
