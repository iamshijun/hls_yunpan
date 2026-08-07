package xyz.asitanokibou.player.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshContainer
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import xyz.asitanokibou.player.baidu.BaiduYunClient
import xyz.asitanokibou.player.baidu.model.BaiduFile

/**
 * 极简的栈式导航，避免引入 Navigation Compose 依赖。
 * - [current] 是当前显示的屏，赋值时自动触发重组
 * - [_history] 只保存"非当前屏"的历史，用于回退；初始为空
 * - [push] 把当前屏压栈并切换到新屏；[pop] 出栈并回到上一屏
 */
class NavState {
    private val _history = ArrayDeque<Screen>()
    var current: Screen by mutableStateOf(Screen.Index)
        private set

    val canPop: Boolean get() = _history.isNotEmpty()

    fun push(screen: Screen) {
        _history.addLast(current)
        current = screen
    }

    fun pop() {
        if (_history.isNotEmpty()) {
            current = _history.removeLast()
        }
    }

    fun reset(screen: Screen) {
        _history.clear()
        current = screen
    }
}

sealed class Screen {
    object Index : Screen()
    object MovieList : Screen()
    /** 进入播放页，initialPath 为预填的媒体目录名（相对 /apps/movies），空串表示手动输入 */
    data class Play(val initialPath: String) : Screen()
    object Settings : Screen()
}

@Composable
fun rememberNavState(): NavState = remember { NavState() }

/**
 * 首页：让用户在两种进入方式间选择。
 * - "从列表选择"：拉取 /apps/movies 下的所有子目录，点选后跳到播放页
 * - "直接输入媒体名"：直接进入播放页，由用户手填路径
 */
@Composable
fun IndexScreen(
    onOpenList: () -> Unit,
    onOpenDirect: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("hls_pan_player", style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = onOpenSettings) { Text("设置") }
            }
            Spacer(Modifier.height(16.dp))
            Text(
                "选择进入方式",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            EntryCard(
                title = "从列表选择",
                subtitle = "浏览 /apps/movies 下的所有目录",
                onClick = onOpenList,
            )
            EntryCard(
                title = "直接输入媒体名",
                subtitle = "手动输入目录名后播放",
                onClick = onOpenDirect,
            )
        }
    }
}

