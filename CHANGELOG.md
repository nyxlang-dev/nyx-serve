# Changelog

All notable changes to nyx-serve are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is independent
from the Nyx language toolchain.

## [0.6.1] - 2026-08-10

### Added
- **Shutdown hooks**: `serve_on_shutdown(handler)` registers a cleanup
  callback (`handler: Fn() -> int`), called before `serve_app`. Hooks run
  in registration order during the SIGTERM drain, after the drain deadline
  (workers are quiet — consistent state for snapshots) and before
  `serve_app` returns `0`. They run in normal context (allocation,
  printing and disk writes are fine — unlike the signal handler itself).
  Each hook is individually guarded: a panicking hook is logged
  (`[nyx-serve] shutdown hook failed: ...`) and neither blocks the
  remaining hooks nor the exit-0 contract. Hooks have no internal timeout —
  your service manager's stop timeout is the outer bound. They only run on
  the SIGTERM drain; SIGKILL or any other termination path skips them.
  Use case: saving in-memory state to disk on shutdown. Quiescence assumes
  in-flight requests fit inside `NYX_SERVE_DRAIN_SECS`; a 0 deadline or a
  long request can still leave hooks running mid-request.

## [0.6.0] - 2026-08-10

### Added
- **Graceful shutdown**: `serve_app` installs a `SIGTERM` handler. On
  receipt, the listener socket is closed immediately (this is what wakes
  the blocking accept loop — no reliance on `EINTR`); every keep-alive
  worker finishes the request in flight, closes that connection, and exits
  once it picks up the shutdown sentinel. The runtime has no worker join, so
  the main thread always sleeps the **full** deadline (`NYX_SERVE_DRAIN_SECS`,
  default 10s; `0` = exit immediately, no wait) regardless of whether workers
  are already idle, then `serve_app` returns `0`. Tune
  `NYX_SERVE_DRAIN_SECS` down for fast redeploys. The `SIGTERM` handler
  itself is allocation-free and guards against a second signal re-closing
  the listener fd (signal-context GC/malloc locks are not reentrant).
- **Structured access log**: `app_access_log(&mut app)` (from `std/web`)
  opts into one JSON line per finished request on stdout: `ts` (epoch
  seconds), `method`, `path`, `status`, `dur_us`, `bytes`, and
  `request_id` (only when an earlier layer wrote `ctx["request-id"]`).
  Emitted after the `app_after` hook chain runs. The `mw_logging` stub from
  `std/web` is now explicitly documented as superseded by this.

### Changed
- `docs/API.md`/`docs/MIDDLEWARE.md`: documented rate limiting as
  out of scope — deploy behind a rate-limiting proxy such as nyx-proxy.
- Requires nyx >= 0.24.26.

## [0.5.1] - 2026-08-10

### Added
- **Per-request `ctx`**: `Request.ctx` (a `Map`) built via `request_new()`
  (from `std/web`) by the dispatcher before anything else runs — a wrap or
  middleware can write to it and have the value visible to the route
  handler, `app_after` hooks, and `app_error`, since `ctx` is shared by
  reference across the per-layer `Request` copies. Two requests never share
  a `ctx`. Smoke E2E coverage: wrap writes a request-id, the handler reads
  it into the body, an after-hook stamps it as a header, and two sequential
  requests are checked for distinct ids.

### Changed
- The dispatcher now builds every `Request` via `request_new()` instead of
  a bare struct literal, so `ctx` is always present. Requires nyx >= 0.24.25.

## [0.5.0] — 2026-08-09

### Added
- **Wrapping middleware**: `app_wrap(app, mw)` and `router_wrap(router, mw)`
  (`mw: Fn(Request, Fn) -> Response`) — runs around the rest of the
  pipeline, not just before it; calling `next(req)` runs everything
  downstream (hooks, status-0 middlewares, mounts, routes, static files, the
  404) and returns its `Response`, so a wrap can time, cache, or rewrite the
  response, or skip `next` entirely to short-circuit. Wraps compose
  onion-style in registration order.
