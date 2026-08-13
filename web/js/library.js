/* 影库首页 — 拉取 /api/catalog 代理的列表 / 详情，点击跳到 /web/play.html?path=...
 *
 * base URL 走同源代理 `/api/catalog`，上游 base 由后端 settings.catalog_api_base 决定。
 */

const PROXY = '/api/catalog';

const state = {
    page: 1,
    size: 60,
    q: '',
    labels: [],            // 服务端筛选用
    movies: [],
    total: 0,
    loading: false,
    error: null,
};

// --- 同步 URL：q / labels 写回；page 暂不同步（避免历史栈污染） ---
function syncUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    if (state.labels.length) p.set('labels', state.labels.join(','));
    const qs = p.toString();
    history.replaceState(null, '', qs ? `${location.pathname}?${qs}` : location.pathname);
}

// --- API ---
function apiUrl(path, params = {}) {
    const search = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
        if (v === undefined || v === null || v === '') continue;
        if (Array.isArray(v)) { if (!v.length) continue; search.set(k, v.join(',')); }
        else search.set(k, String(v));
    }
    const qs = search.toString();
    return `${PROXY}${path}${qs ? '?' + qs : ''}`;
}

async function listMovies() {
    const url = apiUrl('/api/movies', {
        page: state.page, size: state.size, labels: state.labels, q: state.q,
    });
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`目录 API ${resp.status}`);
    return resp.json();
}

function playHref(code, m) {
    const p = new URLSearchParams({ path: code });
    if (m) {
        if (m.title) p.set('title', m.title);
        if (m.cover) p.set('cover', m.cover);
        if (Array.isArray(m.cast) && m.cast.length) p.set('cast', m.cast.join('|'));
        if (Array.isArray(m.labels) && m.labels.length) p.set('tags', m.labels.join('|'));
        if (m.year != null && m.year !== '') p.set('year', String(m.year));
        if (m.duration != null && m.duration !== '') p.set('duration', String(m.duration));
        if (m.description) p.set('description', m.description);
    }
    return `play.html?${p}`;
}

async function load({ append = false } = {}) {
    state.loading = true;
    state.error = null;
    if (append) {
        // 加载更多：只把"加载更多"区切到加载中，保留 grid 不动，
        // 避免清空 grid 导致页面高度坍塌、滚动位置被重置到顶部。
        renderMorePending();
    } else {
        render();
    }
    try {
        const json = await listMovies();
        const data = Array.isArray(json.data) ? json.data : [];
        const beforeCount = state.movies.length;
        state.movies = append ? state.movies.concat(data) : data;
        state.total = json.total ?? state.movies.length;
        state.loading = false;  // 渲染前清掉 loading，否则 renderError() 会一直显示"加载中…"
        if (append) {
            for (const m of state.movies.slice(beforeCount)) grid.appendChild(makeCard(m));
            count.textContent = `共 ${state.total} 部 · 已加载 ${state.movies.length}`;
            renderMore();
        } else {
            render();
        }
    } catch (e) {
        state.error = e.message;
        if (!append) { state.movies = []; state.total = 0; }
        state.loading = false;  // 同上
        if (append) {
            // append 失败：保留已加载的 grid，仅在 more 区显示错误并恢复按钮
            more.innerHTML = '';
            more.appendChild(el('div', 'state-msg', `加载失败：${e.message}`));
            renderMore();
        } else {
            render();
        }
    }
}

// --- 工具 ---
function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
}

function names(v) {
    if (Array.isArray(v)) return v.join('、');
    return v ? String(v) : '';
}

function coverInto(box, m) {
    box.innerHTML = '';
    if (!m.cover) {
        box.appendChild(el('div', 'cover-fallback', m.fan_code || '无封面'));
        return box;
    }
    const img = el('img');
    img.loading = 'lazy';
    img.referrerPolicy = 'no-referrer';
    img.alt = m.fan_code || '';
    img.src = m.cover;
    img.onerror = () => {
        box.innerHTML = '';
        box.appendChild(el('div', 'cover-fallback', m.fan_code || '封面加载失败'));
    };
    box.appendChild(img);
    return box;
}

// 关键词搜索走服务端：debounce 后重新请求 /api/movies?q=...，让上游做匹配。
const SEARCH_DEBOUNCE_MS = 300;

/** 从已加载数据里统计 facet（演员 / 标签），按数量降序。 */
function facets(key) {
    const counter = new Map();
    for (const m of state.movies) {
        const list = Array.isArray(m[key]) ? m[key] : (m[key] ? [m[key]] : []);
        for (const name of list) counter.set(name, (counter.get(name) || 0) + 1);
    }
    return [...counter.entries()].sort((a, b) => b[1] - a[1]);
}

function toggleLabel(name) {
    state.labels = state.labels.includes(name) ? [] : [name];
    state.page = 1;
    syncUrl();
    load();
}