@Composable
private fun EntryCard(
    title: String,
    subtitle: String,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(
                subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 列表页：分页拉取 /apps/movies 下的条目，仅展示 isdir==1 的目录；
 * 点击后将"相对 /apps/movies 的路径"回传给上层跳转播放页。
 *
 * - 首屏只拉 [PAGE_SIZE] 个，滚动到接近底部（最后可见 index >= total-3）时再拉下一页
 * - 通过 [BaiduYunClient.getFileList] 的 `result.size < limit` 推断末页
 * - 客户端过滤 `isdir == 1`：若过滤后当前页无目录但 API 仍返回满页，会继续翻页直到耗尽
 * - 加载更多失败时底部显示"点击重试"，不打断已加载的列表
 *
 * 注意：百度 list API errno!=0 时当前实现返回空列表（见 [BaiduYunClient.getFileList]），
 * 因此"暂无目录"无法区分"目录为空"与"鉴权/路径错误"。
 * 真实错误通常伴随日志（`BaiduYunClient` 内的 `Log.e`）。
 */
private const val MOVIE_LIST_PAGE_SIZE = 20

// 排序字段：与百度 list API 的 order 参数保持一致
private const val SORT_NAME = "name"
private const val SORT_TIME = "time"
private const val SORT_SIZE = "size"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MovieListScreen(
    baidu: BaiduYunClient?,
    hasToken: Boolean,
    onBack: () -> Unit,
    onPick: (relativePath: String) -> Unit,
) {
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val pullState = rememberPullToRefreshState()

    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var loadingMore by remember { mutableStateOf(false) }
    var loadMoreError by remember { mutableStateOf<String?>(null) }
    var dirs by remember { mutableStateOf<List<BaiduFile>>(emptyList()) }
    var nextStart by remember { mutableStateOf(0) }
    var hasMore by remember { mutableStateOf(true) }
    // 排序状态：name=默认按名；desc=true 降序，false 升序
    var sortOrder by remember { mutableStateOf(SORT_NAME) }
    var sortDesc by remember { mutableStateOf(false) }

    // 加载下一页：滚动触发的 auto-load 和 footer 上的"点击重试"共用这段逻辑
    suspend fun loadMore() {
        val client = baidu ?: return
        if (loadingMore || !hasMore) return
        loadingMore = true
        loadMoreError = null
        try {
            val page = client.getFileList(
                path = "/apps/movies",
                start = nextStart,
                limit = MOVIE_LIST_PAGE_SIZE,
                order = sortOrder,
                desc = if (sortDesc) 1 else 0,
            )
            val newDirs = page.filter { it.isdir == 1 }
            dirs = dirs + newDirs
            nextStart += page.size
            if (page.size < MOVIE_LIST_PAGE_SIZE) hasMore = false
        } catch (e: Exception) {
            loadMoreError = e.message ?: e::class.java.simpleName
        } finally {
            loadingMore = false
        }
    }

    // 首屏加载。排序变化时（sortOrder / sortDesc）也会重新触发：先清空旧数据再拉第一页。
    LaunchedEffect(baidu, hasToken, sortOrder, sortDesc) {
        if (!hasToken || baidu == null) {
            loading = false
            dirs = emptyList()
            error = null
            return@LaunchedEffect
        }
        loading = true
        error = null
        loadMoreError = null
        dirs = emptyList()
        nextStart = 0
        hasMore = true
        try {
            val first = baidu.getFileList(
                path = "/apps/movies",
                start = 0,
                limit = MOVIE_LIST_PAGE_SIZE,
                order = sortOrder,
                desc = if (sortDesc) 1 else 0,
            )
            dirs = first.filter { it.isdir == 1 }
            nextStart = first.size
            hasMore = first.size >= MOVIE_LIST_PAGE_SIZE
        } catch (e: Exception) {
            error = e.message ?: e::class.java.simpleName
        } finally {
            loading = false
        }
    }

    // 排序变化时滚回列表顶部，避免"切了排序但还停在原来的滚动位置"造成混淆
    LaunchedEffect(sortOrder, sortDesc) {
        listState.scrollToItem(0)
    }

    // 下拉刷新：用户松手后 isRefreshing 变 true → 重新拉第一页覆盖现有数据。
    // 与初始加载不同，刷新时不清空 dirs，避免列表闪烁；拉完新数据再一次性替换。
    if (pullState.isRefreshing) {
        LaunchedEffect(true) {
            val client = baidu
            if (client == null || !hasToken) {
                pullState.endRefresh()
            } else {
                try {
                    val first = client.getFileList(
                        path = "/apps/movies",
                        start = 0,
                        limit = MOVIE_LIST_PAGE_SIZE,
                        order = sortOrder,
                        desc = if (sortDesc) 1 else 0,
                    )
                    dirs = first.filter { it.isdir == 1 }
                    nextStart = first.size
                    hasMore = first.size >= MOVIE_LIST_PAGE_SIZE
                    loadMoreError = null
                    error = null
                } catch (e: Exception) {
                    error = e.message ?: e::class.java.simpleName
                } finally {
                    pullState.endRefresh()
                }
            }
        }
    }

    // 滚动接近底部 → 触发加载更多。
    // 用 derivedStateOf 把"是否需要加载下一页"打包成一个可订阅信号，
    // 让 LaunchedEffect 只在条件从 false→true 时才真正起一次协程。
    val shouldLoadMore by remember {
        derivedStateOf {
            if (loading || loadingMore || !hasMore || baidu == null) return@derivedStateOf false
            val info = listState.layoutInfo
            val total = info.totalItemsCount
            // LazyColumn 还没渲染出 item（首屏空 + 仍可能有更多）→ 立即触发，无需"接近底部"判断
            if (total == 0) return@derivedStateOf true
            val lastVisible = info.visibleItemsInfo.lastOrNull()?.index ?: -1
            lastVisible >= total - 3
        }
    }

    LaunchedEffect(shouldLoadMore) {
        if (shouldLoadMore) {
            scope.launch { loadMore() }
        }
    }

    Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .nestedScroll(pullState.nestedScrollConnection),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onBack) { Text("← 返回") }
                Spacer(Modifier.width(8.dp))
                Text("视频目录列表", style = MaterialTheme.typography.titleLarge)
            }
            // 排序条：三个 FilterChip 选排序字段，右侧 TextButton 切换升/降序
            SortBar(
                order = sortOrder,
                desc = sortDesc,
                onOrderChange = { sortOrder = it },
                onToggleDesc = { sortDesc = !sortDesc },
            )
            Spacer(Modifier.height(8.dp))

            when {
                !hasToken -> Text(
                    "请先在「设置」中填写百度网盘 access_token",
                    color = MaterialTheme.colorScheme.error,
                )

                loading -> Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }

                error != null -> Text(
                    "加载失败：$error",
                    color = MaterialTheme.colorScheme.error,
                )

                else -> LazyColumn(
                    state = listState,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(dirs, key = { it.fsId }) { dir ->
                        DirectoryItem(dir = dir, onClick = {
                            // 去掉 /apps/movies/ 前缀，得到相对路径（与代理层 convertToYunPath 拼回去的逻辑对齐）
                            val relative = dir.path
                                .removePrefix("/apps/movies/")
                                .trim('/')
                            onPick(relative)
                        })
                    }
                    // 互斥的 footer：加载中 → 失败重试 → 结束（无更多 / 全部加载完且为空）
                    when {
                        loadingMore -> item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                CircularProgressIndicator()
                            }
                        }
                        loadMoreError != null -> item {
                            TextButton(
                                onClick = { scope.launch { loadMore() } },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    "加载失败：${loadMoreError}，点击重试",
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                        }
                        !hasMore && dirs.isEmpty() -> item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(24.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "/apps/movies 下没有找到任何目录",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        !hasMore -> item {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "已经到底了",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
            }
            PullToRefreshContainer(
                state = pullState,
                modifier = Modifier.align(Alignment.TopCenter),
            )
        }
    }
}