- **Mountable routers**: `Router` / `router_new` / `router_get`/`post`/
  `put`/`delete`/`route` / `router_use` / `router_wrap` / `app_mount(app,
  prefix, router)` — a `Router` carries its own routes, status-0
  middlewares and wraps scoped under a literal path prefix. Fall-through
  semantics: if the router's middlewares continue and no internal route
  matches, the request falls through to the app's own routes, static files
  and 404 (a mount does not capture its prefix); a router wrap seeing a
  `status: 0` fall-through sentinel from `next` must return it unchanged.
  Mounts are tried in registration order; the first whose prefix matches
  and whose router handles the request wins — a mount that falls through
  lets a later matching mount (or, failing that, the app's own routes)
  take over.

### Changed
- Dispatcher restructured as an onion chain: `app_wrap`s are now the
  outermost layer, wrapping the full before-hooks → status-0 middlewares →
  mounts → routes → static → 404 pipeline. Mounts are checked **before**
  the app's own routes — a mount's middleware guards its entire prefix, so
  a concrete app route registered under a mounted prefix cannot bypass it
  (only reachable via fall-through).
- Internal request pipeline now resolves a `Response` before formatting
  (after-hooks and HTTP serialization run once, outside the wrap chain,
  instead of being interleaved per return path).
- Requires nyx >= 0.24.24.

## [0.4.0] — 2026-08-06

### Added
- **Registrable error handlers**: `app_not_found(app, handler)` replaces the
  default 404 page (HTTP and unmatched WebSocket upgrades); `app_error(app,
  handler)` turns handler panics/throws into a custom 500 instead of killing
  the process.

### Fixed
- `serve_static(app, dir)` now takes `app: &mut App` — previously the
  registration was silently lost (assigned onto a by-value copy and never
  persisted).

### Changed
- The dispatcher's request pipeline (hooks, middleware, route handler,
  static serving) now runs inside a try/catch: any panic or throw is caught
  and routed through `app_error` instead of crashing the worker. Requires
  nyx >= 0.24.19.

## [0.3.0] — 2026-07-31

### Added
- **WebSockets**: `app_ws(pattern, handler)` — route-matched WS upgrade
  handlers with the same `{param}`/`*` syntax as HTTP routes; `serve_ws(handler)`
  kept as a catch-all alias.
- **Template engine** (`src/template.nx`): `tpl_render` — `{{key}}`
  (HTML-escaped), `{{{key}}}` (raw), `{{#if}}/{{else}}`, nested `{{#each}}`,
  partials via `{{> name}}` with recursion guard.
- **Multipart parsing** (`src/multipart.nx`): binary-safe `multipart_parse`
  plus `part_name`/`part_filename`/`part_ctype`/`part_value` accessors.
- **Automatic 413**: requests over `NYX_HTTP_MAX_BODY` (default 1 MiB) are
  rejected with `413 Payload Too Large` + `Connection: close` before the body
  is read.
- **ETag / cached static serving**: `app_static_cached` adds `Cache-Control`
  + `Last-Modified`; `compute_weak_etag`/`apply_etag` collapse matching
  `If-None-Match` requests to `304`.

### Fixed
- `req.form` is now populated during dispatch (it was always empty).
- Headers set on `3xx` responses (`Set-Cookie` included) now travel with the
  redirect instead of being dropped.

### Changed
- Development unified in the open: this repository is now both the
  development and the public repo.

## [0.2.2] — 2026-07-08

### Fixed
- Dispatcher correctness: headers contributed by a continuing middleware
  (`status: 0`) are merged into the final response, and `app_before` /
  `app_after` hooks are wired into the dispatch path.

## [0.2.1] — 2026-07-06

- Initial standalone release, extracted from the NyxLang monorepo (split #6):
  `serve_app` multi-threaded keep-alive server, path-prefix static file
  serving with MIME detection, middleware chain and cookie sessions on top of
  `std/web`'s `App`.
