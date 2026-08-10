#!/usr/bin/env python3
"""Smoke test de nyx-serve: daemon efímero (examples/standalone.nx) + HTTP.

Corre con `make test-serve`. No requiere red externa ni nyx-kv.
El binario se toma de NYX_SERVE_BIN o ./nyx-serve (raíz del stack).
"""
import base64
import hashlib
import http.client
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

PORT = int(os.environ.get("SERVE_SMOKE_PORT", "13080"))
WS_CATCHALL_PORT = int(os.environ.get("SERVE_SMOKE_WS_PORT", "13081"))
AL_PORT = int(os.environ.get("SERVE_SMOKE_AL_PORT", "13082"))
SH_PORT = int(os.environ.get("SERVE_SMOKE_SH_PORT", "13083"))
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


def get_on(port, path):
    """Variante de get() parametrizada por puerto (para daemons en puertos
    distintos de PORT, p.ej. el daemon --access-log)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
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
    # v0.6.0: NYX_SERVE_DRAIN_SECS=0 fuerza teardown inmediato (sin espera de
    # drain) en TODOS los daemons de este módulo excepto el de
    # spawn_daemon_capture (el único que ejercita el drain con deadline
    # corto) — si no, cada stop_daemon() de acá abajo pagaría el deadline
    # completo (default 10s) y el smoke entero se enlentecería.
    env = dict(os.environ, NYX_SERVE_DRAIN_SECS="0")
    proc = subprocess.Popen(
        [BINARY, "--port", str(port)] + (extra_args or []),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
        env=env,
    )
    return proc


def spawn_daemon_capture(port, extra_args=None):
    """Como spawn_daemon, pero con stdout capturado (access-log) y
    NYX_SERVE_DRAIN_SECS=3 para ejercitar el drain con un deadline corto en
    vez de esperar el default de 10s."""
    env = dict(os.environ, NYX_SERVE_DRAIN_SECS="3")
    proc = subprocess.Popen(
        [BINARY, "--port", str(port)] + (extra_args or []),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
        env=env,
    )
    return proc


def stop_daemon(proc):
    # NYX_SERVE_DRAIN_SECS=0 (spawn_daemon) → drain sin espera: el sentinel
    # se envía y el proceso sale casi de inmediato, así que este
    # proc.wait(timeout=5) sigue siendo holgado incluso con el drain nuevo.
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

        # Bug 3: app_after cableado — X-Request-Id en toda respuesta (incl. 302).
        # Bloqueador 3: el valor es real (wrap_reqid vía ctx), no un placeholder
        # fijo — basta con "presente y con la forma req-N" acá; la coherencia
        # exacta body/header se prueba más abajo con /ctx-demo.
        check("after-hook X-Request-Id en redirect",
              (hdrs.get("x-request-id") or "").startswith("req-"),
              f"(x-request-id {hdrs.get('x-request-id')!r})")
        _, _, hdrs_root = get_h("/")
        check("after-hook X-Request-Id en 200",
              (hdrs_root.get("x-request-id") or "").startswith("req-"),
              f"(x-request-id {hdrs_root.get('x-request-id')!r})")

        # Bug 2: middleware que continúa (status 0) aporta cabeceras downstream
        check("middleware continue aporta X-Mw",
              hdrs_root.get("x-mw") == "seen",
              f"(x-mw {hdrs_root.get('x-mw')!r})")

        # Bloqueador 1 — 404 custom (app_not_found)
        _, status, body = get(None, "/definitely-not-a-route")
        check("404 custom (JSON de app_not_found)",
              status == 404 and b'"error":"not found"' in body
              and b"/definitely-not-a-route" in body,
              f"(status {status} body {body[:80]!r})")

        # Bloqueador 1 — panic en handler → 500 custom (app_error), no muerte
        _, status, body = get(None, "/panic")
        check("GET /panic → 500 custom via app_error",
              status == 500 and b"boom-standalone" in body,
              f"(status {status} body {body[:80]!r})")

        # El check que antes era imposible: el proceso sigue vivo tras el panic
        _, status, body = get(None, "/health")
        check("server vivo tras panic (worker no murió)",
              status == 200 and b"ok" in body, f"(status {status})")

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
            _, resp, ws_nope_body = ws_handshake(s, "/ws/nope")
            check("WS upgrade sin match → 404", resp.startswith(b"HTTP/1.1 404"),
                  f"({resp[:80]!r})")
            check("WS 404 bien formado (Content-Length)",
                  b"Content-Length:" in resp, f"({resp[:120]!r})")
            # ws_handshake solo devuelve las cabeceras en `resp`; el body
            # (leftover del mismo recv, o el resto si llegó separado) viaja
            # en el tercer valor de retorno.
            cl_match = None
            for line in resp.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    cl_match = int(line.split(b":", 1)[1].strip())
            expected_len = cl_match or 0
            s.settimeout(5)
            try:
                while len(ws_nope_body) < expected_len:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    ws_nope_body += chunk
            except socket.timeout:
                # Server sent fewer bytes than Content-Length promised — stop
                # reading and let the check below fail cleanly on what we got.
                pass
            check("WS 404 usa el handler custom", b'"error":"not found"' in ws_nope_body,
                  f"({ws_nope_body[:120]!r})")
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
        # Bloqueador 2 — wrap global de timing: toda respuesta lleva X-Elapsed-Us
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        elapsed = resp.getheader("X-Elapsed-Us")
        resp.read()
        conn.close()
        check("wrap timing: X-Elapsed-Us presente y numerico",
              elapsed is not None and elapsed.isdigit(), f"({elapsed!r})")

        # Bloqueador 2 — short-circuit + composicion onion: el 418 del wrap
        # interno sale envuelto por el timing (header presente igual)
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/teapot")
        resp = conn.getresponse()
        tp_status = resp.status
        tp_elapsed = resp.getheader("X-Elapsed-Us")
        tp_body = resp.read()
        conn.close()
        check("wrap short-circuit → 418", tp_status == 418, f"(status {tp_status})")
        check("composicion onion: 418 con X-Elapsed-Us",
              tp_elapsed is not None, f"({tp_elapsed!r})")

        # Bloqueador 2 — mount /priv con auth propia
        _, status, body = get(None, "/priv/users/7")
        check("mount /priv sin token → 401", status == 401, f"(status {status})")

        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/priv/users/7", headers={"X-Token": "secreto"})
        resp = conn.getresponse()
        au_status = resp.status
        au_body = resp.read()
        conn.close()
        check("mount /priv con token → 200 con {id} del router",
              au_status == 200 and b'"user":"7"' in au_body,
              f"(status {au_status} body {au_body[:60]!r})")

        # Bloqueador 2 — router sin auth + fall-through al 404 del APP
        _, status, body = get(None, "/pub/hello")
        check("mount /pub → 200", status == 200 and b'"pub":"hello"' in body,
              f"(status {status})")
        _, status, body = get(None, "/pub/no-existe")
        check("fall-through: /pub/no-existe → 404 custom del app",
              status == 404 and b'"error":"not found"' in body,
              f"(status {status} body {body[:60]!r})")

        # Bloqueador 2 — router_wrap de /pub: estampa header al salir, pero
        # respeta el sentinel status 0 en el fall-through (no lo toca).
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/pub/hello")
        resp = conn.getresponse()
        rw_status = resp.status
        rw_header = resp.getheader("X-Pub-Wrap")
        resp.read()
        conn.close()
        check("router_wrap /pub: /pub/hello → 200 con X-Pub-Wrap",
              rw_status == 200 and rw_header == "1",
              f"(status {rw_status} header {rw_header!r})")

        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/pub/no-existe")
        resp = conn.getresponse()
        rwnf_status = resp.status
        rwnf_header = resp.getheader("X-Pub-Wrap")
        resp.read()
        conn.close()
        check("router_wrap /pub: fall-through a 404 sin X-Pub-Wrap (sentinel intacto)",
              rwnf_status == 404 and rwnf_header is None,
              f"(status {rwnf_status} header {rwnf_header!r})")

        # Bloqueador 2 — fall-through a una ruta REAL del app bajo el
        # prefijo mounted /pub: prueba que el path original (no el
        # despojado por el mount) es el que matchea.
        _, status, body = get(None, "/pub/extra")
        check("fall-through a ruta real del app bajo /pub (path original preservado)",
              status == 200 and b'"app":"extra"' in body,
              f"(status {status} body {body[:60]!r})")

        # Bloqueador 3 — Request.ctx: el wrap escribe, el handler lee (body),
        # el after-hook estampa (header). Body y header deben COINCIDIR: el
        # after-hook ve el ctx que escribió el wrap pese a recibir el Request
        # "original" (mismo Map por referencia).
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/ctx-demo")
        resp = conn.getresponse()
        ctx1_hdr = resp.getheader("X-Request-Id")
        ctx1_body = resp.read()
        conn.close()
        check("ctx: wrap→handler→after-hook coherente",
              ctx1_hdr is not None and ctx1_hdr != "MISSING"
              and f'"request_id":"{ctx1_hdr}"'.encode() in ctx1_body,
              f"(hdr {ctx1_hdr!r} body {ctx1_body[:60]!r})")

        # Dos requests secuenciales (no concurrentes) obtienen ids distintos.
        # La garantía fuerte de que ctx nunca se comparte entre requests
        # concurrentes la fija test-340 del lang; esto es el smoke E2E.
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        conn.request("GET", "/ctx-demo")
        resp = conn.getresponse()
        ctx2_hdr = resp.getheader("X-Request-Id")
        resp.read()
        conn.close()
        check("ctx: requests secuenciales obtienen ids distintos",
              ctx2_hdr is not None and ctx2_hdr != ctx1_hdr,
              f"({ctx1_hdr!r} vs {ctx2_hdr!r})")
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

    # ── v0.6.0: access-log estructurado + graceful drain ──
    proc_al = spawn_daemon_capture(AL_PORT, ["--access-log"])
    try:
        check("daemon access-log arriba", wait_for_port(AL_PORT), "")
        _, status, _ = get_on(AL_PORT, "/health")
        check("access-log: GET responde", status == 200, f"({status})")

        # 8 requests concurrentes a /health: cada línea de access-log ahora se
        # escribe con term_write(sb + "\n") + term_flush() en una sola llamada
        # de write — reemplaza el print() de dos llamadas stdio (payload,
        # "\n") que bajo concurrencia real podía intercalar líneas de dos
        # workers. Se valida más abajo, contra el stdout completo capturado
        # (post-wait), que TODAS las líneas '{' parsean como JSON individual.
        concurrent_errors = []
        def burst():
            try:
                _, st, _ = get_on(AL_PORT, "/health")
                if st != 200:
                    concurrent_errors.append(st)
            except Exception as e:
                concurrent_errors.append(str(e))
        burst_threads = [threading.Thread(target=burst) for _ in range(8)]
        for th in burst_threads:
            th.start()
        for th in burst_threads:
            th.join(timeout=10)

        # SIGTERM con un request lento EN VUELO: el drain debe dejarlo terminar
        slow_result = {}
        def do_slow():
            try:
                conn = http.client.HTTPConnection("127.0.0.1", AL_PORT, timeout=10)
                conn.request("GET", "/slow")
                r = conn.getresponse()
                slow_result["status"] = r.status
                slow_result["body"] = r.read()
                conn.close()
            except Exception as e:
                slow_result["error"] = str(e)
        t = threading.Thread(target=do_slow); t.start()
        time.sleep(0.5)                       # el request ya está en vuelo
        proc_al.send_signal(signal.SIGTERM)
        t.join(timeout=10)
        check("drain: request en vuelo completa tras SIGTERM",
              slow_result.get("status") == 200 and b"done" in slow_result.get("body", b""),
              f"({slow_result})")

        # el proceso sale solo, con código 0, antes del deadline
        try:
            rc = proc_al.wait(timeout=12)
            check("drain: proceso sale solo con exit 0", rc == 0, f"(rc {rc})")
        except subprocess.TimeoutExpired:
            proc_al.kill()
            proc_al.wait()
            check("drain: proceso sale solo con exit 0", False, "(timeout)")

        # la línea de access-log del /health es JSON parseable con los campos
        out = proc_al.stdout.read().decode(errors="replace")
        al_lines = [l for l in out.splitlines() if l.startswith("{")]
        parsed = None
        for l in al_lines:
            try:
                j = json.loads(l)
                if j.get("path") == "/health":
                    parsed = j
                    break
            except ValueError:
                pass
        check("access-log: linea JSON valida con campos",
              parsed is not None and parsed.get("method") == "GET"
              and parsed.get("status") == 200 and isinstance(parsed.get("dur_us"), int),
              f"(lines {al_lines[:2]!r})")

        # interleaving: con el write atómico (term_write+term_flush), las
        # ~10 líneas generadas (1 GET inicial + 8 concurrentes + 1 /slow) por
        # workers concurrentes deben parsear TODAS como JSON individual —
        # ninguna corrupta/mezclada con otra.
        bad_lines = []
        for l in al_lines:
            try:
                json.loads(l)
            except ValueError:
                bad_lines.append(l)
        check("access-log: 8 requests concurrentes sin interleaving (todas las lineas JSON parsean)",
              len(concurrent_errors) == 0 and len(bad_lines) == 0 and len(al_lines) >= 8,
              f"(errors={concurrent_errors} bad={bad_lines[:3]!r} total_lines={len(al_lines)})")
    finally:
        if proc_al.poll() is None:
            proc_al.kill()
            proc_al.wait()

    # ── v0.6.1: serve_on_shutdown ──
    marker = os.path.join(ROOT, ".smoke_shutdown_marker")
    if os.path.exists(marker):
        os.remove(marker)
    proc_sh = spawn_daemon_capture(SH_PORT, ["--shutdown-marker", marker])
    try:
        check("daemon shutdown-hook arriba", wait_for_port(SH_PORT), "")
        proc_sh.send_signal(signal.SIGTERM)
        try:
            rc = proc_sh.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc_sh.kill()
            proc_sh.wait()
            rc = None
        sh_out = proc_sh.stdout.read().decode(errors="replace")
        check("shutdown hooks: panic del 1ro no impide exit 0 ni al 2do",
              rc == 0 and os.path.exists(marker)
              and "shutdown hook failed" in sh_out,
              f"(rc {rc} marker {os.path.exists(marker)} out {sh_out[-200:]!r})")
        check("shutdown hooks: marcador con contenido esperado",
              os.path.exists(marker) and open(marker).read() == "shutdown-ok",
              "")
    finally:
        if proc_sh.poll() is None:
            proc_sh.kill()
            proc_sh.wait()
        if os.path.exists(marker):
            os.remove(marker)

    print(f"smoke: {passed}/{passed + failed} PASS")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
