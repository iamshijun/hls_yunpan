package xyz.asitanokibou.player.ui

import android.content.Context
import android.util.AttributeSet
import android.view.GestureDetector
import android.view.MotionEvent
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.PlayerView
import kotlin.math.abs
import kotlin.math.min

/**
 * 带手势控制的 PlayerView，交互风格类似 YouTube / Bilibili：
 * - 水平滑动 → 快进/快退（拖动时只预览，松手才 [onSeekCommit]）
 * - 左半屏竖滑 → 亮度；右半屏竖滑 → 音量
 * - 双击左/右半屏 → 快退/快进 10s
 * - 单击视频区 → 切换控制栏（沿用 PlayerView 自带的 performClick 逻辑）
 *
 * 手势识别放在 [onTouchEvent]：视频区域的触摸不会被 PlayerView 的子 View
 * （SurfaceView / 控制栏背景）消费，会回落到 onTouchEvent，因此无需拦截，
 * 控制栏上的进度条/按钮仍由默认 PlayerControlView 处理，二者互不干扰。
 */
@OptIn(UnstableApi::class)
class GesturePlayerView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : PlayerView(context, attrs, defStyleAttr) {

    /** 水平 seek 预览：参数为相对手势起点的累计偏移（秒，正=快进） */
    var onSeekPreview: ((Float) -> Unit)? = null

    /** 水平 seek 松手提交（无参，具体偏移由上层已记录的预览值决定） */
    var onSeekCommit: (() -> Unit)? = null

    /** 水平 seek 被中断（ACTION_CANCEL）时清除浮层，不提交跳转 */
    var onSeekCancel: (() -> Unit)? = null

    /** 竖滑调整：参数 1 为相对手势起点的累计偏移（-1..1，正=向上），参数 2 为是否左半屏 */
    var onVerticalDrag: ((fraction: Float, isLeftHalf: Boolean) -> Unit)? = null

    /** 竖滑结束（隐藏音量/亮度浮层） */
    var onVerticalDragEnd: (() -> Unit)? = null

    /** 双击：side = -1（左半屏快退）或 +1（右半屏快进） */
    var onDoubleTap: ((side: Int) -> Unit)? = null

    private var seeking = false
    private var verticalDragging = false
    private var dragIsLeftHalf = false

    private val gestureDetector = GestureDetector(
        context,
        object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean = true

            override fun onScroll(
                e1: MotionEvent?,
                e2: MotionEvent,
                distanceX: Float,
                distanceY: Float,
            ): Boolean {
                val startX = e1?.x ?: e2.x
                val startY = e1?.y ?: e2.y
                // 首次确定手势方向后不再切换，避免斜滑时在 seek/竖滑之间抖动
                if (!seeking && !verticalDragging) {
                    if (abs(e2.x - startX) > abs(e2.y - startY)) {
                        seeking = true
                    } else {
                        verticalDragging = true
                        dragIsLeftHalf = startX < width / 2f
                    }
                    hideController() // 手势期间隐藏默认控制栏，避免遮挡
                }

                if (seeking) {
                    val deltaSec = (e2.x - startX) / width * seekRangeSec()
                    onSeekPreview?.invoke(deltaSec)
                } else if (verticalDragging) {
                    // 相对手势起点的累计偏移；向上滑动为负 → 取负号转成"向上=正值"
                    val fraction = (-(e2.y - startY) / height).coerceIn(-1f, 1f)
                    onVerticalDrag?.invoke(fraction, dragIsLeftHalf)
                }
                return true
            }

            override fun onDoubleTap(e: MotionEvent): Boolean {
                val side = if (e.x < width / 2f) -1 else 1
                onDoubleTap?.invoke(side)
                return true
            }
        },
    )

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        gestureDetector.onTouchEvent(ev)

        when (ev.actionMasked) {
            MotionEvent.ACTION_UP -> {
                if (seeking) onSeekCommit?.invoke()
                if (verticalDragging) onVerticalDragEnd?.invoke()
                resetGestureState()
            }
            MotionEvent.ACTION_CANCEL -> {
                // 手势被打断：丢弃 seek，仅收起浮层
                if (seeking) onSeekCancel?.invoke()
                if (verticalDragging) onVerticalDragEnd?.invoke()
                resetGestureState()
            }
        }

        // 非手势触摸（单击等）交给 PlayerView 自带逻辑（点击切换控制栏）
        return super.onTouchEvent(ev)
    }

    private fun resetGestureState() {
        seeking = false
        verticalDragging = false
    }

    /** 满屏水平滑动对应的秒数：随视频时长缩放，上限 [MAX_SEEK_RANGE_SEC] */
    private fun seekRangeSec(): Float {
        val durationMs = player?.duration ?: 0L
        if (durationMs <= 0) return MAX_SEEK_RANGE_SEC
        return min(durationMs / 1000f * SEEK_RANGE_RATIO, MAX_SEEK_RANGE_SEC)
    }

    private companion object {
        /** 满屏滑动最多 seek 的秒数 */
        const val MAX_SEEK_RANGE_SEC = 180f

        /** 满屏滑动 seek 占视频总时长的比例 */
        const val SEEK_RANGE_RATIO = 0.3f
    }
}
