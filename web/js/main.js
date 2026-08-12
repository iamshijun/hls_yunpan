const $ = (id) => document.getElementById(id);

const video = $('video');
const mediaPathInput = $('mediaPath');
const playerSection = $('playerSection');
const statusEl = $('status');
const errorMessage = $('errorMessage');
const currentPathEl = $('currentPath');

const metadataPanel = $('metadataPanel');
const metaCover = $('metaCover');
const metaTitle = $('metaTitle');
const metaFanCode = $('metaFanCode');
const metaCast = $('metaCast');
const metaSeries = $('metaSeries');
const metaMaker = $('metaMaker');
const metaGenre = $('metaGenre');
const metaTags = $('metaTags');

let hls = null;

function showStatus(status, text) {
    statusEl.className = 'status ' + status;
    statusEl.textContent = text;
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.add('show');
    showStatus('error', '播放失败');
}

function hideError() {
    errorMessage.classList.remove('show');
}

// 检测访问方式并确定服务器基础地址（含协议）
function getBaseUrl() {
    // 如果是通过 file:// 协议直接打开文件，回退到本地服务地址
    if (window.location.protocol === 'file:') {
        return 'http://localhost:9009';
    }
    // 通过 HTTP/HTTPS 访问时，直接使用当前 origin
    // （自动带上正确的协议+主机+端口，避免 https 页面加载 http 资源被拦截）
    return window.location.origin;
}

function loadVideo() {
    hideError();

    const path = mediaPathInput.value.trim();
    if (!path) {
        showError('请输入媒体目录路径');
        return;
    }

    // 移除开头的斜杠（如果有）
    const cleanPath = path.startsWith('/') ? path.substring(1) : path;

    // 获取目录名（最后一个/后面的部分）
    const dirName = cleanPath.split('/').pop();

    // 构建m3u8 URL - 使用当前 origin（协议自适应 http/https）
    const baseUrl = getBaseUrl();
    const m3u8Url = `${baseUrl}/hls/${cleanPath}/playlist.m3u8`;

    console.log('播放地址:', m3u8Url);

    playerSection.classList.add('active');
    currentPathEl.textContent = `当前播放: /apps/movies/${cleanPath}/playlist.m3u8`;
    showStatus('loading', '加载中...');

    // 并行拉取元数据（不影响播放）
    fetchMetadata(baseUrl, cleanPath);

    if (hls) {
        hls.destroy();
    }

    if (Hls.isSupported()) {
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
            video.play().catch(e => {
                console.error('自动播放失败:', e);
            });
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
        // Safari原生支持
        video.src = m3u8Url;
        video.addEventListener('loadedmetadata', function() {
            showStatus('playing', '播放中');
            video.play().catch(e => {
                console.error('自动播放失败:', e);
            });
        });

        video.addEventListener('error', function() {
            showError('播放失败，请检查文件是否存在');
        });

    } else {
        showError('您的浏览器不支持HLS播放');
    }
}

// ---- 元数据 ----

function hideMetadata() {
    metadataPanel.classList.remove('active');
}

function setMetaText(el, value) {
    // 字符串/数字都按文本；空值清空
    el.textContent = (value == null) ? '' : String(value);
}

function renderMetadata(data) {
    // 标题
    if (data.title) {
        setMetaText(metaTitle, data.title);
        metaTitle.style.display = '';
    } else {
        metaTitle.style.display = 'none';
    }

    // 番号 / 系列 / 制作商
    setMetaText(metaFanCode, data.fan_code || '');
    setMetaText(metaSeries, data.series || '');
    setMetaText(metaMaker, data.maker || '');

    // 演员（数组 → 用「、」拼接）
    const cast = data.cast;
    if (Array.isArray(cast) && cast.length) {
        setMetaText(metaCast, cast.join('、'));
    } else if (typeof cast === 'string' && cast) {
        setMetaText(metaCast, cast);
    } else {
        setMetaText(metaCast, '');
    }

    // 类型（数组 → 用「、」拼接）
    const genre = data.genre;
    if (Array.isArray(genre) && genre.length) {
        setMetaText(metaGenre, genre.join('、'));
    } else if (typeof genre === 'string' && genre) {
        setMetaText(metaGenre, genre);
    } else {
        setMetaText(metaGenre, '');
    }

    // 标签：渲染为 chips
    const tags = data.tags;
    metaTags.innerHTML = '';
    if (Array.isArray(tags) && tags.length) {
        tags.forEach(t => {
            const chip = document.createElement('span');
            chip.className = 'tag-chip';
            chip.textContent = t;
            metaTags.appendChild(chip);
        });
    }

    // 封面：有 url 才设 src，缺省隐藏
    if (data.cover) {
        metaCover.src = data.cover;
        metaCover.style.display = '';
    } else {
        metaCover.removeAttribute('src');
        metaCover.style.display = 'none';
    }

    metadataPanel.classList.add('active');
}

async function fetchMetadata(baseUrl, cleanPath) {
    hideMetadata();
    try {
        const resp = await fetch(`${baseUrl}/metadata/${cleanPath}`);
        if (resp.status === 404) return; // 没有 metadata 是合法情况
        if (!resp.ok) {
            console.warn('metadata 请求失败:', resp.status);
            return;
        }
        const data = await resp.json();
        if (data && typeof data === 'object') {
            renderMetadata(data);
        }
    } catch (e) {
        // 静默不报错，不影响视频播放
        console.debug('metadata 拉取异常:', e);
    }
}

// 回车键播放
mediaPathInput.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        loadVideo();
    }
});

// URL参数支持
const urlParams = new URLSearchParams(window.location.search);
const pathParam = urlParams.get('path');
if (pathParam) {
    mediaPathInput.value = pathParam;
    loadVideo();
}
