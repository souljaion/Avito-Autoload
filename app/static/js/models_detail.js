/* models_detail.js — extracted from detail.html inline <script> */

const _D = window.MODEL_PAGE_DATA;
const MODEL_ID = _D.model_id;
const ACCOUNTS = _D.accounts;
const PACKS = _D.packs;
const HAS_CATEGORY = _D.has_category;
window.modelIsComplete = _D.model_is_complete;
window.modelMissingFields = _D.missing_fields;

const goodsTypesMap = _D.goods_types;
const apparelsMap = _D.apparels;
const subtypesMap = _D.goods_subtypes;
const modelCategory = _D.model_category;
const modelGoodsType = _D.model_goods_type;
const modelSubcategory = _D.model_subcategory;
const modelGoodsSubtype = _D.model_goods_subtype;

function showToast(msg, isError) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.style.display = 'block';
    t.style.background = isError ? '#fef2f2' : '#dcfce7';
    t.style.color = isError ? '#991b1b' : '#166534';
    t.style.border = isError ? '0.5px solid #fca5a5' : '0.5px solid #86efac';
    setTimeout(() => t.style.display = 'none', 4000);
}

// ── Cascading selects ──
function populateSelect(sel, items, val) {
    sel.innerHTML = `<option value="">${sel.options[0]?.text||'--'}</option>`;
    for (const i of (items||[])) { const o = document.createElement('option'); o.value = i; o.textContent = i; if (i === val) o.selected = true; sel.appendChild(o); }
}
function onCategoryChange() { populateSelect(document.getElementById('editGoodsType'), goodsTypesMap[document.getElementById('editCategory').value]||[], modelGoodsType); onGoodsTypeChange(); }
function onGoodsTypeChange() { populateSelect(document.getElementById('editSubcategory'), apparelsMap[document.getElementById('editGoodsType').value]||[], modelSubcategory); onSubcategoryChange(); }
function onSubcategoryChange() {
    const sel = document.getElementById('editGoodsSubtype');
    const items = subtypesMap[document.getElementById('editSubcategory').value] || [];
    if (items.length === 0) {
        sel.innerHTML = '<option value="">Не требуется</option>';
        sel.disabled = true; sel.style.opacity = '0.6';
    } else {
        sel.disabled = false; sel.style.opacity = '';
        populateSelect(sel, items, modelGoodsSubtype);
    }
}
onCategoryChange();

function toggleEditForm() { document.getElementById('editForm').classList.toggle('visible'); }

async function saveModel() {
    const body = { brand: document.getElementById('editBrand').value.trim(), name: document.getElementById('editName').value.trim(), description: document.getElementById('editDesc').value.trim(), category: document.getElementById('editCategory').value, goods_type: document.getElementById('editGoodsType').value, subcategory: document.getElementById('editSubcategory').value, goods_subtype: document.getElementById('editGoodsSubtype').value };
    if (!body.name) { showToast('Название обязательно', true); return; }
    const resp = await fetch('/models/' + MODEL_ID, { method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.ok) location.reload(); else showToast(data.error, true);
}

async function deleteModel() {
    if (!confirm('Удалить модель?')) return;
    const resp = await fetch('/models/' + MODEL_ID, { method: 'DELETE' });
    if ((await resp.json()).ok) location.href = '/models';
}

// ── Status pills (header meta is server-rendered in new layout) ──
function updateStatusPills() {
    // No-op: inline meta is rendered server-side in the compressed header
}

// ── Auto-save ──
const _saveTimers = {};

function debounceSave(pid, el) {
    clearTimeout(_saveTimers[pid]);
    _saveTimers[pid] = setTimeout(() => autoSave(pid, el), 800);
}

async function autoSave(pid, el) {
    const field = el.dataset.field;
    let value = el.value;
    if (field === 'price') value = value ? parseInt(value) : null;
    if (field === 'account_id') value = value ? parseInt(value) : null;
    if (field === 'use_custom_description') value = value === 'true';

    try {
        const resp = await fetch('/products/' + pid, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ [field]: value }),
        });
        const data = await resp.json();
        if (data.ok) {
            const ind = document.getElementById('saved-' + pid);
            if (ind) { ind.classList.add('visible'); setTimeout(() => ind.classList.remove('visible'), 2000); }
            updateStatusPills();
        } else showToast(data.error || 'Ошибка', true);
    } catch(e) { showToast('Ошибка сети', true); }
}

async function updateDescriptionTemplate(selectEl) {
    const pid = selectEl.dataset.productId;
    const prevValue = selectEl.dataset.prevValue ?? selectEl.value;
    const newValue = selectEl.value ? parseInt(selectEl.value) : null;

    try {
        const resp = await fetch('/products/' + pid, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ description_template_id: newValue }),
        });
        const data = await resp.json();
        if (data.ok) {
            selectEl.dataset.prevValue = selectEl.value;
            showToast('Шаблон обновлён');
            const ind = document.getElementById('saved-' + pid);
            if (ind) { ind.classList.add('visible'); setTimeout(() => ind.classList.remove('visible'), 2000); }
        } else {
            selectEl.value = prevValue;
            showToast(data.error || 'Ошибка', true);
        }
    } catch(e) {
        selectEl.value = prevValue;
        showToast('Ошибка сети', true);
    }
}

