# Changelog

All notable changes to nyx-serve are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is independent
from the Nyx language toolchain.

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
