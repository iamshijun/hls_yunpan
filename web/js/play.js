/* 播放页 — 变体 A 风格：hero（模糊背景图 + 海报 + 标题/标签）+ 演员 chips + 播放器 + 字段表
 * 支持「带详情就直显，没有就回退 /metadata/{path}」 */
const $ = (id) => document.getElementById(id);

const video = $('video');
const statusEl = $('status');
const errorEl = $('errorMessage');
const currentPathEl = $('currentPath');
const titleEl = $('title');
const crumbPathEl = $('crumbPath');

const heroEl = $('hero');
const heroBgEl = $('heroBg');
const heroPosterEl = $('heroPoster');
const heroMetaEl = $('heroMeta');
const heroSubEl = $('heroSub');

const castSectionEl = $('castSection');
const castChipsEl = $('castChips');

const fieldsEl = $('fields');

let hls = null;

function showStatus(cls, text) {
    statusEl.className = 'play-status ' + cls;
    statusEl.textContent = text;
}

function showError(message) {
    errorEl.textContent = message;
    errorEl.classList.add('show');
    showStatus('error', '播放失败');
}

function hideError() {
    errorEl.classList.remove('show');
}

function getBaseUrl() {
    if (window.location.protocol === 'file:') return 'http://localhost:9009';
    const m = location.pathname.match(/^(.*?)\/web(?:\/|$)/);
    return m ? m[1] : '';
}

function readQuery() {
    const p = new URLSearchParams(location.search);
    const get = (k) => p.get(k) || '';
    const splitPipes = (s) => s ? s.split('|').map(x => x.trim()).filter(Boolean) : [];
    return {
        path: get('path'),
        title: get('title'),
        cover: get('cover'),
        cast: splitPipes(get('cast')),
        tags: splitPipes(get('tags')),
        year: get('year'),
        duration: get('duration'),
        description: get('description'),
        series: get('series'),
        maker: get('maker'),
        genre: splitPipes(get('genre')),
        fanCode: get('fanCode') || get('path'),
    };
}

function hasInlineDetail(q) {
    return Boolean(q.title || q.cover || q.cast.length || q.tags.length || q.year || q.duration || q.description);
}

function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
}

function names(v) {
    if (Array.isArray(v)) return v.filter(Boolean).join('、');
    return v ? String(v) : '';
}

/** 渲染 hero：模糊背景 + 海报 + 标题/标签 + 副标题 */
function renderHero(q) {
    titleEl.textContent = q.title || `播放 ${q.path}`;

    heroPosterEl.innerHTML = '';
    if (q.cover) {
        const img = document.createElement('img');
        img.loading = 'eager';
        img.referrerPolicy = 'no-referrer';
        img.alt = q.title || q.path;
        img.src = q.cover;
        img.onerror = () => { heroPosterEl.innerHTML = ''; heroPosterEl.appendChild(el('div', 'cover-fallback', q.path || '无封面')); };
        heroPosterEl.appendChild(img);
        heroBgEl.style.backgroundImage = `url("${q.cover}")`;
        heroBgEl.hidden = false;
    } else {
        heroBgEl.hidden = true;
        heroPosterEl.appendChild(el('div', 'cover-fallback', q.path || '无封面'));
    }

    heroMetaEl.innerHTML = '';
    const metaBits = [q.fanCode, q.year, q.duration ? `${q.duration} 分钟` : null].filter(Boolean);
    for (const t of metaBits) heroMetaEl.appendChild(el('span', 'play-tag', t));

    heroSubEl.textContent = '';
}

function renderCast(q) {
    if (!q.cast.length) {
        castSectionEl.hidden = true;
        return;
    }
    castSectionEl.hidden = false;
    castChipsEl.innerHTML = '';
    for (const name of q.cast) {
        castChipsEl.appendChild(el('span', 'play-cast-chip', name));
    }
}

function renderFields(q) {
    fieldsEl.innerHTML = '';
    const rows = [
        ['番号', q.fanCode ? el('span', 'play-tag', q.fanCode) : null],
        ['标签', q.tags.length ? q.tags.join('、') : null],
        ['年份', q.year || null],
        ['时长', q.duration ? `${q.duration} 分钟` : null],
        ['简介', q.description || null],
        ['系列', q.series || null],
        ['制作商', q.maker || null],
        ['类型', names(q.genre) || null],
    ];
    for (const [k, v] of rows) {
        if (!v) continue;
        const row = el('div', 'play-field');
        row.appendChild(el('b', null, k));
        if (typeof v === 'string') row.appendChild(el('span', null, v));
        else row.appendChild(v);
        fieldsEl.appendChild(row);
    }
    // 播放地址
    const baseUrl = getBaseUrl();
    const urlRow = el('div', 'play-field');
    urlRow.appendChild(el('b', null, '播放地址'));
    const urlSpan = el('span', 'play-url', `${baseUrl}/hls/${q.path}/playlist.m3u8`);
    urlRow.appendChild(urlSpan);
    fieldsEl.appendChild(urlRow);
}