// ── Pack change ──
async function changePack(pid, packId) {
    if (!packId) return;
    try {
        const resp = await fetch('/products/' + pid + '/pack', { method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ pack_id: parseInt(packId) }) });
        const data = await resp.json();
        if (data.ok) showToast('Пак применён', false); else showToast(data.error, true);
    } catch(e) { showToast('Ошибка сети', true); }
}

// ── Schedule ──
function _getScheduleTime() {
    const v = document.getElementById('schedule-time').value;
    return v || null;
}

async function scheduleAllDrafts() {
    const time = _getScheduleTime();
    if (!time) { showToast('Укажите время', true); return; }
    const cards = document.querySelectorAll('[data-product-id]');
    let ok = 0, total = 0, lastProblems = [];
    for (const card of cards) {
        if (card.dataset.status !== 'draft') continue;
        const pid = card.dataset.productId;
        const group = card.closest('.account-group');
        const accId = group ? group.dataset.accountId : null;
        if (!accId) continue;
        total++;
        try {
            const resp = await fetch('/products/' + pid + '/schedule', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ account_id: parseInt(accId), scheduled_at: time }) });
            const data = await resp.json();
            if (data.ok) ok++;
            else if (data.problems) lastProblems = data.problems;
        } catch(e) {}
    }
    if (total === 0) showToast('Нет черновиков', false);
    else {
        let msg = `Запланировано: ${ok}/${total}`;
        if (ok < total && lastProblems.length) msg += '. Не хватает: ' + lastProblems.join(', ');
        showToast(msg, ok < total);
        if (ok > 0) location.reload();
    }
}

// ── Bulk actions ──
function getSelectedDraftIds() {
    const checked = document.querySelectorAll('.row-cb:checked');
    const ids = [];
    const nonDraft = [];
    checked.forEach(cb => {
        const row = cb.closest('[data-product-id]');
        const status = row.dataset.status;
        if (status === 'draft') {
            ids.push(parseInt(cb.dataset.productId));
        } else {
            nonDraft.push(cb);
        }
    });
    // Uncheck non-drafts
    if (nonDraft.length > 0) {
        nonDraft.forEach(cb => cb.checked = false);
        showToast(`Только черновики могут быть опубликованы. Снято выделение: ${nonDraft.length} строк`, true);
        updateBulkBar();
    }
    return ids;
}

function toggleSelectAll(master) {
    const cbs = document.querySelectorAll('.row-cb');
    cbs.forEach(cb => cb.checked = master.checked);
    updateBulkBar();
}

function updateBulkBar() {
    const count = document.querySelectorAll('.row-cb:checked').length;
    const bar = document.getElementById('bulk-bar');
    const countEl = document.getElementById('bulk-count');
    if (count > 0) {
        bar.classList.add('visible');
        countEl.textContent = `Выбрано: ${count}`;
    } else {
        bar.classList.remove('visible');
    }
    // Update master checkbox state
    const allCbs = document.querySelectorAll('.row-cb');
    document.getElementById('select-all-cb').checked = allCbs.length > 0 && count === allCbs.length;
}

function clearSelection() {
    document.querySelectorAll('.row-cb').forEach(cb => cb.checked = false);
    document.getElementById('select-all-cb').checked = false;
    updateBulkBar();
}

async function bulkSchedule() {
    const ids = getSelectedDraftIds();
    if (!ids.length) { showToast('Нет выбранных черновиков', true); return; }
    try {
        const resp = await fetch('/models/' + MODEL_ID + '/bulk-schedule', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: ids }),
        });
        const data = await resp.json();
        if (data.ok) {
            const n = data.scheduled.length;
            const s = data.skipped.length;
            showToast(`В расписание: ${n}` + (s ? `, пропущено: ${s}` : ''));
            if (n > 0) location.reload();
        } else showToast(data.error, true);
    } catch(e) { showToast('Ошибка сети', true); }
}

async function scheduleOneNow(pid) {
    try {
        const resp = await fetch('/models/' + MODEL_ID + '/bulk-schedule', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: [pid] }),
        });
        const data = await resp.json();
        if (data.ok && data.scheduled.length) {
            showToast('В расписание: 1');
            location.reload();
        } else showToast(data.error || 'Не удалось запланировать', true);
    } catch(e) { showToast('Ошибка сети', true); }
}

async function bulkPublishModal() {
    const ids = getSelectedDraftIds();
    if (!ids.length) { showToast('Нет выбранных черновиков', true); return; }

    if (ids.length === 1) {
        openInlineEdit(ids[0]);
        return;
    }

    // 2+ products: carousel mode
    _carouselQueue = ids.slice();
    _carouselIndex = 0;
    _carouselStats = {saved: 0, published: 0, skipped: 0};
    _loadCarouselItem(0);
}

function closeBulkModal() {
    document.getElementById('bulk-modal-overlay').classList.remove('visible');
}

// ── Inline edit + publish (single product) ──
let _inlineProductId = null;
let _inlineTimeoutId = null;
const INLINE_TIMEOUT_MS = 10000;

function _armInlineTimeout() {
    _clearInlineTimeout();
    const btn = document.getElementById('inline-publish-btn');
    _inlineTimeoutId = setTimeout(() => {
        _inlineTimeoutId = null;
        btn.disabled = false;
        btn.textContent = 'Сохранить и опубликовать';
        showToast('Не удалось сохранить — iframe не ответил за 10 секунд. Проверьте подключение и попробуйте снова.', true);
    }, INLINE_TIMEOUT_MS);
}

