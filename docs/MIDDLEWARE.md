# nyx-serve — Middleware Guide

Middlewares run before route handlers. They can inspect or modify the request, short-circuit with an error response, or pass through by returning `Response { status: 0, ... }`.

---

## Two kinds of middleware

nyx-serve has two distinct middleware shapes — pick based on whether you
need to act *before* the handler only, or *around* it (before **and**
after, with state carried across).

| | status-0 (`app_use` / `router_use`) | wrap (`app_wrap` / `router_wrap`) |
|---|---|---|
| Signature | `Fn(Request) -> Response` | `Fn(Request, Fn) -> Response` (second arg is `next`) |
| Runs | before the handler | around the handler (calls `next` to continue) |
| Can short-circuit | yes (non-zero status) | yes (skip calling `next`) |
| Can contribute headers on continue | yes (`headers_flat` on a `status: 0` response) | yes (mutate the `Response` `next` returns) |
| Can see/modify the final response | no | yes — `next(req)` returns the downstream `Response` |
| Can time/measure across the handler | no | yes (read a clock before and after `next`) |
| Registration order | first registered runs first | first registered is outermost |

**Rule of thumb:** if you only need to validate, short-circuit, or add a
header, `app_use`/`router_use` (status-0) is simpler and enough. If you need
to run code *after* the handler using state captured *before* it — timing,
response-body inspection, caching, tracing spans — use `app_wrap`/
`router_wrap`.

```nyx
// Wrap: times the whole downstream chain and stamps the response.
fn wrap_timing(req: Request, next: Fn) -> Response {
    let t0: int = time_us()
    let nx: Fn(Request) -> Response = next
    var resp: Response = nx(req)
    let dt: int = time_us() - t0
    resp.headers_flat.push("X-Elapsed-Us")
    resp.headers_flat.push(int_to_string(dt))
    return resp
}

app_wrap(app, wrap_timing)
```

See `docs/API.md` (`app_wrap`, Routers) for the full contract, including
router-level wraps (`router_wrap`) and the fall-through sentinel.

Requires nyx >= 0.24.24.

---

## How Middleware Works

```
Request → [mw1] → [mw2] → [mw3] → route handler → Response
                   ↑ returns status: 0 (continue)
                             ↑ returns status: 403 (short-circuit)
```

Each middleware receives a `Request` and returns a `Response`. If `status == 0`, the next middleware or route handler runs. If `status != 0`, the chain stops and that response is sent to the client.

This status-0 chain is itself just one segment of the pipeline: the whole
thing (before-hooks, this middleware chain, mounted routers, routes, static
files, the 404) runs *inside* the wrap chain — `app_wrap`s are the
outermost layer, and `next()` from the outermost wrap runs everything shown
above plus the mount/route/static/404 resolution. See "Two kinds of
middleware" above and `docs/API.md` for the full picture.

**Contributing headers while continuing** (since v0.2.2): a middleware that continues (`status: 0`) may still return headers in `headers_flat` — they are merged into the eventual response the handler produces. This lets a middleware set a `Set-Cookie` (or any header) without short-circuiting:

```nyx
fn mw_visitor(req: Request) -> Response {
    var h: Array = []
    h.push("Set-Cookie")
    h.push("visitor=1; Path=/; Max-Age=31536000")
    return Response { status: 0, headers_flat: h, body: "" }  // continues + sets cookie
}
```

Before v0.2.2 the `Response` of a continuing middleware was discarded, so header injection had to be done client-side.

---

## Registration Order

```nyx
app_use(app, mw_cors)      // runs first (handles OPTIONS)
app_use(app, my_auth_mw)   // runs second
app_use(app, my_quota_mw)  // runs third
```

---

## Built-in Middleware

### CORS

```nyx
cors_configure("*", "GET, POST, PUT, DELETE, OPTIONS", "Content-Type, Authorization")
app_use(app, mw_cors)
```

- Handles `OPTIONS` preflight: returns 204 with `Access-Control-Allow-*` headers.
- For all other methods: returns `status: 0` (continue). To add CORS headers to non-preflight responses, have the middleware include them in its `headers_flat` on the continue path (see "Contributing headers while continuing" above) — the dispatcher now merges them into the response.

