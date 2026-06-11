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
- For all other methods: returns `status: 0` (continue) — CORS headers are added to the final response by the dispatch loop.

### Logging

```nyx
app_use(app, mw_logging)
```

Logs: `GET /path → 200 (3ms)` to stdout. This is a marker middleware — logging is performed by the dispatch loop after the handler returns.

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
// Note: security headers are best added in the response, not as a middleware
// since middleware can only short-circuit — it cannot modify the response.
// Add headers directly in route handlers:
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

## Limitations

- Middlewares can **read** the request but cannot **modify** it before passing it to the next middleware (the `Request` struct is passed by value).
- Middlewares cannot add headers to the eventual response — only the route handler controls the response headers. To add headers to all responses, use `app_after` hooks (experimental).
- The `body` field in a `continue` response (`status: 0`) is ignored.