function _clearInlineTimeout() {
    if (_inlineTimeoutId) {
        clearTimeout(_inlineTimeoutId);
        _inlineTimeoutId = null;
    }
}

var _inlineSaveOnly = false;

// ── Carousel state (multi-select) ──
var _carouselQueue = [];   // product IDs
var _carouselIndex = -1;   // current index, -1 = no carousel
var _carouselStats = {saved: 0, published: 0, skipped: 0};

function _isCarousel() { return _carouselQueue.length > 1; }

function _updateTitle() {
    var title = 'Редактировать и опубликовать';
    if (_isCarousel()) title += ' (' + (_carouselIndex + 1) + ' из ' + _carouselQueue.length + ')';
    document.getElementById('inline-edit-title').textContent = title;
}

function _resetButtons() {
    document.getElementById('inline-publish-btn').disabled = false;
    document.getElementById('inline-publish-btn').textContent = 'Сохранить и опубликовать';
    document.getElementById('inline-save-only-btn').disabled = false;
    document.getElementById('inline-save-only-btn').textContent = 'Только сохранить';
    document.getElementById('inline-skip-btn').style.display = _isCarousel() ? '' : 'none';
    document.getElementById('inline-skip-btn').disabled = false;
}

function _disableAllButtons() {
    document.getElementById('inline-publish-btn').disabled = true;
    document.getElementById('inline-save-only-btn').disabled = true;
    document.getElementById('inline-skip-btn').disabled = true;
}

function _loadCarouselItem(index) {
    _carouselIndex = index;
    var productId = _carouselQueue[index];
    _inlineProductId = productId;
    _inlineSaveOnly = false;
    var iframe = document.getElementById('inline-edit-iframe');
    iframe.src = '/products/' + productId + '/edit?inline=1';
    _updateTitle();
    _resetButtons();
    document.getElementById('inline-edit-overlay').classList.add('visible');
}

function _buildAggregate() {
    var s = _carouselStats;
    var parts = [];
    if (s.saved > 0) parts.push('Сохранено: ' + s.saved);
    if (s.published > 0) parts.push('Опубликовано: ' + s.published);
    if (s.skipped > 0) parts.push('Пропущено: ' + s.skipped);
    return parts.length ? parts.join(', ') : 'Ничего не изменено';
}

function _advanceOrFinish() {
    var next = _carouselIndex + 1;
    if (next < _carouselQueue.length) {
        _loadCarouselItem(next);
    } else {
        _finishCarousel();
    }
}

function _finishCarousel() {
    var msg = _isCarousel() ? _buildAggregate() : 'Сохранено';
    var hadWork = _carouselStats.saved + _carouselStats.published > 0;
    _closeInlineRaw();
    showToast(msg, false);
    if (hadWork) setTimeout(function() { location.reload(); }, 1500);
}

function _closeInlineRaw() {
    _clearInlineTimeout();
    document.getElementById('inline-edit-overlay').classList.remove('visible');
    document.getElementById('inline-edit-iframe').src = '';
    _inlineProductId = null;
    _carouselQueue = [];
    _carouselIndex = -1;
}

function openInlineEdit(productId) {
    _carouselQueue = [productId];
    _carouselIndex = 0;
    _carouselStats = {saved: 0, published: 0, skipped: 0};
    _inlineProductId = productId;
    _inlineSaveOnly = false;
    var iframe = document.getElementById('inline-edit-iframe');
    iframe.src = '/products/' + productId + '/edit?inline=1';
    _updateTitle();
    _resetButtons();
    document.getElementById('inline-edit-overlay').classList.add('visible');
}

function closeInlineEdit() {
    _clearInlineTimeout();
    if (_isCarousel() && (_carouselStats.saved + _carouselStats.published + _carouselStats.skipped > 0)) {
        var msg = _buildAggregate();
        var hadWork = _carouselStats.saved + _carouselStats.published > 0;
        _closeInlineRaw();
        showToast(msg, false);
        if (hadWork) setTimeout(function() { location.reload(); }, 1500);
        return;
    }
    _closeInlineRaw();
}

// Listen for postMessage from iframe after form save
window.addEventListener('message', function(e) {
    if (e.origin !== window.location.origin) return;
    if (e.data && e.data.type === 'product-saved' && _inlineProductId) {
        _clearInlineTimeout();
        if (_inlineSaveOnly) {
            _carouselStats.saved++;
            if (_isCarousel()) {
                _advanceOrFinish();
            } else {
                _finishCarousel();
            }
        } else {
            _doPublishAfterSave(e.data.productId || _inlineProductId);
        }
    }
});

function skipCarouselItem() {
    _carouselStats.skipped++;
    _advanceOrFinish();
}

function inlineSaveOnly() {
    _inlineSaveOnly = true;
    var btn = document.getElementById('inline-save-only-btn');
    btn.disabled = true;
    btn.textContent = 'Сохраняем...';
    document.getElementById('inline-publish-btn').disabled = true;
    document.getElementById('inline-skip-btn').disabled = true;
    _armInlineTimeout();
    var iframe = document.getElementById('inline-edit-iframe');
    iframe.contentWindow.postMessage({type: 'submit-form'}, window.location.origin);
}

