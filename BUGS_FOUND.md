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

## Dead endpoints missing Bug #5 unification (v7.9 task)

**Found:** 2026-04-20 during Bug #5 audit.

**Endpoints:**
- `POST /models/{id}/create-all-listings` — creates products with pack but no
  `description_template_id` support.
- `POST /models/schedule-matrix` — creates products without pack or template_id.
- `POST /models/{id}/create-one` — creates products with auto-pack round-robin
  but no template_id.

**Status:** All three have **no JS/HTML callers** — they are dead code. They were
never wired into the UI.

**When revived (v7.9):** Apply `_apply_description_overrides` for description
priority rules and accept explicit `pack_id` from callers. The round-robin
auto-pack logic in `create_one` is useful and worth preserving as a fallback
when caller does not supply explicit `pack_id`.

## Dual-source description quirk (v7.9 UX improvement)

**Found:** 2026-04-20 during Bug #5 investigation (product 1532).

**Symptom:** On `/products/{id}/edit`, the "Вставить шаблон" dropdown button
copies template body text into the `<textarea name="description">`. When the
form is saved, `product.description` gets the template body AND
`product.description_template_id` remains set. Both fields co-exist on the
same product.

**Impact:** Confusing — operator sees description text in the edit form but
the feed actually uses the template's body (template wins per feed_generator
priority). If template body is later edited, the product.description becomes
stale but harmless (never rendered in feed).

**Suggested fix (v7.9):** When `description_template_id` is set on a product,
clear `product.description` to avoid confusion. Alternatively, on the edit
page, show a read-only preview of the template body instead of pasting into
the editable textarea.

## Description priority in create_model_product (v7.9 cosmetic)

**Found:** 2026-04-20 during Bug #5 audit.

**Symptom:** When `template_id` AND `model.description` are both provided,
current code sets BOTH on the product (`description_template_id=T`,
`description=model.description`, `use_custom_description=True`). Per v7.7
priority rules, template should win (`use_custom=False`, `description=None`).

**Impact:** Not a blocker — feed_generator handles this correctly via its own
priority rules (template wins at feed time). DB has dual-source data but feed
output is correct.

**Suggested fix (v7.9):** Add conditional: if `template_id` is set, leave
`description=None` and `use_custom_description=False`.