### Logging

There is **no** built-in access logging in nyx-serve. (The `mw_logging`
symbol exported by `std/web` is a dead no-op stub — registering it does
nothing; don't.) If you need request logging, write your own middleware
(see "Request Logging with Body" below) or an `app_after` hook that prints
`req`/`resp`.

---

## Custom Middleware Examples

### Authentication

```nyx
fn mw_auth(req: Request) -> Response {
    let token: String = req.cookies.get("session_id")
    if token.length() == 0 {
        return response_json(401, "{\"error\": \"authentication required\"}")
    }
    // In a real app: validate token against nyx-kv
    let hdrs: Array = []
    return Response { status: 0, headers_flat: hdrs, body: "" }
}

app_use(app, mw_auth)
```

### Rate Limiting

```nyx
var __rate_count: Map = map_new()
var __rate_ts: Map = map_new()
let RATE_LIMIT: int = 100

fn mw_rate_limit(req: Request) -> Response {
    let ip: String = http_find_header(req.headers_flat, "X-Forwarded-For")
    let now_us: int = time_us()
    let last_us: int = map_get_int(__rate_ts, ip)
    if now_us - last_us > 1000000 {
        __rate_ts.insert(ip, int_to_string(now_us))
        __rate_count.insert(ip, "1")
    } else {
        let count: int = map_get_int(__rate_count, ip)
        if count >= RATE_LIMIT {
            return response_json(429, "{\"error\": \"rate limit exceeded\"}")
        }
        __rate_count.insert(ip, int_to_string(count + 1))
    }
    let hdrs: Array = []
    return Response { status: 0, headers_flat: hdrs, body: "" }
}
```

### Request Logging with Body

```nyx
fn mw_debug_log(req: Request) -> Response {
    print("[debug] " + req.method + " " + req.path + " body=" + req.body)
    let hdrs: Array = []
    return Response { status: 0, headers_flat: hdrs, body: "" }
}
```

### Security Headers

```nyx
// Two options: add them in the route handler (below), or set them on a
// continuing middleware's headers_flat so they apply to every response
// (see "Contributing headers while continuing").
fn handle_sensitive(req: Request) -> Response {
    let hdrs: Array = [
        "X-Frame-Options", "DENY",
        "X-Content-Type-Options", "nosniff",
        "Strict-Transport-Security", "max-age=31536000"
    ]
    return Response { status: 200, headers_flat: hdrs, body: data }
}
```

---

## Before / After Hooks

In addition to middlewares, the dispatcher runs two hook chains (wired in v0.2.2):

- **`app_before(app, hook)`** — `hook: Fn(Request) -> Response`. Runs *before* middlewares. Same contract as a middleware: return `status: 0` to continue (and optionally contribute headers), or a non-zero status to short-circuit.
- **`app_after(app, hook)`** — `hook: Fn(Request, Response) -> Response`. Runs *after* the final response is resolved (route handler, static file, short-circuit, or 404), but before it is serialized. Each after-hook sees the final `(req, resp)` and returns a possibly-modified `Response`. Use it to observe or stamp the response — access logs, analytics by status code, request-id headers.

```nyx
fn hook_request_id(req: Request, resp: Response) -> Response {
    resp.headers_flat.push("X-Request-Id")
    resp.headers_flat.push(gen_id())      // your id generator
    return resp
}
app_after(app, hook_request_id)           // applies to every response
```

After-hooks run on **every** response path, including redirects and short-circuited middleware responses.

---

## Limitations

- Middlewares/before-hooks can **read** the request but cannot **modify** it before passing it to the next stage (the `Request` struct is passed by value).
- A continuing (`status: 0`) middleware/before-hook can now contribute **headers** to the eventual response (v0.2.2), but its `body` is still ignored. To rewrite the body or status of an already-resolved response, use an `app_after` hook.
- A middleware/hook/handler that panics or throws is caught by the dispatcher and turned into a 500 (see `app_error` in API.md) — it no longer kills the process (since v0.4.0).