// --- 渲染 ---
const grid = document.getElementById('libGrid');
const chips = document.getElementById('libChips');
const count = document.getElementById('libCount');
const more = document.getElementById('libMore');
const search = document.getElementById('libSearch');

function statusLine() {
    if (state.loading) return '加载中…';
    if (state.error) return `目录 API 出错：${state.error}`;
    return null;
}

function renderError() {
    const msg = statusLine();
    if (!msg) return false;
    grid.innerHTML = '';
    more.innerHTML = '';
    const box = el('div', 'state-msg');
    box.innerHTML = state.error
        ? `${msg}<br><br>请确认已启动 demo 目录 API：<code>python3 /Users/iamshijun/py_workspace/demo/movie-storage/app.py</code><br>并检查 <code>CATALOG_API_BASE</code> 配置。`
        : msg;
    grid.appendChild(box);
    count.textContent = '';
    return true;
}

function renderChips() {
    chips.innerHTML = '';
    const all = el('div', 'lib-chip' + (state.labels.length ? '' : ' on'));
    all.appendChild(el('span', null, '全部'));
    all.appendChild(el('i', null, String(state.total)));
    all.onclick = () => { if (state.labels.length) toggleLabel(state.labels[0]); };
    chips.appendChild(all);

    const section = (title, key) => {
        const rows = facets(key);
        if (!rows.length) return;
        chips.appendChild(el('h3', null, title));
        for (const [name, n] of rows.slice(0, 40)) {
            const chip = el('div', 'lib-chip' + (state.labels.includes(name) ? ' on' : ''));
            chip.appendChild(el('span', null, name));
            chip.appendChild(el('i', null, String(n)));
            chip.onclick = () => toggleLabel(name);
            chips.appendChild(chip);
        }
    };
    section('演员', 'cast');
    section('标签', 'labels');
}

function makeCard(m) {
    const card = el('div', 'lib-card');
    const thumb = el('div', 'lib-thumb');
    coverInto(thumb, m);
    thumb.appendChild(el('div', 'lib-code', m.fan_code));
    card.appendChild(thumb);
    card.appendChild(el('div', 'lib-title', m.title || '(无标题)'));

    if (Array.isArray(m.cast) && m.cast.length) {
        const castRow = el('div', 'lib-cast-row');
        castRow.appendChild(el('span', 'lib-cast-label', '演员'));
        const chipsBox = el('div', 'lib-cast-chips');
        const list = m.cast.slice(0, 5);
        for (const name of list) {
            const chip = el('span', 'lib-cast-chip' + (state.labels.includes(name) ? ' on' : ''), name);
            chip.onclick = (e) => { e.stopPropagation(); toggleLabel(name); };
            chipsBox.appendChild(chip);
        }
        if (m.cast.length > list.length) {
            const moreChip = el('a', 'lib-cast-chip', `+${m.cast.length - list.length}`);
            moreChip.href = playHref(m.fan_code, m);
            moreChip.onclick = (e) => e.stopPropagation();
            chipsBox.appendChild(moreChip);
        }
        castRow.appendChild(chipsBox);
        card.appendChild(castRow);
    }

    const a = el('a');
    a.href = playHref(m.fan_code, m);
    a.style.display = 'none';
    card.appendChild(a);
    card.onclick = () => { open_page(playHref(m.fan_code, m)); };
    return card;
}

function renderMore() {
    more.innerHTML = '';
    if (state.movies.length < state.total) {
        const btn = el('button', 'btn', `加载更多（${state.movies.length}/${state.total}）`);
        btn.onclick = () => { state.page++; load({ append: true }); };
        more.appendChild(btn);
    }
}

function renderMorePending() {
    more.innerHTML = '';
    more.appendChild(el('div', 'state-msg', '加载中…'));
}

function renderGrid() {
    grid.innerHTML = '';
    more.innerHTML = '';
    if (renderError()) return;
    for (const m of state.movies) grid.appendChild(makeCard(m));
    count.textContent = `共 ${state.total} 部 · 已加载 ${state.movies.length}`;
    renderMore();
}

function open_page(url) {
    const link = document.createElement('a');
    link.href = url
    link.target = '_blank'; // 新标签页打开
    link.rel = 'noopener noreferrer'; // 安全加固（防止新页面控制原页面）
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function render() {
    if (state.error) { renderChips(); renderError(); return; }
    renderChips();
    renderGrid();
}

// --- 启动 ---
const qs = new URLSearchParams(location.search);
state.q = qs.get('q') || '';
state.labels = (qs.get('labels') || '').split(',').map(s => s.trim()).filter(Boolean);
search.value = state.q;
let searchTimer = null;
search.addEventListener('input', () => {
    state.q = search.value;
    syncUrl();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        state.page = 1;
        load();
    }, SEARCH_DEBOUNCE_MS);
});

render();
load();
