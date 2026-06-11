# nyx-serve — API Reference (`std/web`)

All functions are exported from `std/web`. Import with `import "std/web"`.

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

Register a middleware function. Runs before route handlers in registration order.

---

### `app_before(app: App, hook: Fn)`
### `app_after(app: App, hook: Fn)`

Register before/after hooks (less common than middlewares).

---

### `serve_static(app: App, dir: String)`

Set the static file directory. Tried as a fallback if no route matches.

---

## Server

### `serve_app(app: App, port: int, workers: int)`

Start the server. Blocks forever. Spawns `workers` goroutines in a keep-alive connection pool.

From `products/serve/server`:

```nyx
import "products/serve/server"
serve_app(app, 3000, 64)
```

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

302 redirect to `url`.

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

No-op marker. Logging is performed by the dispatch loop (`METHOD PATH → STATUS ms`).

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
