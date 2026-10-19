# Phone Gamepad

Turns up to 4 phones into virtual Xbox 360 controllers for games on this PC,
over home Wi-Fi. No app install on the phone — just the browser.

## Run it

```powershell
& $env:USERPROFILE\Documents\phone-gamepad\start-server.ps1
```

(That script runs the server under the system Python, which Windows Firewall
already allows inbound — running `.venv\Scripts\python server.py` directly
works too, but phones will be blocked until that exe gets its own
firewall rule.)

The terminal prints a QR code and URL (something like `http://192.168.x.x:8765/?s=AB12`).
Scan it with each phone. The status page for this PC is
<http://localhost:8765/status>.

- The 4-letter session code changes every time the server starts.
- First run: Windows Firewall will ask — tick **Private networks** and Allow.

## Two modes

- **Test mode** (no driver): everything works end to end, input shows live on
  the status page, but games can't see the controllers.
- **Live mode**: needs the ViGEmBus driver (one-time admin install from
  https://github.com/nefarius/ViGEmBus/releases — official source only).
  Then each phone appears in Windows as a real Xbox 360 pad:
  check with `Win+R` → `joy.cpl`, or https://hardwaretester.com/gamepad

## Layout

- `server.py` — aiohttp web + WebSocket server, QR, status API
- `pad.py` — ViGEmBus virtual pads (falls back to test mode without driver)
- `static/controller.html` — the phone page (sticks, D-pad, ABXY, LB/RB/LT/RT, Start/Select)
- `static/status.html` — who's connected + live input readout
