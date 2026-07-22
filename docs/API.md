# nyx-serve — API Reference

The `App`/`Request`/`Response` framework (routes, middleware, hooks, response
constructors, parsing helpers) is exported from `std/web` — import it with
`import "std/web"`. The pieces that are specific to this library (the
multi-threaded server, WebSockets, static file serving with ETag/caching,
templates, and multipart parsing) live in `src/` and are imported from a
consumer project as `import "nyx-serve/src/server"`,
`import "nyx-serve/src/files"`, `import "nyx-serve/src/template"`, and
`import "nyx-serve/src/multipart"` respectively — each section below says
which one it comes from.

---

## App

### `app_new() -> App`

Create a new application instance.

```nyx
let app: App = app_new()
```

---

### `app_route(app: App, method: String, pattern: String, handler: Fn)`

Register a route for any HTTP method.

---

### `app_get(app: App, pattern: String, handler: Fn)`
### `app_post(app: App, pattern: String, handler: Fn)`
### `app_put(app: App, pattern: String, handler: Fn)`
### `app_delete(app: App, pattern: String, handler: Fn)`

Register a route for GET, POST, PUT, DELETE respectively.

**Pattern syntax**:
- `/path/to/resource` — exact match
- `/users/{id}` — captures `id` into `req.params`
- `/files/*` — wildcard, matches any suffix

---

### `app_use(app: App, mw: Fn(Request) -> Response)`

Register a middleware function. Runs before route handlers in registration order. Return `status: 0` to continue (headers in `headers_flat` are merged into the downstream response, since v0.2.2) or a non-zero status to short-circuit.

---

### `app_before(app: App, hook: Fn(Request) -> Response)`

Register a hook that runs **before** middlewares. Same contract as a middleware: `status: 0` continues (and may contribute headers), non-zero short-circuits.

### `app_after(app: App, hook: Fn(Request, Response) -> Response)`

Register a hook that runs **after** the final response is resolved (every path: route, static, short-circuit, 404), before serialization. Receives `(req, resp)` and returns a possibly-modified `Response`. Use for access logs, analytics by status, or stamping headers (e.g. request-id). See `docs/MIDDLEWARE.md`.

---

## Server

### `serve_app(app: App, port: int, workers: int)`

Start the server. Blocks forever. Spawns `workers` goroutines in a keep-alive connection pool.

From `nyx-serve/src/server`:

```nyx
import "nyx-serve/src/server"
serve_app(app, 3000, 64)
```

Requests whose body exceeds `NYX_HTTP_MAX_BODY` (default 1 MiB) are rejected
automatically with `413 Payload Too Large` + `Connection: close` — the body
is never read or drained (anti-DoS), and the handler never runs.

---

## WebSockets

From `nyx-serve/src/server`.

### `app_ws(pattern: String, handler: Fn(Array) -> int)`

Registers a WebSocket upgrade handler for a route pattern. Uses the **same**
`{param}`/`*` matcher as `app_get`/`app_post`/etc.

The handler receives a single `Array` argument shaped
`[fd, path, headers_flat, params_pairs_flat]`:

| Index | Type | Description |
|-------|------|-------------|
| `0` | int | The raw socket fd |
| `1` | String | The request path |
| `2` | Array | Interleaved request headers (`["Header-Name", "value", ...]`) |
| `3` | Array | Flat `{param}` captures from the matched pattern: `[k1, v1, k2, v2, ...]` |

The handler is responsible for the WebSocket handshake and framing itself
(via `std/websocket`: `ws_handshake_response`, `ws_parse`, `ws_frame`,
`ws_close`, `ws_is_close`) plus reading/writing on the fd
(`tcp_read_partial`, `tcp_write`, `tcp_close`).

Return value tells the server what to do with the fd:
- **`1`** — the handler took ownership: it did the handshake, served the
  connection, and closed the fd itself. The server will not read from or
  close it again.
