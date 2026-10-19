"""Phone-as-gamepad server.

Serves the touch controller page to phones on the LAN, receives their
input over WebSockets, and feeds it into virtual Xbox 360 controllers
(ViGEmBus). Run:  py server.py
"""

import io
import json
import random
import socket
from pathlib import Path

import qrcode
import qrcode.image.svg
from aiohttp import web, WSMsgType

from pad import PadManager

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
PORT = 8765

# games the user supplied; served only on the LAN, behind the session code
ROMS_DIR = Path.home() / "Documents" / "retro-games"
ROM_SYSTEMS = {
    "n64": (".z64", ".n64", ".v64"),
    "snes": (".sfc", ".smc"),
    "nes": (".nes",),
}

# Short session code so a stray visitor on the network can't grab a slot.
# Ambiguous characters (0/O, 1/I) left out; persisted so QR codes and phones
# keep working across restarts (delete session_code.txt for a fresh one).
_CODE_FILE = ROOT / "session_code.txt"
if _CODE_FILE.is_file():
    SESSION_CODE = _CODE_FILE.read_text().strip().upper()
else:
    SESSION_CODE = "".join(random.choices("23456789ABCDEFGHJKMNPQRSTUVWXYZ", k=4))
    _CODE_FILE.write_text(SESSION_CODE)

pads = PadManager()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no packet is sent; just picks the LAN interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def controller_url():
    return f"http://{lan_ip()}:{PORT}/?s={SESSION_CODE}"


async def index(request):
    return web.FileResponse(STATIC / "controller.html")


async def status_page(request):
    return web.FileResponse(STATIC / "status.html")


async def api_status(request):
    data = pads.status()
    data["code"] = SESSION_CODE
    data["url"] = controller_url()
    return web.json_response(data)


async def qr_svg(request):
    img = qrcode.make(controller_url(), image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
    buf = io.BytesIO()
    img.save(buf)
    return web.Response(body=buf.getvalue(), content_type="image/svg+xml")


# --- WebRTC signaling: the PC's own browser captures the game window and
# streams it peer-to-peer to viewers; this server only relays the handshake.
rtc = {"host": None, "viewers": {}, "next_id": 0}


async def rtc_handler(request):
    if request.query.get("s", "").upper() != SESSION_CODE:
        raise web.HTTPForbidden(text="bad session code")
    role = request.query.get("role", "view")
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    if role == "host":
        old = rtc["host"]
        if old is not None and not old.closed:
            await old.close()
        rtc["host"] = ws
        print("[+] stream host connected")
        for vid in list(rtc["viewers"]):
            await ws.send_json({"t": "viewer-joined", "id": vid})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    m = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                vws = rtc["viewers"].get(m.get("to"))
                if vws is not None and not vws.closed:
                    await vws.send_json(m)
        finally:
            if rtc["host"] is ws:
                rtc["host"] = None
            print("[-] stream host disconnected")
            for vws in list(rtc["viewers"].values()):
                if not vws.closed:
                    await vws.send_json({"t": "host-gone"})
        return ws

    rtc["next_id"] += 1
    vid = rtc["next_id"]
    rtc["viewers"][vid] = ws
    await ws.send_json({"t": "welcome", "id": vid})
    host = rtc["host"]
    if host is not None and not host.closed:
        await host.send_json({"t": "viewer-joined", "id": vid})
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            m["from"] = vid
            host = rtc["host"]
            if host is not None and not host.closed:
                await host.send_json(m)
    finally:
        rtc["viewers"].pop(vid, None)
        host = rtc["host"]
        if host is not None and not host.closed:
            await host.send_json({"t": "viewer-left", "id": vid})
    return ws


async def play_page(request):
    return web.FileResponse(STATIC / "play.html")


async def api_roms(request):
    if request.query.get("s", "").upper() != SESSION_CODE:
        raise web.HTTPForbidden(text="bad session code")
    out = {}
    for sys_name, exts in ROM_SYSTEMS.items():
        d = ROMS_DIR / sys_name
        out[sys_name] = sorted(
            p.name for p in d.iterdir()
            if p.is_file() and p.suffix.lower() in exts
        ) if d.is_dir() else []
    return web.json_response(out)


async def rom_file(request):
    if request.query.get("s", "").upper() != SESSION_CODE:
        raise web.HTTPForbidden(text="bad session code")
    sys_name = request.match_info["sys"]
    if sys_name not in ROM_SYSTEMS:
        raise web.HTTPNotFound()
    base = (ROMS_DIR / sys_name).resolve()
    path = (base / request.match_info["name"]).resolve()
    if base not in path.parents:
        raise web.HTTPForbidden(text="bad path")
    if not path.is_file() or path.suffix.lower() not in ROM_SYSTEMS[sys_name]:
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def host_page(request):
    return web.FileResponse(STATIC / "host.html")


async def watch_page(request):
    return web.FileResponse(STATIC / "watch.html")


async def ws_handler(request):
    if request.query.get("s", "").upper() != SESSION_CODE:
        raise web.HTTPForbidden(text="bad session code")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    slot = pads.claim()
    if slot is None:
        await ws.send_json({"t": "full"})
        await ws.close()
        return ws

    peer = request.transport.get_extra_info("peername")
    slot.ip = peer[0] if peer else "?"
    await ws.send_json({"t": "hello", "player": slot.index + 1, "mode": pads.mode})
    print(f"[+] P{slot.index + 1} connected from {slot.ip}")

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                m = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            t = m.get("t")
            if t == "state":
                slot.apply(m)
            elif t == "ping":
                await ws.send_json({"t": "pong", "ts": m.get("ts")})
    finally:
        print(f"[-] P{slot.index + 1} disconnected")
        pads.release(slot)
    return ws


def main():
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/status", status_page),
        web.get("/host", host_page),
        web.get("/watch", watch_page),
        web.get("/play", play_page),
        web.get("/api/roms", api_roms),
        web.get("/rom/{sys}/{name}", rom_file),
        web.get("/rtc", rtc_handler),
        web.get("/api/status", api_status),
        web.get("/qr.svg", qr_svg),
        web.get("/ws", ws_handler),
    ])

    url = controller_url()
    print()
    print("=" * 56)
    print("  Phone Gamepad server")
    print(f"  Phones connect to:   {url}")
    print(f"  Session code:        {SESSION_CODE}")
    print(f"  Status page (PC):    http://localhost:{PORT}/status")
    print(f"  Share screen (PC):   http://localhost:{PORT}/host")
    print(f"  Watch + gamepad:     http://{lan_ip()}:{PORT}/watch?s={SESSION_CODE}")
    print(f"  Play in browser:     http://{lan_ip()}:{PORT}/play?s={SESSION_CODE}")
    if pads.mode == "mock":
        print("  MODE: TEST ONLY — ViGEmBus driver not installed.")
        print("  Input shows on the status page but no game will see it.")
    print("=" * 56)
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    try:
        qr.print_ascii(invert=True)
    except UnicodeEncodeError:
        print("  (QR code: open the status page for a scannable one)")
    print()

    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