function applyDetail(q) {
    renderHero(q);
    renderCast(q);
    renderFields(q);
    video.poster = q.cover || '';
}

async function fetchMetadata(baseUrl, cleanPath) {
    try {
        const resp = await fetch(`${baseUrl}/metadata/${cleanPath}`);
        if (resp.status === 404) return; // 没 metadata 是合法情况
        if (!resp.ok) { console.warn('metadata 请求失败:', resp.status); return; }
        const data = await resp.json();
        if (!data || typeof data !== 'object') return;
        const q = readQuery();
        // 用 metadata 填充 URL 没带的字段（不覆盖已有的）
        const merged = {
            ...q,
            title: q.title || data.title || '',
            cover: q.cover || data.cover || '',
            cast: q.cast.length ? q.cast : (Array.isArray(data.cast) ? data.cast : (typeof data.cast === 'string' ? [data.cast] : [])),
            tags: q.tags.length ? q.tags : (Array.isArray(data.tags) ? data.tags : []),
            year: q.year || (data.year != null ? String(data.year) : ''),
            duration: q.duration || (data.duration != null ? String(data.duration) : ''),
            description: q.description || data.description || '',
            series: q.series || data.series || '',
            maker: q.maker || data.maker || '',
            genre: q.genre.length ? q.genre : (Array.isArray(data.genre) ? data.genre : []),
            fanCode: q.fanCode || data.fan_code || cleanPath,
        };
        applyDetail(merged);
    } catch (e) {
        console.debug('metadata 拉取异常:', e);
    }
}

function playVideo(cleanPath, baseUrl) {
    const m3u8Url = `${baseUrl}/hls/${cleanPath}/playlist.m3u8`;
    console.log('播放地址:', m3u8Url);
    currentPathEl.textContent = `当前播放: ${m3u8Url}`;
    showStatus('loading', '加载中...');

    if (hls) hls.destroy();

    if (window.Hls && Hls.isSupported()) {
        hls = new Hls({
            enableWorker: true,
            lowLatencyMode: true,
            manifestLoadingTimeOut: 30000,
            manifestLoadingMaxRetry: 3,
            fragLoadingTimeOut: 120000,
            fragLoadingMaxRetry: 6,
        });
        hls.loadSource(m3u8Url);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, function() {
            showStatus('playing', '播放中');
            video.play().catch(e => console.error('自动播放失败:', e));
        });
        hls.on(Hls.Events.ERROR, function(event, data) {
            console.error('HLS错误:', data);
            if (data.fatal) {
                switch (data.type) {
                    case Hls.ErrorTypes.NETWORK_ERROR:
                        showError('网络错误，无法加载媒体文件');
                        hls.startLoad();
                        break;
                    case Hls.ErrorTypes.MEDIA_ERROR:
                        showError('媒体错误，尝试恢复...');
                        hls.recoverMediaError();
                        break;
                    default:
                        showError('无法播放: ' + (data.details || '未知错误'));
                        hls.destroy();
                }
            }
        });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = m3u8Url;
        video.addEventListener('loadedmetadata', function() {
            showStatus('playing', '播放中');
            video.play().catch(e => console.error('自动播放失败:', e));
        });
        video.addEventListener('error', function() {
            showError('播放失败，请检查文件是否存在');
        });
    } else {
        showError('您的浏览器不支持HLS播放');
    }
}

// --- 启动 ---
const q = readQuery();
if (!q.path) {
    titleEl.textContent = '缺少 path 参数';
    crumbPathEl.textContent = '?';
    showError('请通过影库选择影片，或在 URL 上加 ?path=<fan_code>');
} else {
    crumbPathEl.textContent = q.path;
    const baseUrl = getBaseUrl();
    if (hasInlineDetail(q)) {
        // 带详情：直接渲染详情面板（不等 metadata）
        applyDetail(q);
    } else {
        // 老链接：先按 path 占位渲染，再异步拉 metadata 补全
        applyDetail(q);
        fetchMetadata(baseUrl, q.path);
    }
    playVideo(q.path, baseUrl);
}
