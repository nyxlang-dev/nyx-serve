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
    app_use(app, mw_logging())
    app_use(app, mw_cors("*"))
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

## Documentation

- [`docs/API.md`](docs/API.md) — Full public API reference
- [`docs/EXAMPLES.md`](docs/EXAMPLES.md) — Annotated usage examples
- [`docs/MIDDLEWARE.md`](docs/MIDDLEWARE.md) — Built-in middleware reference

## Limitations

- HTTP/1.1 only — for HTTP/2 use [nyx-http2](../http2/)
- No stateful WebSocket handlers
- No automatic response compression
- Cookie sessions depend on an external `nyx-kv` instance

## License

Apache 2.0 — see [LICENSE](./LICENSE)
