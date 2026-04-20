# Bugs Found During v7.7 Smoke Test

## No cache-busting for Jinja2 templates (v7.9 task)

**Found:** 2026-04-20 during v7.7 deploy smoke test.

**Symptom:** After deploying v7.7, operator saw stale form.html in browser
(taxonomy dropdowns appeared empty). Hard-refresh (Ctrl+Shift+R) fixed it.

**Root cause:** Jinja2 HTML templates are served by uvicorn through nginx
reverse proxy. There is no cache-busting mechanism — no `?v=` query strings,
no hashed filenames, no `Cache-Control` headers set by the app.

**Impact:** Every deploy that changes HTML templates risks stale-cache bugs
for users who have the page open or cached.

**Suggested fix (v7.9):**
- Add a `?v={{ app_version }}` query string to static asset references in
  `base.html` (favicon, CSS, JS if any are extracted).
- Set `Cache-Control: no-cache` on HTML responses in nginx or middleware
  (HTML pages should always revalidate; static assets can be long-cached
  with versioned URLs).
- Alternatively, add `ETag` / `Last-Modified` headers to HTML responses
  so browsers revalidate without a full re-download.
