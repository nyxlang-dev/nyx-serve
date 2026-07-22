# nyx-serve — Examples

## Minimal JSON API

```nyx
import "std/web"
import "nyx-serve/src/server"

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
import "nyx-serve/src/server"

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
import "nyx-serve/src/server"

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
import "nyx-serve/src/server"

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

## WebSocket Echo with `{param}`

`app_ws` matches WS upgrade requests with the same `{param}`/`*` pattern
syntax as HTTP routes; the handler receives `[fd, path, headers_flat,
params_pairs_flat]` and must do its own handshake/read/write/close via
`std/websocket`. Returning `1` tells the server the handler took ownership
of the fd.

```nyx
import "std/web"
import "std/websocket"
import "nyx-serve/src/server"

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

fn main() {
    let app: App = app_new()
    app_ws("/ws/echo/{room}", ws_echo_handler)
    serve_app(app, 3000, 4)
}
```

---

## Template Rendering: if / each / partial

```nyx
import "std/web"
import "nyx-serve/src/server"
import "nyx-serve/src/template"

fn handle_template_demo(req: Request) -> Response {
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
    return response_html(200, html)
}

fn main() {
    let app: App = app_new()
    app_get(app, "/template-demo", handle_template_demo)
    serve_app(app, 3000, 4)
}
```

---

## Multipart Upload

`multipart_parse` is a standalone helper — it does not touch `req.form`, so
call it explicitly with the raw body and `Content-Type` header. Always use
the `part_*` accessors to read a part (never index it directly).

```nyx
import "std/web"
import "nyx-serve/src/server"
import "nyx-serve/src/multipart"

fn handle_multipart_demo(req: Request) -> Response {
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

fn main() {
    let app: App = app_new()
    app_post(app, "/multipart-demo", handle_multipart_demo)
    serve_app(app, 3000, 4)
}
```