@Composable
private fun DirectoryItem(dir: BaiduFile, onClick: () -> Unit) {
    val displayName = dir.path
        .removePrefix("/apps/movies/")
        .trim('/')
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(displayName, style = MaterialTheme.typography.titleMedium)
                Text(
                    dir.path,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text("播放", color = MaterialTheme.colorScheme.primary)
        }
    }
}

/**
 * 目录列表的排序条：
 * - 左侧三个 FilterChip 选择排序字段（名称 / 时间 / 大小），选中项高亮
 * - 右侧 TextButton 切换升/降序，显示当前方向（↑ 升序 / ↓ 降序）
 * - 排序变化由调用方更新状态，触发 [MovieListScreen] 重新拉第一页
 */
@Composable
private fun SortBar(
    order: String,
    desc: Boolean,
    onOrderChange: (String) -> Unit,
    onToggleDesc: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        FilterChip(
            selected = order == SORT_NAME,
            onClick = { onOrderChange(SORT_NAME) },
            label = { Text("名称") },
        )
        FilterChip(
            selected = order == SORT_TIME,
            onClick = { onOrderChange(SORT_TIME) },
            label = { Text("时间") },
        )
        FilterChip(
            selected = order == SORT_SIZE,
            onClick = { onOrderChange(SORT_SIZE) },
            label = { Text("大小") },
        )
        Spacer(Modifier.weight(1f))
        TextButton(onClick = onToggleDesc) {
            // 用 Unicode 箭头避免引入 material-icons 依赖
            Text(if (desc) "↓ 降序" else "↑ 升序")
        }
    }
}
