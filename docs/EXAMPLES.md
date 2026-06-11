# nyx-serve — Examples

## Minimal JSON API

```nyx
import "std/web"
import "products/serve/server"

fn handle_ping(req: Request) -> Response {
    return response_json(200, "{\"pong\": true}")
}

fn main() {
    let app: App = app_new()
    app_get(app, "/ping", handle_ping)
    serve_app(app, 3000, 16)
    return 0
}
```

---

## REST API with Path Params

```nyx
import "std/web"
import "std/json"
import "products/serve/server"

fn handle_get_user(req: Request) -> Response {
    let id: String = req.params.get("id")
    // fetch from store...
    return response_json(200, "{\"id\": \"" + id + "\", \"name\": \"Alice\"}")
}

fn handle_create_user(req: Request) -> Response {
    let data: Map = req_json(req)
    let name: String = data.get("name")
    if name.length() == 0 {
        return response_json(400, "{\"error\": \"name required\"}")
    }
    return response_json(201, "{\"created\": true}")
}

fn main() {
    let app: App = app_new()
    app_get(app, "/users/{id}", handle_get_user)
    app_post(app, "/users", handle_create_user)
    serve_app(app, 3000, 32)
    return 0
}
```

---

## HTML + Static Files

```nyx
import "std/web"
import "products/serve/server"

fn handle_index(req: Request) -> Response {
    let html: String = read_file("public/index.html")
    return response_html(200, html)
}

fn main() {
    let app: App = app_new()
    app_get(app, "/", handle_index)
    serve_static(app, "public")      // /css/app.css, /js/app.js, etc.
    serve_app(app, 3000, 32)
    return 0
}
```

---

## CORS + Auth Middleware

```nyx
import "std/web"
import "products/serve/server"

fn mw_auth(req: Request) -> Response {
    let hdrs: Array = []
    if req.method == "OPTIONS" {
        return Response { status: 0, headers_flat: hdrs, body: "" }
    }
    let auth: String = http_find_header(req.headers_flat, "Authorization")
    if auth.length() == 0 {
        return response_json(401, "{\"error\": \"unauthorized\"}")
    }
    return Response { status: 0, headers_flat: hdrs, body: "" }
}

fn handle_data(req: Request) -> Response {
    return response_json(200, "{\"data\": [1, 2, 3]}")
}

fn main() {
    let app: App = app_new()
    cors_configure("https://myapp.com", "GET, POST", "Content-Type, Authorization")
    app_use(app, mw_cors)
    app_use(app, mw_auth)
    app_get(app, "/api/data", handle_data)
    serve_app(app, 3000, 32)
    return 0
}
```

---

## Query Params + Form Data

```nyx
fn handle_search(req: Request) -> Response {
    let q: String = req.query.get("q")
    let page: String = req.query.get("page")
    if page.length() == 0 { page = "1" }
    return response_json(200, "{\"q\": \"" + q + "\", \"page\": " + page + "}")
}

fn handle_form_submit(req: Request) -> Response {
    let content_type: String = http_find_header(req.headers_flat, "Content-Type")
    let form: Map = parse_form_data(req.body, content_type)
    let email: String = form.get("email")
    return response_json(200, "{\"received\": \"" + email + "\"}")
}
```

---

## Redirect

```nyx
fn handle_old_path(req: Request) -> Response {
    return response_redirect("/new/path")
}
```

---

## 404 and Error Handling

Routes that don't match fall through to the static file server, then to a built-in `404 Not Found` HTML page. To customise 404:

```nyx
fn handle_404(req: Request) -> Response {
    return response_html(404, read_file("public/404.html"))
}

// Register as a wildcard catch-all (last route)
app_get(app, "/*", handle_404)
```

---

## nyxlang.com (Real Example)

The actual nyxlang.com server (`products/serve/main.nx`) shows:
- Landing page routes (`/`, `/es/`)
- Wildcard `/learn/*` for The Nyx Book
- Static file fallback for CSS/images
- Install script delivery (`/install.sh`)
