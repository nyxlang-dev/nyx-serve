# nyx-serve — Middleware Guide

Middlewares run before route handlers. They can inspect or modify the request, short-circuit with an error response, or pass through by returning `Response { status: 0, ... }`.

---

## How Middleware Works

```
Request → [mw1] → [mw2] → [mw3] → route handler → Response
                   ↑ returns status: 0 (continue)
                             ↑ returns status: 403 (short-circuit)
```

Each middleware receives a `Request` and returns a `Response`. If `status == 0`, the next middleware or route handler runs. If `status != 0`, the chain stops and that response is sent to the client.

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
app_use(app, mw_logging)   // runs second
app_use(app, my_auth_mw)   // runs third
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

```nyx
app_use(app, mw_logging)
```

`mw_logging` is a **no-op** — it always returns `status: 0` with no headers
and prints nothing. There is no automatic access logging in nyx-serve today.
If you need request logging, write your own middleware (see "Request
Logging with Body" below) or an `app_after` hook that prints `req`/`resp`.

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
