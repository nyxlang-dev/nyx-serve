# nyx-serve

HTTP web framework **library** for [Nyx](https://nyxlang.com). Wraps the `App`
framework from `std/web` with a multi-threaded keep-alive server, middleware
chain, cookie sessions, and path-prefix static file serving with MIME detection.
Add it as a dependency in `nyx.toml` — it is not a standalone daemon.

Librería de framework HTTP para [Nyx](https://nyxlang.com). Envuelve el framework
`App` de `std/web` con un servidor multi-threaded keep-alive, cadena de middlewares,
cookie sessions y servicio de archivos estáticos. Se consume como dependencia en
`nyx.toml` — no es un daemon independiente.

---

## Philosophy

nyx-serve follows the Flask/Werkzeug layering: **power lives in the language**
(`std/web` owns the vocabulary — `Request`, `Response`, `App`, routing,
response helpers — and grows capabilities there), while **nyx-serve
facilitates**: a ready-to-run server, the dispatcher, and the ergonomics for
building apps, pages and APIs. It wraps the standard library; it never
replaces it. Framework-layer issues (server, dispatcher, WS, templates,
static, multipart) belong here; vocabulary gaps belong to the language
toolchain ([nyxlang.com](https://nyxlang.com)).

**Filosofía**: capas estilo Flask/Werkzeug — el poder vive en el lenguaje
(`std/web` es dueño del vocabulario y crece allá); nyx-serve facilita
(servidor listo, dispatcher, ergonomía). Envuelve la stdlib, nunca la
reemplaza. Issues de framework van acá; huecos de vocabulario, al repo del
lenguaje.

## Install

Install the Nyx toolchain:

```bash
curl -sSf https://nyxlang.com/install.sh | sh
```

## Quick start

```bash
git clone https://github.com/nyxlang-dev/nyx-serve
cd nyx-serve
nyx build
./nyx-serve   # smoke test on :8080
```

## Usage

Declare the dependency in your project:

```toml
# nyx.toml
[package]
name = "my-site"
main = "src/main.nx"

[dependencies]
nyx-serve = "*"
```

Wire routes and start the server:

```nyx
import "std/web"
import "nyx-serve/src/server"
import "nyx-serve/src/files"

fn handle_index(req: Request) -> Response {
    return response_html(200, read_file("static/index.html"))
}

fn main() {
    let app: App = app_new()
    cors_configure("*", "GET, POST, OPTIONS", "Content-Type, Authorization")
    app_use(app, mw_cors)
    app_get(app, "/", handle_index)
    app_static(app, "/assets/", "static/assets/")
    serve_app(app, 3000, 16)
}
```

Serve JSON:

```nyx
fn handle_api(req: Request) -> Response {
    let body: Map = req_json(req)
    return response_json_map(200, body)
}
```

Expected output on startup:

```
[nyx-serve] listening on :3000 (16 workers)
```

## Configuration

Flags of the smoke-test binary built from `examples/standalone.nx` (a
library consumer picks its own port in `serve_app`):

| Flag | Default | Description |
|------|---------|-------------|
| `--port <N>` | `8080` | TCP port to listen on |

Server workers are set programmatically via `serve_app(app, port, workers)`.

**Cookie sessions** require a running `nyx-kv` instance (via `std/session.nx`).

## What's new in v0.7.0

- **WebSocket rooms & broadcast** (`src/ws`): a mutex-guarded registry of
  live connections (`fd <-> room`) layered on top of `app_ws` — `ws_join`/
  `ws_accept(fd, room, headers)` register a connection and spawn a
  dedicated reader thread (close/EOF detection only; push-only by design,
  upstream frames are never delivered), `ws_broadcast(room, payload)` sends
  to every connection in a room with serialized writes (frames never
  interleave on a fd), `ws_leave(fd)` evicts a connection explicitly, and
  `ws_count`/`ws_count_room` report live connections. `ws_accept` collapses
  a typical handler to three lines. On `SIGTERM`, registered connections now
  get drain courtesy (close frame + fd close) before `serve_on_shutdown`
  hooks run, ahead of any consumer snapshot. See `docs/API.md`.

**Novedades en v0.7.0**: salas y broadcast de WebSocket (`src/ws`) — un
registro de conexiones vivas (`fd <-> sala`) protegido por mutex, encima de
`app_ws`. `ws_join`/`ws_accept(fd, sala, headers)` registran una conexión y
lanzan un thread lector dedicado (solo detecta close/EOF; push-only por
diseño, no entrega frames entrantes), `ws_broadcast(sala, payload)` envía a
todas las conexiones de una sala con escrituras serializadas (los frames
nunca se interleavean en un mismo fd), `ws_leave(fd)` expulsa una conexión
explícitamente, y `ws_count`/`ws_count_room` reportan conexiones vivas.
`ws_accept` reduce un handler típico a tres líneas. En `SIGTERM`, las
conexiones registradas ahora reciben cortesía de drain (frame de cierre +
cierre de fd) antes de que corran los hooks de `serve_on_shutdown`, previo a
cualquier snapshot del consumer. Ver `docs/API.md`.

## What's new in v0.6.1

- **Shutdown hooks**: `serve_on_shutdown(handler)` registers a cleanup
  callback (`Fn() -> int`) that runs during the SIGTERM drain — in
  registration order, after the drain deadline (workers are quiet, so state
  is consistent for snapshots) and before `serve_app` returns `0`. Runs in
  normal context (allocation/printing/disk writes are fine). A panicking
  hook is logged and does not block the remaining hooks or the exit-0
  contract. Only fires on the SIGTERM drain — not on SIGKILL. Register
  before calling `serve_app`. Use case: flushing in-memory state to disk on
  shutdown.

**Novedades en v0.6.1**: hooks de shutdown — `serve_on_shutdown(handler)`
registra un callback de limpieza que corre durante el drain de `SIGTERM`,
en orden de registro, después del deadline (workers quietos, estado
consistente para snapshots) y antes de que `serve_app` retorne `0`. Corre en
contexto normal (alocar/imprimir/escribir a disco es seguro). Un hook que
paniquea se loguea y no bloquea a los demás ni el contrato de exit-0. Solo
corre en el drain de `SIGTERM`, no en `SIGKILL`. Registrar antes de llamar a
`serve_app`. Caso de uso: volcar estado en memoria a disco al apagar.

## What's new in v0.6.0

- **Graceful shutdown**: `serve_app` now handles `SIGTERM` — closes the
  listener immediately (waking the accept loop), lets in-flight requests on
  every keep-alive worker finish and close their connection, then exits `0`
  after the **full** `NYX_SERVE_DRAIN_SECS` deadline (default `10`s) — the
  runtime has no worker join, so it always waits the whole deadline, it does
  not return early once workers are idle. Tune `NYX_SERVE_DRAIN_SECS` down
  for fast redeploys (`0` = exit immediately, no drain wait). Requires nyx
  >= 0.24.26.
- **Structured access log**: `app_access_log(&mut app)` (from `std/web`)
  opts into one JSON line per request on stdout — `ts`, `method`, `path`,
  `status`, `dur_us`, `bytes`, and `request_id` when set upstream. See
  `docs/API.md` and `docs/MIDDLEWARE.md`.
- nyx-serve does not rate-limit; deploy behind a rate-limiting proxy such as
  nyx-proxy.

**Novedades en v0.6.0**: apagado ordenado (`serve_app` maneja `SIGTERM` —
cierra el listener, deja terminar los requests en vuelo de cada worker
keep-alive y sale con `0` tras esperar el deadline COMPLETO de
`NYX_SERVE_DRAIN_SECS` (default 10s) — el runtime no hace join de workers,
así que siempre espera el deadline entero, no vuelve antes si los workers ya
terminaron; tuneá `NYX_SERVE_DRAIN_SECS` a la baja para redeploys rápidos (0
= salida inmediata sin espera; requiere nyx >= 0.24.26)
y access log estructurado (`app_access_log`, una línea JSON por request con
`ts`/`method`/`path`/`status`/`dur_us`/`bytes`/`request_id` opcional).
nyx-serve no hace rate limiting; desplegar detrás de un proxy con rate
limiting como nyx-proxy.

## What's new in v0.5.1

- **Per-request `ctx`**: every `Request` carries a `ctx: Map` — write once in
  a wrap or middleware, read it back in the route handler, `app_after` hooks,
  and `app_error`. It's shared by reference across the per-layer `Request`
  copies, and each request gets its own (never shared across requests).
  Requires nyx >= 0.24.25.

**Novedades en v0.5.1**: `ctx` por-request — escribilo una vez en un wrap o
middleware y leelo en el handler, los hooks `app_after` y `app_error`. Se
comparte por referencia entre las copias del `Request` de cada capa, y cada
request tiene el suyo propio (nunca compartido entre requests). Requiere
nyx >= 0.24.25.

## What's new in v0.5.0

- **Wrapping middleware** (`app_wrap(app, mw)`, `mw: Fn(Request, Fn) -> Response`):
  runs *around* the rest of the pipeline instead of only before it — call
  `next(req)` to run everything downstream and get its `Response` back, so a
  wrap can time, cache, or modify the response, not just short-circuit or add
  headers. Wraps compose onion-style in registration order (first registered
  is outermost).
- **Mountable routers** (`router_new`, `router_get`/`post`/`put`/`delete`/
  `route`, `router_use`, `router_wrap`, `app_mount(app, prefix, router)`): a
  `Router` carries its own routes, status-0 middlewares and wraps, scoped
  under a literal path prefix. Mounts are checked before the app's own
  routes, and fall through to them (then static files, then 404) when the
  router doesn't handle the request. Requires nyx >= 0.24.24.

**Novedades en v0.5.0**: middleware envolvente (`app_wrap`, con `next` para
correr el resto del pipeline y ver/modificar la `Response`, no solo cortar o
agregar headers) y routers montables (`Router`, `router_get`/`use`/`wrap`,
`app_mount`) con su propio stack de rutas/middlewares/wraps bajo un prefijo,
chequeados antes que las rutas del app y con fall-through si no matchean.
Requiere nyx >= 0.24.24.

## What's new in v0.4.0

- **Registrable error handlers**: `app_not_found(app, handler)` replaces the
  default 404 page (HTTP and unmatched WebSocket upgrades);
  `app_error(app, handler)` turns handler panics/throws into a custom 500 —
  a panicking handler no longer kills the server process. Requires
  nyx >= 0.24.19.

**Novedades en v0.4.0**: handlers de error registrables — `app_not_found`
reemplaza la página 404 (HTTP y upgrades WS sin match) y `app_error`
convierte panics/throws de handlers en un 500 propio: un handler que
panickea ya no mata el proceso. Requiere nyx >= 0.24.19.

## What's new in v0.3.0

- **WebSockets** (`app_ws`): route-matched WS upgrade handlers with the same
  `{param}`/`*` pattern syntax as HTTP routes.
- **Templates** (`src/template.nx`): `tpl_render` — `{{key}}` (HTML-escaped),
  `{{{key}}}` (raw), `{{#if}}/{{else}}`, `{{#each}}` (nested), `{{> partial}}`.
- **Multipart parsing** (`src/multipart.nx`): binary-safe `multipart_parse` +
  `part_name`/`part_filename`/`part_ctype`/`part_value` accessors.
- **Automatic 413**: requests over `NYX_HTTP_MAX_BODY` (default 1 MiB) are
  rejected with `413 Payload Too Large` + `Connection: close` before the body
  is read — no handler code needed.
- **ETag / cached static serving**: `app_static_cached` adds `Cache-Control`
  + `Last-Modified`; `compute_weak_etag`/`apply_etag` collapse matching
  `If-None-Match` requests to `304`.
- **Set-Cookie on redirects**: headers set on a `301`/`302`/`303`/`307`/`308`
  `Response` (e.g. `Set-Cookie`) now travel with the redirect instead of being
  dropped.

**Novedades en v0.3.0**: WebSockets (`app_ws`, mismo matcher `{param}`/`*` que
las rutas HTTP), motor de templates (`tpl_render` con `{{key}}` escapado,
`{{{key}}}` crudo, `{{#if}}/{{else}}`, `{{#each}}` anidable, `{{> partial}}`),
parser multipart binary-safe (`multipart_parse` + accessors `part_*`), 413
automático sobre `NYX_HTTP_MAX_BODY` (default 1MiB, sin código de handler),
archivos estáticos con ETag/caching (`app_static_cached`, `compute_weak_etag`,
`apply_etag`) y headers (`Set-Cookie` incluido) que ahora sí viajan en
redirects 3xx.

## Documentation

- [`docs/API.md`](docs/API.md) — Full public API reference
- [`docs/EXAMPLES.md`](docs/EXAMPLES.md) — Annotated usage examples
- [`docs/MIDDLEWARE.md`](docs/MIDDLEWARE.md) — Built-in middleware reference

## Limitations

- HTTP/1.1 only — for HTTP/2 use [nyx-http2](../http2/)
- No automatic response compression
- Cookie sessions depend on an external `nyx-kv` instance
- `app_ws` handlers take full ownership of the socket fd once they return `1`
  (do their own handshake/read/write/close loop); `src/ws` layers rooms and
  broadcast on top, but it's push-only — there are no client-side frame
  helpers, and upstream messages from the client are not delivered to your
  code (validate client input over a plain HTTP route instead). Each
  connection is served by whichever worker accepted it (no separate WS
  event loop)
- `multipart_parse` is a standalone helper — it does **not** populate
  `req.form`; call it explicitly from the handler with the raw body and
  `Content-Type` header
- Requests over `NYX_HTTP_MAX_BODY` (default 1 MiB) are rejected with an
  automatic `413` before the handler ever sees them — there's no per-route
  override
- Mounts/wraps do not apply to WebSocket upgrades; no per-router static
  serving
- No built-in rate limiting — deploy behind a rate-limiting proxy such as
  nyx-proxy

## License

Apache 2.0 — see [LICENSE](./LICENSE)
