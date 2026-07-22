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

| Flag | Default | Description |
|------|---------|-------------|
| `--port <N>` | `3000` | TCP port to listen on |

Server workers are set programmatically via `serve_app(app, port, workers)`.

**Cookie sessions** require a running `nyx-kv` instance (via `std/session.nx`).

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
  (do their own handshake/read/write/close loop) — there's no built-in
  broadcast/pub-sub primitive across connections, and each connection is
  served by whichever worker accepted it (no separate WS event loop)
- `multipart_parse` is a standalone helper — it does **not** populate
  `req.form`; call it explicitly from the handler with the raw body and
  `Content-Type` header
- Requests over `NYX_HTTP_MAX_BODY` (default 1 MiB) are rejected with an
  automatic `413` before the handler ever sees them — there's no per-route
  override

## License

Apache 2.0 — see [LICENSE](./LICENSE)