- **`0`** — let the server respond/close the connection normally (e.g. the
  handler decided this isn't actually a WS request it wants to handle).

If no `app_ws` pattern matches an `Upgrade: websocket` request, the server
responds with a well-formed `404 Not Found`.

```nyx
fn ws_echo_handler(info: Array) -> int {
    let fd: int = info[0]
    let headers: Array = info[2]
    let params: Array = info[3]

    let key: String = http_find_header(headers, "Sec-WebSocket-Key")
    if key.length() == 0 {
        tcp_write(fd, "HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        tcp_close(fd)
        return 1
    }

    var room: String = "?"
    var i: int = 0
    while i + 1 < params.length() {
        let pk: String = params[i]
        if pk == "room" {
            let pv: String = params[i + 1]
            room = pv
        }
        i = i + 2
    }

    tcp_write(fd, ws_handshake_response(key))
    let data: String = tcp_read_partial(fd, 4096)
    if data.length() > 0 and !ws_is_close(data) {
        let payload: String = ws_parse(data)
        tcp_write(fd, ws_frame(room + ":" + payload))
    }
    tcp_write(fd, ws_close())
    tcp_close(fd)
    return 1
}

app_ws("/ws/echo/{room}", ws_echo_handler)
```

### `serve_ws(handler: Fn(Array) -> int)`

Compat alias: `serve_ws(handler)` == `app_ws("*", handler)` — registers the
handler under the catch-all pattern. Prefer `app_ws(pattern, handler)` for
new code, since a `"*"` registration swallows every WS upgrade request
(there's no way for another `app_ws` pattern to take precedence, and the
"no route matched" 404 becomes unreachable).

---

## Request

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `method` | String | HTTP method (`"GET"`, `"POST"`, ...) |
| `path` | String | Clean path, query string stripped |
| `query` | Map | Query params (`?k=v` → `map["k"]="v"`) |
| `headers_flat` | Array | Interleaved `["Header-Name", "value", ...]` |
| `body` | String | Raw request body |
| `form` | Map | Parsed `application/x-www-form-urlencoded` body |
| `cookies` | Map | Parsed `Cookie` header |
| `params` | Map | Route path params from `{placeholders}` |

### `req_json(req: Request) -> Map`

Parse request body as JSON object. Returns `Map<String>` with string, number, bool, and null values stringified.

```nyx
let data: Map = req_json(req)
let name: String = data.get("name")
```

---

## Response Constructors

### `response_html(status: int, html: String) -> Response`

Status + HTML body. Content-Type is auto-detected as `text/html; charset=utf-8`.

### `response_json(status: int, json: String) -> Response`

Status + JSON body. Sets `Content-Type: application/json; charset=utf-8`.

### `response_json_map(status: int, data: Map) -> Response`

Serialises a `Map<String>` into a JSON object and returns a 200 JSON response.

### `response_text(status: int, text: String) -> Response`

Status + plain text. No Content-Type set (auto-detected as `text/plain`).

### `response_redirect(url: String) -> Response`

302 redirect to `url`. Any headers you add to the returned `Response`'s `headers_flat` (e.g. `Set-Cookie`) are emitted on the redirect (since v0.2.2). The dispatcher emits `headers_flat` for all `Location`-based redirects (301/302/303/307/308).

### `response_new(status: int, body: String) -> Response`

Bare constructor — no Content-Type header.

---

## Middleware Helpers

### `mw_cors(req: Request) -> Response`

Built-in CORS middleware. Handles `OPTIONS` preflight (returns 204). For other methods, returns `status: 0` (continue). Adds `Access-Control-Allow-Origin` header.

### `cors_configure(origin: String, methods: String, headers: String)`

Configure CORS before registering `mw_cors`.

```nyx
cors_configure("https://example.com", "GET, POST", "Content-Type, Authorization")
app_use(app, mw_cors)
```

### `mw_logging(req: Request) -> Response`

No-op — always returns `status: 0` (continue) with no headers. There is
**no** automatic request logging in nyx-serve; this middleware exists as a
registration slot for future use, but wiring it up today does not print
anything. To log requests, write your own middleware or `app_after` hook
(see `docs/MIDDLEWARE.md`).

---

## Templates

From `nyx-serve/src/template`.

### `tpl_render(tmpl: String, ctx: Map) -> String`

Renders a template string against a `Map<String>` context. Syntax:

| Tag | Behaviour |
|-----|-----------|
| `{{key}}` | HTML-escaped interpolation. Missing key → `""` (no error). |
| `{{{key}}}` | **Raw** interpolation, no escaping. ⚠️ XSS risk — only use with trusted/pre-sanitized content, never raw user input. |
| `{{#if key}}...{{/if}}`, `{{#if key}}...{{else}}...{{/if}}` | Truthy = key present AND value not `""` AND not `"0"`. |
| `{{#each key}}...{{/each}}` | `key` must resolve to an `Array<Map>`; the body is rendered once per element using that element's `Map` as the block context. Nesting (`{{#each}}` inside `{{#each}}`) is supported. |
| `{{> name}}` | Includes a partial registered via `tpl_partial()`, rendered with the **current** context. Recursion is capped at depth 8 — beyond that a literal error marker is emitted instead of looping or crashing. |

```nyx
var item1: Map = map_new()
item1.insert("name", "Ann")
var item2: Map = map_new()
item2.insert("name", "<Bob>")
var items: Array = [item1, item2]

var ctx: Map = map_new()
ctx.insert("title", "<Nyx>")
ctx.insert("show_list", "1")
ctx.insert("items", items)

let tmpl: String = "<h1>{{title}}</h1>{{#if show_list}}<ul>{{#each items}}<li>{{name}}</li>{{/each}}</ul>{{else}}<p>empty</p>{{/if}}"
let html: String = tpl_render(tmpl, ctx)
// <h1>&lt;Nyx&gt;</h1><ul><li>Ann</li><li>&lt;Bob&gt;</li></ul>
```

### `tpl_partial(name: String, tmpl: String)`

Registers a partial template under `name`, usable from any subsequent
`tpl_render` call via `{{> name}}`.

---

## Multipart

From `nyx-serve/src/multipart`. **Standalone helper** — it does not populate
`req.form` and does not touch the `Request` struct; call it explicitly from
your handler.

### `multipart_parse(body: String, content_type: String) -> Array`

Parses a `multipart/form-data` body against the boundary declared in
`content_type`. Binary-safe (survives embedded NUL bytes and `\r\n`/`--`
sequences inside a part's value). Capped at 256 parts. Returns an empty
`Array` if `content_type` has no boundary or the leading boundary marker
never appears in `body`. Since requests are capped by `NYX_HTTP_MAX_BODY`
(see the Server section), bodies parsed here are always under that limit.

Returns an `Array` of opaque "part" values — always use the accessors below,
never index a part directly (the internal layout is not a stable contract):

- `part_name(p: Array) -> String`
- `part_filename(p: Array) -> String` — `""` if the part has no `filename=`.
- `part_ctype(p: Array) -> String` — `""` if the part has no `Content-Type:`.
- `part_value(p: Array) -> String`

```nyx
fn handle_upload(req: Request) -> Response {
    let ctype: String = http_find_header(req.headers_flat, "Content-Type")
    let parts: Array = multipart_parse(req.body, ctype)
    var sb: StringBuilder = StringBuilder.new()
    var i: int = 0
    while i < parts.length() {
        let p: Array = parts[i]
        let name: String = part_name(p)
        let filename: String = part_filename(p)
        let value: String = part_value(p)
        sb.append(name)
        sb.append(":")
        sb.append(filename)
        sb.append(":")
        sb.append(int_to_string(value.length()))
        sb.append("\n")
        i = i + 1
    }
    return response_text(200, sb.to_string())
}
```

---

## Static Files & Caching

From `nyx-serve/src/files`.

### `app_static(app: App, prefix: String, directory: String) -> int`

Registers a prefix-based static route: a request whose path starts with
`prefix` is served from `directory` (e.g. `/learn/01.html` →
`static/learn/01.html` for `app_static(app, "/learn/", "static/learn/")`).
Rejects (no-ops, returns `0`) if `prefix` contains `".."` or `"~"`.

### `app_static_cached(app: App, prefix: String, directory: String, max_age: int) -> int`

Same as `app_static`, but every `200` response additionally gets
`Cache-Control: public, max-age=<max_age>` and (when the file's mtime is
available) `Last-Modified: <http-date>`. Combine with the automatic ETag
handling below — `Cache-Control` avoids the re-request, `ETag` validates it
if one happens anyway.

### `serve_static(app: App, dir: String)`

Registers a **fallback** static directory: tried only when no route and no
`app_static`/`app_static_cached` prefix matched. Unlike those, there's no
URL prefix — the whole `dir` is mounted at `/`.

### `detect_mime_type(path: String) -> String`

Detects a `Content-Type` from a file extension (`.html`, `.css`, `.js`,
`.json`, images, fonts, `.xml`, `.txt`, `.md`, `.wasm`, ... falls back to
`application/octet-stream`).

### `compute_weak_etag(content: String) -> String`

Computes a weak ETag (`W/"<first 16 hex chars of sha256(content)>"`).

### `apply_etag(resp: Response, if_none_match: String) -> Response`

Only acts on `status: 200` responses (returns others unchanged). Computes
the ETag of `resp.body` and adds it as an `ETag` header; if `if_none_match`
(the client's `If-None-Match` request header) matches, collapses the
response to a bare `304 Not Modified` instead. Pass `""` for
`if_none_match` to just add the header without the 304 check. The server
already calls this automatically for every static file it serves (both
`app_static`/`app_static_cached` prefixes and the `serve_static` fallback) —
you only need to call it yourself from a handler that serves its own
cacheable content.

---

## Parsing Helpers

### `parse_query_string(path: String) -> Map`

Extract query params from a path string. `"/search?q=nyx&page=2"` → `{"q":"nyx","page":"2"}`.

### `parse_form_data(body: String, content_type: String) -> Map`

Parse `application/x-www-form-urlencoded` body.

### `parse_cookies(headers_flat: Array) -> Map`

Parse the `Cookie` header from a flat headers array.

### `route_match(pattern: String, path: String) -> Map`

Match a path against a pattern. Returns a Map with `"_matched" = "true"` if matched, plus any captured params. Empty map if no match.

---

## Utility

### `url_decode(s: String) -> String`

URL-decode a string (converts `+` to space; percent-decoding handled by runtime).