async function inlinePublishConfirm() {
    _inlineSaveOnly = false;
    var btn = document.getElementById('inline-publish-btn');
    btn.disabled = true;
    btn.textContent = 'Сохраняем...';
    document.getElementById('inline-save-only-btn').disabled = true;
    document.getElementById('inline-skip-btn').disabled = true;
    _armInlineTimeout();
    var iframe = document.getElementById('inline-edit-iframe');
    iframe.contentWindow.postMessage({type: 'submit-form'}, window.location.origin);
}

async function _doPublishAfterSave(productId) {
    var btn = document.getElementById('inline-publish-btn');
    btn.textContent = 'Публикуем...';
    try {
        var resp = await fetch('/models/' + MODEL_ID + '/bulk-publish', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: [productId] }),
        });
        var data = await resp.json();
        if (data.ok && data.published > 0) {
            _carouselStats.published++;
            if (_isCarousel()) {
                _advanceOrFinish();
            } else {
                _closeInlineRaw();
                showToast('Опубликовано. Появится на Авито в течение часа.', false);
                setTimeout(function() { location.reload(); }, 1500);
            }
        } else if (data.not_ready?.length) {
            var missing = data.not_ready[0].missing.join(', ');
            showToast('Не готово к публикации: ' + missing, true);
            _resetButtons();
        } else {
            showToast(data.error || 'Ошибка публикации', true);
            _resetButtons();
        }
    } catch(e) {
        showToast('Ошибка сети', true);
        _resetButtons();
    }
}

async function publishOneNow(productId) {
    if (!confirm('Выложить это объявление сразу?')) return;
    try {
        var resp = await fetch('/models/' + MODEL_ID + '/bulk-publish', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: [productId] }),
        });
        var data = await resp.json();
        if (data.ok && data.published > 0) {
            showToast('Опубликовано. Появится на Авито в течение часа.', false);
            setTimeout(function() { location.reload(); }, 1500);
        } else if (data.not_ready && data.not_ready.length) {
            showToast('Не готово: ' + data.not_ready[0].missing.join(', '), true);
        } else {
            showToast(data.error || 'Ошибка публикации', true);
        }
    } catch(e) {
        showToast('Ошибка сети', true);
    }
}

async function bulkPublishConfirm() {
    const ids = JSON.parse(document.getElementById('bulk-confirm-btn').dataset.ids || '[]');
    if (!ids.length) return;

    document.getElementById('bulk-confirm-btn').disabled = true;
    document.getElementById('bulk-confirm-btn').textContent = 'Публикуем...';

    try {
        const resp = await fetch('/models/' + MODEL_ID + '/bulk-publish', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: ids }),
        });
        const data = await resp.json();
        closeBulkModal();

        if (data.ok) {
            let msg = `Опубликовано: ${data.published} объявлений. Появятся на Авито в течение часа.`;
            if (data.not_ready?.length) {
                msg += ` Не готовы: ${data.not_ready.length}`;
                const problems = data.not_ready.map(r => `${r.title}: ${r.missing.join(', ')}`).join('; ');
                msg += ` (${problems})`;
            }
            showToast(msg, data.not_ready?.length > 0);
            if (data.published > 0) setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Ошибка', true);
        }
    } catch(e) {
        closeBulkModal();
        showToast('Ошибка сети', true);
    } finally {
        const btn = document.getElementById('bulk-confirm-btn');
        btn.disabled = false;
        btn.textContent = 'Подтвердить';
    }
}

// ── Actions ──
async function repostProduct(pid) {
    if (!confirm('Перевыложить?')) return;
    showToast('Перевыкладка...', false);
    try {
        const resp = await fetch('/products/' + pid + '/repost', { method: 'POST' });
        const data = await resp.json();
        if (data.ok) { showToast(data.message, false); setTimeout(() => location.reload(), 1500); }
        else showToast(data.error, true);
    } catch(e) { showToast('Ошибка сети', true); }
}

async function softDelete(pid, title, status, avitoId) {
    if (status === 'active' || status === 'imported' || status === 'published') {
        showDeleteImportedModal(pid, title, avitoId);
        return;
    }
    if (!confirm('Удалить "' + title + '"?')) return;
    await doMarkRemoved(pid);
}

async function doMarkRemoved(pid) {
    try {
        const resp = await fetch('/products/' + pid, { method: 'DELETE' });
        const data = await resp.json();
        if (data.ok) {
            document.getElementById('row-' + pid)?.remove();
            showToast('Помечено как удалённое', false);
            updateStatusPills();
            closeDeleteModal();
        } else showToast('Ошибка', true);
    } catch(e) { showToast('Ошибка сети', true); }
}

