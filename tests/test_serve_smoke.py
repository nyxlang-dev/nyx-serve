#!/usr/bin/env python3
"""Smoke test de nyx-serve: daemon efímero (examples/standalone.nx) + HTTP.

Corre con `make test-serve`. No requiere red externa ni nyx-kv.
El binario se toma de NYX_SERVE_BIN o ./nyx-serve (raíz del stack).
"""
import base64
import hashlib
import http.client
import os
import signal
import socket
import struct
import subprocess
import sys
import time

PORT = int(os.environ.get("SERVE_SMOKE_PORT", "13080"))
WS_CATCHALL_PORT = int(os.environ.get("SERVE_SMOKE_WS_PORT", "13081"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.environ.get("NYX_SERVE_BIN", os.path.join(ROOT, "nyx-serve"))

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS {name}")
    else:
        failed += 1
        print(f"  FAIL {name} {detail}")


def wait_for_port(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def get(conn_or_none, path):
    conn = conn_or_none or http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    return conn, resp.status, body


def get_h(path):
    """GET que también devuelve las cabeceras. No sigue redirects (http.client
    no los sigue por defecto), así podemos inspeccionar el 302 crudo."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, body, headers


def spawn_daemon(port, extra_args=None):
    proc = subprocess.Popen(
        [BINARY, "--port", str(port)] + (extra_args or []),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
    )
    return proc


def stop_daemon(proc):
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def ws_accept_key(key):
    digest = hashlib.sha1((key + WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def ws_handshake(sock, path):
    """Sends a raw WS upgrade request over `sock` and returns (key, header,
    leftover): the HTTP response up to \\r\\n\\r\\n plus any bytes read PAST
    the header. The daemon writes 101+frame+close back-to-back, so TCP can
    coalesce them into one segment — discarding the tail here was the flaky
    'payload b'' ' of the ws-catchall check (the next recv() saw only EOF)."""
    key_bytes = os.urandom(16)
    key = base64.b64encode(key_bytes).decode()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(req.encode())
    resp = b""
    sock.settimeout(5)
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            break
        resp += chunk
    head, sep, leftover = resp.partition(b"\r\n\r\n")
    return key, head + sep, leftover


def recv_ws_frame(sock, buf=b""):
    """Returns the bytes of (at least) one server frame, seeding from the
    handshake leftover and reading more only if the frame is incomplete.
    Short-length frames only (<126), same scope as ws_parse_server_frame."""
    sock.settimeout(5)
    while True:
        if len(buf) >= 2 and len(buf) >= 2 + (buf[1] & 0x7F):
            return buf
        chunk = sock.recv(4096)
        if not chunk:
            return buf
        buf += chunk


def ws_client_frame(payload: bytes) -> bytes:
    """Builds a single masked text frame (RFC6455 requires client→server
    frames to be masked)."""
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytes([0x81, 0x80 | len(payload)])  # FIN+text, MASK+len (<126)
    return header + mask + masked


def ws_parse_server_frame(data: bytes):
    """Parses a single unmasked server→client frame (opcode, payload).
    Only handles the short-length (<126 bytes) case, enough for this test."""
    if len(data) < 2:
        return None, b""
    opcode = data[0] & 0x0F
    length = data[1] & 0x7F
    payload = data[2:2 + length]
    return opcode, payload


def main():
    if not os.path.isfile(BINARY):
        print(f"FAIL: binario no encontrado: {BINARY} (correr `make build`)")
        return 1

    proc = spawn_daemon(PORT)
    try:
        check("daemon arriba", wait_for_port(PORT), f"(:{PORT} nunca abrió)")
        if failed:
            return 1

        _, status, body = get(None, "/")
        check("GET / → 200", status == 200, f"(status {status})")
        check("GET / body", b"nyx-serve" in body, f"({body[:60]!r})")

        _, status, body = get(None, "/health")
        check("GET /health → 200 ok", status == 200 and b"ok" in body,
              f"(status {status}, {body[:60]!r})")

        _, status, body = get(None, "/api/health")
        check("GET /api/health → 200 ok", status == 200 and b"ok" in body,
              f"(status {status}, {body[:60]!r})")

        _, status, _ = get(None, "/nonexistent")
        check("GET /nonexistent → 404", status == 404, f"(status {status})")

        # Task 3.2: template engine E2E — escape + if + each en un solo render.
        _, status, body = get(None, "/template-demo")
        expected_template_html = (
            b"<h1>&lt;Nyx&gt;</h1><ul>"
            b"<li>Ann</li><li>&lt;Bob&gt;</li>"
            b"</ul>"
        )
        check("GET /template-demo → 200", status == 200, f"(status {status})")
        check("GET /template-demo body exacto", body == expected_template_html,
              f"({body!r})")

        # Bug 1: redirect 3xx debe emitir headers_flat (Set-Cookie) y Location
        status, _, hdrs = get_h("/redir")
        check("GET /redir → 302", status == 302, f"(status {status})")
        check("redirect Location", hdrs.get("location") == "/health",
              f"(location {hdrs.get('location')!r})")
        check("redirect Set-Cookie sobrevive",
              "sid=abc" in (hdrs.get("set-cookie") or ""),
              f"(set-cookie {hdrs.get('set-cookie')!r})")

        # Bug 3: app_after cableado — X-Request-Id en toda respuesta (incl. 302)
        check("after-hook X-Request-Id en redirect",
              hdrs.get("x-request-id") == "test",
              f"(x-request-id {hdrs.get('x-request-id')!r})")
        _, _, hdrs_root = get_h("/")
        check("after-hook X-Request-Id en 200",
              hdrs_root.get("x-request-id") == "test",
              f"(x-request-id {hdrs_root.get('x-request-id')!r})")

        # Bug 2: middleware que continúa (status 0) aporta cabeceras downstream
        check("middleware continue aporta X-Mw",
              hdrs_root.get("x-mw") == "seen",
              f"(x-mw {hdrs_root.get('x-mw')!r})")

        # keep-alive: 2 requests por la misma conexión
        conn, status1, _ = get(None, "/")
        try:
            _, status2, _ = get(conn, "/health")
            check("keep-alive 2 requests", status1 == 200 and status2 == 200,
                  f"(status {status1}/{status2})")
        finally:
            conn.close()

        # Task 3.1 — app_ws(pattern, handler): handshake WS completo por
        # socket crudo contra una ruta con {param} (ws_echo_handler).
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        try:
            key, resp, ws_left = ws_handshake(s, "/ws/echo/testroom")
            check("WS handshake → 101", resp.startswith(b"HTTP/1.1 101"),
                  f"({resp[:80]!r})")
            expected_accept = ws_accept_key(key)
            check("WS handshake Sec-WebSocket-Accept correcto",
                  f"Sec-WebSocket-Accept: {expected_accept}".encode() in resp,
                  f"(esperado {expected_accept!r}, resp {resp!r})")

            s.sendall(ws_client_frame(b"hello"))
            frame = recv_ws_frame(s, ws_left)
            opcode, payload = ws_parse_server_frame(frame)
            check("WS eco de 1 frame de texto", opcode == 0x1 and len(payload) > 0,
                  f"(opcode {opcode}, frame {frame!r})")
            check("WS eco incluye el param {room}",
                  payload == b"testroom:hello",
                  f"(payload {payload!r})")
        finally:
            s.close()

        # No-match: Upgrade a una ruta WS sin ningún app_ws registrado para
        # ella → 404 HTTP bien formado (vía el formateador del framework,
        # no un tcp_write crudo).
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        try:
            _, resp, _ = ws_handshake(s, "/ws/nope")
            check("WS upgrade sin match → 404", resp.startswith(b"HTTP/1.1 404"),
                  f"({resp[:80]!r})")
            check("WS 404 bien formado (Content-Length)",
                  b"Content-Length:" in resp, f"({resp[:120]!r})")
        finally:
            s.close()

        # Request HTTP normal a la MISMA app sigue funcionando (no-regresión).
        _, status, body = get(None, "/health")
        check("GET /health tras WS → 200 ok (no-regresión)",
              status == 200 and b"ok" in body, f"(status {status})")

        # Task 3.3 — multipart/form-data E2E: POST armado a mano (boundary
        # conocido) con 1 campo de texto + 1 archivito binario (~1KB, con
        # bytes NUL/no-imprimibles) via src/multipart.nx.
        boundary = "NyxSmokeBoundary42"
        field_value = b"hello"
        file_bytes = bytes((i * 7 + 3) % 256 for i in range(1024))  # incl. NUL bytes
        mp_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="field1"\r\n\r\n'
        ).encode() + field_value + b"\r\n" + (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="upload"; filename="blob.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + file_bytes + b"\r\n" + f"--{boundary}--\r\n".encode()

        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request(
            "POST", "/multipart-demo", body=mp_body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        resp = conn.getresponse()
        mp_status = resp.status
        mp_out = resp.read()
        conn.close()
        expected_mp = f"field1::{len(field_value)}\nupload:blob.bin:{len(file_bytes)}\n".encode()
        check("POST /multipart-demo → 200", mp_status == 200, f"(status {mp_status})")
        check("POST /multipart-demo resumen exacto (names+sizes)",
              mp_out == expected_mp, f"({mp_out!r} != {expected_mp!r})")

        # req.form (fix 2026-07-22): urlencoded se parsea al Request; clave
        # ausente responde 400 (contains-primero, Map.get aborta si falta).
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("POST", "/form-demo", body="title=hola+mundo&x=1",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = conn.getresponse(); form_status = r.status; form_body = r.read(); conn.close()
        check("POST /form-demo urlencoded → 200 + valor decodificado",
              form_status == 200 and form_body == b'{"title":"hola mundo"}',
              f"({form_status} {form_body!r})")
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("POST", "/form-demo", body="x=1",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = conn.getresponse(); form2_status = r.status; r.read(); conn.close()
        check("POST /form-demo sin title → 400 (no abort)", form2_status == 400,
              f"({form2_status})")

        # req[5]==413: Content-Length sobre el cap (1MiB default) → el fast
        # parser lo señala SIN drenar el body; el worker debe responder 413
        # y CERRAR la conexión (no se manda el body: el server no lo lee).
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        try:
            s.sendall(
                b"POST /health HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Content-Length: 2097152\r\n\r\n"
            )
            s.settimeout(5)
            resp = s.recv(4096)
            check("POST body sobre el cap → 413",
                  resp.startswith(b"HTTP/1.1 413"), f"({resp[:80]!r})")
            tail = s.recv(4096)
            check("413 cierra la conexion", tail == b"", f"(tail {tail[:40]!r})")
        finally:
            s.close()
    finally:
        stop_daemon(proc)

    # Segundo daemon con --ws-catchall: exercita serve_ws(handler) (alias
    # = app_ws("*", handler)) por separado, en un puerto propio, para no
    # convertir el check de "no match → 404" de arriba en un falso-verde
    # (un catch-all "*" matchea cualquier path, así que no puede convivir
    # con ese caso en el mismo daemon).
    ws_proc = spawn_daemon(WS_CATCHALL_PORT, ["--ws-catchall"])
    try:
        check("daemon ws-catchall arriba", wait_for_port(WS_CATCHALL_PORT),
              f"(:{WS_CATCHALL_PORT} nunca abrió)")
        s = socket.create_connection(("127.0.0.1", WS_CATCHALL_PORT), timeout=5)
        try:
            _, resp, ws_left = ws_handshake(s, "/ws/anything")
            check("WS serve_ws alias → 101", resp.startswith(b"HTTP/1.1 101"),
                  f"({resp[:80]!r})")
            frame = recv_ws_frame(s, ws_left)
            opcode, payload = ws_parse_server_frame(frame)
            check("WS serve_ws alias responde", opcode == 0x1 and payload == b"legacy-ok",
                  f"(payload {payload!r})")
        finally:
            s.close()
    finally:
        stop_daemon(ws_proc)

    print(f"smoke: {passed}/{passed + failed} PASS")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