function showDeleteImportedModal(pid, title, avitoId) {
    closeDeleteModal();
    const overlay = document.createElement('div');
    overlay.id = 'delete-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;display:flex;align-items:center;justify-content:center;';
    overlay.onclick = function(e) { if (e.target === overlay) closeDeleteModal(); };

    const avitoUrl = avitoId
        ? 'https://www.avito.ru/items/' + avitoId
        : 'https://www.avito.ru/profile/items';

    overlay.innerHTML = `
        <div style="background:white;padding:24px 28px;border-radius:12px;max-width:460px;width:90%;box-shadow:0 10px 40px rgba(0,0,0,0.2);">
            <div style="font-size:17px;font-weight:600;margin-bottom:12px;">Удалить объявление</div>
            <div style="font-size:14px;line-height:1.6;color:#555;margin-bottom:20px;">
                Объявления, опубликованные через кабинет Авито, не всегда удаляются через файл автозагрузки.<br><br>
                Рекомендуем сначала снять объявление с публикации в кабинете Авито, а затем пометить его здесь как удалённое.
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;">
                <a href="${avitoUrl}" target="_blank" rel="noopener"
                   style="display:block;text-align:center;background:#6366f1;color:white;padding:12px;border-radius:8px;font-size:14px;text-decoration:none;font-weight:500;">
                    Открыть в Авито ↗
                </a>
                <button onclick="doMarkRemoved(${pid})"
                    style="background:#f3f4f6;color:#111;padding:12px;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;cursor:pointer;">
                    Я удалил на Авито, пометить в программе
                </button>
                <button onclick="closeDeleteModal()"
                    style="background:transparent;color:#6b7280;padding:8px;border:none;font-size:13px;cursor:pointer;margin-top:2px;">
                    Отмена
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
}

function closeDeleteModal() {
    document.getElementById('delete-modal-overlay')?.remove();
}

// ── Add row ──
async function addNewRow(accountId) {
    // Warn if model is incomplete
    if (!window.modelIsComplete) {
        const missing = window.modelMissingFields.join(", ");
        const ok = confirm(
            `Модель не полностью заполнена (не хватает: ${missing}).\n\n` +
            `Объявление будет создано, но не попадёт в фид до дозаполнения модели.\n\n` +
            `Продолжить создание?`
        );
        if (!ok) return;
    }

    // Use provided accountId or pick first account (backend requires account_id NOT NULL)
    const accId = accountId || (ACCOUNTS.length ? ACCOUNTS[0].id : null);

    try {
        const resp = await fetch('/models/' + MODEL_ID + '/products', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                account_id: accId,
            }),
        });
        const data = await resp.json();
        if (data.ok) { showToast('Объявление создано', false); location.reload(); }
        else showToast(data.error, true);
    } catch(e) { showToast('Ошибка сети', true); }
}

// ── Photo packs ──
function togglePackSource() {
    const isYdisk = document.querySelector('input[name="packSource"][value="ydisk"]').checked;
    document.getElementById('packSourceLocal').style.display = isYdisk ? 'none' : 'block';
    document.getElementById('packSourceYdisk').style.display = isYdisk ? 'block' : 'none';
}

async function createPack() {
    const name = document.getElementById('packName').value.trim();
    if (!name) { document.getElementById('packError').textContent = 'Введите название'; document.getElementById('packError').style.display = 'block'; return; }
    document.getElementById('packError').style.display = 'none';

    const isYdisk = document.querySelector('input[name="packSource"][value="ydisk"]').checked;
    const form = new FormData(); form.append('name', name); form.append('model_id', MODEL_ID);
    try {
        const resp = await fetch('/photo-packs', { method: 'POST', body: form });
        const data = await resp.json();
        if (!data.ok) { document.getElementById('packError').textContent = data.error; document.getElementById('packError').style.display = 'block'; return; }

        if (isYdisk) {
            const url = document.getElementById('packYdUrl').value.trim();
            const folderName = document.getElementById('packYdName').value.trim();
            if (!url) { document.getElementById('packError').textContent = 'Введите ссылку на папку'; document.getElementById('packError').style.display = 'block'; return; }
            const fResp = await fetch('/api/photo-packs/' + data.id + '/yandex-folders', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({public_url: url, folder_name: folderName || null}),
            });
            const fData = await fResp.json();
            if (!fData.ok) { document.getElementById('packError').textContent = fData.error || 'Ошибка'; document.getElementById('packError').style.display = 'block'; return; }
            // Auto-select all files from the new folder
            if (fData.files && fData.files.length) {
                await _autoSelectAllFiles(data.id, fData.folder_id, fData.files);
            }
        } else {
            const files = document.getElementById('packFiles').files;
            if (files.length > 0) { const uf = new FormData(); for (const f of files) uf.append('files', f); await fetch('/photo-packs/' + data.id + '/upload', { method: 'POST', body: uf }); }
        }
        location.reload();
    } catch(e) { showToast('Ошибка сети', true); }
}

async function renamePack(packId, currentName) {
    var newName = prompt('Новое имя пака:', currentName);
    if (newName === null || newName.trim() === '' || newName.trim() === currentName) return;
    try {
        var resp = await fetch('/photo-packs/' + packId, {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: newName.trim()}),
        });
        var data = await resp.json();
        if (data.ok) {
            var el = document.querySelector('#pack-' + packId + ' .pack-item-name');
            if (el) el.textContent = data.name;
            showToast('Переименовано', false);
        } else { showToast(data.error || 'Ошибка', true); }
    } catch(e) { showToast('Ошибка сети', true); }
}

async function deletePack(packId) {
    if (!confirm('Удалить фотопак?')) return;
    var resp = await fetch('/photo-packs/' + packId, { method: 'DELETE' });
    if ((await resp.json()).ok) { document.getElementById('pack-' + packId)?.remove(); showToast('Удалён', false); }
    else showToast('Ошибка', true);
}

async function uploadToPack(packId, files) {
    if (!files.length) return;
    const form = new FormData(); for (const f of files) form.append('files', f);
    try {
        const resp = await fetch('/photo-packs/' + packId + '/upload', { method: 'POST', body: form });
        if ((await resp.json()).ok) location.reload(); else showToast('Ошибка загрузки', true);
    } catch(e) { showToast('Ошибка сети', true); }
}

// ── Yandex.Disk on pack cards ──
const _ydPollingTimers = {};

function showAddYdFolderForPack(packId) {
    document.getElementById('yd-add-' + packId).style.display = 'block';
}

async function addYdFolderForPack(packId) {
    var url = document.getElementById('yd-url-' + packId).value.trim();
    var name = document.getElementById('yd-name-' + packId).value.trim();
    var errEl = document.getElementById('yd-add-err-' + packId);
    errEl.textContent = '';
    if (!url) { errEl.textContent = 'Введите ссылку'; return; }
    try {
        var resp = await fetch('/api/photo-packs/' + packId + '/yandex-folders', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({public_url: url, folder_name: name || null}),
        });
        var data = await resp.json();
        if (!data.ok) { errEl.textContent = data.error || 'Ошибка'; return; }
        document.getElementById('yd-add-' + packId).style.display = 'none';
        // Auto-select all files from the new folder
        if (data.files && data.files.length) {
            await _autoSelectAllFiles(packId, data.folder_id, data.files);
        }
        loadYdFolders(packId);
    } catch(e) { errEl.textContent = 'Ошибка сети'; }
}

async function _autoSelectAllFiles(packId, folderId, files) {
    var paths = files.map(function(f) { return f.path; });
    try {
        var resp = await fetch('/api/photo-packs/' + packId + '/yandex-folders/' + folderId + '/selection', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({selected_paths: paths}),
        });
        var data = await resp.json();
        if (data.ok && data.added > 0) {
            showToast(data.added + ' фото добавлено. Загрузка начнётся автоматически.', false);
            checkYdDownloadStatus(packId);
        }
    } catch(e) {}
}

async function deleteYdFolderForPack(packId, folderId) {
    if (!confirm('Удалить папку и все связанные фото?')) return;
    await fetch('/api/photo-packs/' + packId + '/yandex-folders/' + folderId + '?delete_images=true', {method: 'DELETE'});
    loadYdFolders(packId);
}

async function loadYdFolders(packId) {
    var container = document.getElementById('yd-folders-' + packId);
    container.innerHTML = '<span style="color:#9ca3af;font-size:11px;">Загрузка...</span>';
    try {
        var resp = await fetch('/api/photo-packs/' + packId + '/yandex-folders');
        var data = await resp.json();
        if (!data.ok) { container.innerHTML = '<span style="color:#dc2626;font-size:11px;">Ошибка</span>'; return; }

        if (!data.folders.length) { container.innerHTML = ''; return; }

        var html = '';
        for (var folder of data.folders) {
            html += '<div style="border:1px solid #e2e4f0;border-radius:6px;padding:8px;margin-bottom:6px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">';
            html += '<span style="font-size:12px;font-weight:500;">' + (folder.folder_name || 'Папка') + '</span>';
            html += '<button class="btn btn-sm btn-outline-danger" style="font-size:10px;padding:2px 6px;" onclick="deleteYdFolderForPack(' + packId + ',' + folder.folder_id + ')">&#x2715;</button>';
            html += '</div>';
            if (folder.error) html += '<div style="color:#dc2626;font-size:10px;margin-bottom:4px;">' + folder.error + '</div>';

            html += '<div class="pack-yd-grid">';
            for (var f of folder.files) {
                html += '<img src="/api/yandex-preview?url=' + encodeURIComponent(f.preview_url) + '" alt="' + f.name + '" loading="lazy" title="' + f.name + ' (' + Math.round(f.size/1024) + ' KB)">';
            }
            if (!folder.files.length) html += '<span style="color:#9ca3af;font-size:11px;">Пусто</span>';
            html += '</div>';
            html += '</div>';
        }
        container.innerHTML = html;
    } catch(e) { container.innerHTML = '<span style="color:#dc2626;font-size:11px;">Ошибка</span>'; }
}

async function retryPackDownload(packId, imageId) {
    await fetch('/api/photo-packs/' + packId + '/images/' + imageId + '/retry-download', {method: 'PATCH'});
    checkYdDownloadStatus(packId);
}

const _ydPollStartTimes = {};
const _YD_POLL_INTERVAL = 5000;
const _YD_POLL_MAX_DURATION = 10 * 60 * 1000;  // 10 minutes

async function checkYdDownloadStatus(packId) {
    // Clear existing timer
    if (_ydPollingTimers[packId]) { clearTimeout(_ydPollingTimers[packId]); _ydPollingTimers[packId] = null; }

    // Track polling start
    if (!_ydPollStartTimes[packId]) _ydPollStartTimes[packId] = Date.now();

    // Safety timeout
    if (Date.now() - _ydPollStartTimes[packId] > _YD_POLL_MAX_DURATION) {
        console.warn(`Y.Disk polling for pack ${packId} stopped after 10 minutes`);
        delete _ydPollStartTimes[packId];
        return;
    }

    try {
        const resp = await fetch('/photo-packs/' + packId + '/images');
        const data = await resp.json();
        if (!data.ok) return;

        let hasPending = false;
        for (const img of data.images) {
            if (img.source_type !== 'yandex_disk') continue;

            // Find badge element for this image, or create one
            const badgeId = 'yd-status-' + img.id;
            let badgeEl = document.getElementById(badgeId);

            if (img.download_status === 'pending' || img.download_status === 'downloading') {
                hasPending = true;
            }

            // Individual image status is handled by the bulk refresh in the
            // hasPending false→true transition below (see Bug B comment).
        }

        // Show/hide per-pack status banner
        _updatePackStatusBanner(packId, data.images);

        if (hasPending) {
            _ydPollingTimers[packId] = setTimeout(() => checkYdDownloadStatus(packId), _YD_POLL_INTERVAL);
        } else {
            // Done — no pending images. Clean up and stop.
            delete _ydPollStartTimes[packId];
            if (_ydPollingTimers[packId]) {
                clearTimeout(_ydPollingTimers[packId]);
                delete _ydPollingTimers[packId];
            }
            // Refresh folder previews once downloads complete
            loadYdFolders(packId);
        }
    } catch(e) {
        // Retry on network error, but with the standard interval (not immediately)
        _ydPollingTimers[packId] = setTimeout(() => checkYdDownloadStatus(packId), _YD_POLL_INTERVAL);
    }
}

function _updatePackStatusBanner(packId, images) {
    const ydImages = images.filter(i => i.source_type === 'yandex_disk');
    if (!ydImages.length) return;

    const pending = ydImages.filter(i => i.download_status === 'pending').length;
    const downloading = ydImages.filter(i => i.download_status === 'downloading').length;
    const failed = ydImages.filter(i => i.download_status === 'failed').length;
    const ready = ydImages.filter(i => i.download_status === 'ready').length;

    let bannerId = 'yd-dl-banner-' + packId;
    let banner = document.getElementById(bannerId);
    if (!banner) {
        banner = document.createElement('div');
        banner.id = bannerId;
        banner.style.cssText = 'font-size:11px;padding:6px 8px;border-radius:6px;margin-top:6px;';
        const section = document.querySelector(`.yd-pack-section[data-pack-id="${packId}"]`);
        if (section) section.appendChild(banner);
    }

    if (pending + downloading === 0 && failed === 0) {
        banner.remove();
        return;
    }

    let parts = [];
    if (pending > 0) parts.push(`<span class="yd-badge yd-badge-pending">В очереди: ${pending}</span>`);
    if (downloading > 0) parts.push(`<span class="yd-badge yd-badge-downloading">⏳ Загружается: ${downloading}</span>`);
    if (failed > 0) parts.push(`<span class="yd-badge yd-badge-failed">❌ Ошибка: ${failed}</span>`);
    if (ready > 0) parts.push(`<span style="color:#22c55e;font-size:10px;">✓ Готово: ${ready}</span>`);
    banner.innerHTML = parts.join(' ');
}

// ── Link products ──
let _linkTimer;
const _linkSelected = new Set();

function toggleLinkSection() {
    const body = document.getElementById('link-body');
    const icon = document.getElementById('link-toggle-icon');
    if (body.style.display === 'none') { body.style.display = 'block'; icon.innerHTML = '&#x25BC;'; }
    else { body.style.display = 'none'; icon.innerHTML = '&#x25B6;'; }
}

document.getElementById('link-search').addEventListener('input', function() {
    clearTimeout(_linkTimer);
    _linkTimer = setTimeout(() => searchUnlinked(), 400);
});
document.getElementById('link-account-filter').addEventListener('change', () => searchUnlinked());

async function searchUnlinked() {
    const q = document.getElementById('link-search').value.trim();
    const accId = document.getElementById('link-account-filter').value;
    const container = document.getElementById('link-results');
    if (!q && !accId) { container.innerHTML = '<div style="color:#9ca3af;font-size:13px;">Введите запрос или выберите аккаунт</div>'; return; }

    let url = '/models/' + MODEL_ID + '/unlinked-products?q=' + encodeURIComponent(q);
    if (accId) url += '&account_id=' + accId;

    try {
        const resp = await fetch(url);
        const data = await resp.json();
        if (!data.ok) { container.innerHTML = '<div style="color:#fca5a5;">Ошибка</div>'; return; }
        _linkSelected.clear();
        updateLinkBar();
        if (!data.items.length) { container.innerHTML = '<div style="color:#9ca3af;font-size:13px;padding:8px;">Ничего не найдено</div>'; return; }

        let html = '';
        for (const p of data.items) {
            const checked = _linkSelected.has(p.id) ? 'checked' : '';
            const accBadge = p.account_name ? `<span style="background:#eef2ff;color:#4338ca;padding:1px 6px;border-radius:6px;font-size:10px;">${p.account_name}</span>` : '';
            const statusCls = {active:'status-active',published:'status-active',imported:'status-imported',draft:'status-draft'}[p.status] || 'status-draft';
            const meta = [p.size, p.price ? p.price.toLocaleString('ru-RU') + ' ₽' : null].filter(Boolean).join(' · ');
            const thumbHtml = p.image_url
                ? `<img src="${p.image_url}" style="width:64px;height:64px;object-fit:cover;border-radius:6px;flex-shrink:0;">`
                : `<div style="width:64px;height:64px;border-radius:6px;background:#f3f4f6;flex-shrink:0;"></div>`;
            html += `<label style="display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:0.5px solid #f3f4f6;cursor:pointer;" onmouseenter="this.style.background='#f9fafb'" onmouseleave="this.style.background=''">
                <input type="checkbox" value="${p.id}" ${checked} onchange="toggleLinkItem(${p.id},this.checked)" style="width:auto;flex-shrink:0;">
                ${thumbHtml}
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${p.title}</div>
                    <div style="font-size:11px;color:#9ca3af;">${accBadge} <span class="status-badge ${statusCls}" style="font-size:10px;">${p.status}</span> ${meta}</div>
                </div>
            </label>`;
        }
        container.innerHTML = html;
    } catch(e) { container.innerHTML = '<div style="color:#fca5a5;">Ошибка сети</div>'; }
}

function toggleLinkItem(id, checked) {
    if (checked) _linkSelected.add(id); else _linkSelected.delete(id);
    updateLinkBar();
}

function updateLinkBar() {
    const bar = document.getElementById('link-bar');
    const count = document.getElementById('link-count');
    if (_linkSelected.size > 0) { bar.style.display = 'flex'; count.textContent = 'Выбрано: ' + _linkSelected.size; }
    else { bar.style.display = 'none'; }
}

async function linkSelected() {
    if (!_linkSelected.size) return;
    try {
        const resp = await fetch('/models/' + MODEL_ID + '/link-products', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ product_ids: [..._linkSelected] }),
        });
        const data = await resp.json();
        if (data.ok) {
            showToast('Привязано: ' + data.linked + ' объявлений', false);
            _linkSelected.clear();
            document.getElementById('link-results').innerHTML = '';
            updateLinkBar();
            location.reload();
        } else showToast(data.error, true);
    } catch(e) { showToast('Ошибка сети', true); }
}

// ── Analytics (legacy — element removed in new layout) ──
async function loadAnalytics() {
    const body = document.getElementById('analyticsBody');
    if (!body) return;
    try {
        const resp = await fetch('/models/' + MODEL_ID + '/analytics');
        const data = await resp.json();
        if (!data.ok) { body.innerHTML = '<div style="color:#9ca3af;font-size:13px;">Нет данных</div>'; return; }

        const rec = data.recommendations;
        let html = '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">';
        html += `<span class="m-pill m-pill-green">&#x1F7E2; Живых: ${rec.live_count}</span>`;
        html += `<span class="m-pill m-pill-yellow">&#x1F7E1; Слабых: ${rec.weak_count}</span>`;
        html += `<span class="m-pill m-pill-red">&#x1F534; Мёртвых: ${rec.dead_count}</span>`;
        html += '</div>';
        html += `<div style="font-size:13px;color:#374151;margin-bottom:14px;">${rec.recommendation}</div>`;

        if (data.items.length) {
            html += '<div style="overflow-x:auto;"><table class="listings-table"><thead><tr><th>Аккаунт</th><th>Название</th><th>Просмотры</th><th>&Delta; день</th><th>Маркер</th></tr></thead><tbody>';
            for (const it of data.items) {
                const markerLabels = {alive:'живое',weak:'слабое',dead:'мёртвое',unknown:'нет данных'};
                const titleTrunc = it.title && it.title.length > 25 ? it.title.substring(0, 25) + '...' : (it.title || '—');
                html += `<tr>`;
                html += `<td style="font-size:12px;">${it.account_name||'—'}</td>`;
                html += `<td style="font-size:12px;" title="${it.title||''}">${titleTrunc}</td>`;
                html += `<td style="font-size:12px;">${it.views_total != null ? it.views_total : '—'}</td>`;
                html += `<td style="font-size:12px;">${it.views_delta != null ? (it.views_delta > 0 ? '+' : '') + it.views_delta : '—'}</td>`;
                html += `<td style="font-size:12px;"><span class="marker-dot marker-${it.marker}"></span>${markerLabels[it.marker]||'?'}</td>`;
                html += `</tr>`;
            }
            html += '</tbody></table></div>';
        } else {
            html += '<div style="color:#9ca3af;font-size:13px;">Нет активных объявлений</div>';
        }
        body.innerHTML = html;
    } catch(e) { body.innerHTML = '<div style="color:#fca5a5;font-size:13px;">Ошибка загрузки аналитики</div>'; }
}

// ── Unlinked count badge ──
async function loadUnlinkedCount() {
    try {
        const resp = await fetch('/models/' + MODEL_ID + '/unlinked-products?count_only=true');
        const data = await resp.json();
        if (data.ok && data.count > 0) {
            const badge = document.getElementById('link-count-badge');
            badge.textContent = data.count + ' без модели';
            badge.style.display = 'inline';
        }
    } catch(e) {}
}

// ── Init ──
updateStatusPills();
loadAnalytics();
loadUnlinkedCount();

// Load Y.Disk folders for all packs and check download status
const _allPackIds = _D.all_pack_ids;
for (const packId of _allPackIds) {
    loadYdFolders(packId);
    (async (pid) => {
        try {
            var resp = await fetch('/photo-packs/' + pid + '/images');
            var data = await resp.json();
            if (data.ok && data.images.some(function(i) { return i.source_type === 'yandex_disk' && (i.download_status === 'pending' || i.download_status === 'downloading'); })) {
                checkYdDownloadStatus(pid);
            }
        } catch(e) {}
    })(packId);
}
