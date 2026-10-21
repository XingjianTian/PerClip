package com.sudox.perclip.ui.recall

import android.provider.Settings
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Workspaces
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.key
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.recall.repository.RecallDomainMemory
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.recall.repository.RecallResurfaceItem
import com.sudox.perclip.recall.repository.MemoryPlanetMemory
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.ui.PerClipSourceIcon
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import kotlin.math.cos
import kotlin.math.sin

private val RecallPurple = Color(0xFF765BFF)
private val RecallGreen = Color(0xFF45BD8B)
private val RecallOrange = Color(0xFFFF942F)
private val RecallBlue = Color(0xFF58AEF4)

private data class RecallPalette(val page: Color, val surface: Color, val ink: Color, val muted: Color, val line: Color, val soft: Color, val accentText: Color, val dark: Boolean)

@Composable private fun recallPalette(): RecallPalette = if (MaterialTheme.colorScheme.background.luminance() < .5f) {
    RecallPalette(
        ColorTokens.DarkPlumBackground,
        ColorTokens.DarkPlumSurface,
        ColorTokens.DarkPlumText,
        ColorTokens.DarkPlumSecondary,
        ColorTokens.DarkPlumBorder,
        ColorTokens.DarkPlumAccentSoft,
        ColorTokens.DarkPlumPlanet,
        true,
    )
} else {
    RecallPalette(Color(0xFFFAF9FE), Color.White, Color(0xFF17152F), Color(0xFF69647D), Color(0xFFCFC5E6), Color(0xFFF0EBFF), RecallPurple, false)
}

internal object RecallAutoRotationPolicy {
    fun canRotate(
        presentation: RecallPresentationState,
        topicCount: Int,
        reducedMotion: Boolean,
        menuOpen: Boolean = false,
        filterOverlayOpen: Boolean = false,
    ): Boolean = presentation.autoSurfaceEnabled &&
        presentation.scope == RecallScope.ALL_TOPICS &&
        !reducedMotion &&
        !menuOpen &&
        !filterOverlayOpen &&
        topicCount > 1
}

internal enum class RecallFilterOverlay {
    NONE,
    PERIOD_MENU,
    KNOWLEDGE_BASE_MENU,
    DATE_PICKER,
    ;

    val isOpen: Boolean get() = this != NONE
}

internal enum class RecallFilterOverlayEvent {
    OPEN_PERIOD_MENU,
    OPEN_KNOWLEDGE_BASE_MENU,
    OPEN_DATE_PICKER,
    DISMISS,
    CONFIRM,
    CANCEL,
    SELECT,
}

internal data class RecallFilterOverlayTransition(
    val overlay: RecallFilterOverlay,
    val interactionRequired: Boolean,
)

internal object RecallFilterOverlayPolicy {
    fun reduce(
        current: RecallFilterOverlay,
        event: RecallFilterOverlayEvent,
    ): RecallFilterOverlayTransition {
        val next = when (event) {
            RecallFilterOverlayEvent.OPEN_PERIOD_MENU -> RecallFilterOverlay.PERIOD_MENU
            RecallFilterOverlayEvent.OPEN_KNOWLEDGE_BASE_MENU -> RecallFilterOverlay.KNOWLEDGE_BASE_MENU
            RecallFilterOverlayEvent.OPEN_DATE_PICKER -> RecallFilterOverlay.DATE_PICKER
            RecallFilterOverlayEvent.DISMISS,
            RecallFilterOverlayEvent.CONFIRM,
            RecallFilterOverlayEvent.CANCEL,
            RecallFilterOverlayEvent.SELECT,
            -> RecallFilterOverlay.NONE
        }
        return RecallFilterOverlayTransition(
            overlay = next,
            interactionRequired = current != next && (!current.isOpen || !next.isOpen),
        )
    }
}

internal object RecallOrbitPolicy {
    const val CYCLE_MILLIS = 24_000
    const val INTERACTION_PAUSE_MILLIS = 2_000L
    const val TILT_DEGREES = 8f

    fun canOrbit(presentation: RecallPresentationState, topicCount: Int, reducedMotion: Boolean): Boolean =
        presentation.autoSurfaceEnabled && presentation.graphExpanded && !reducedMotion && topicCount > 1

    fun remainingPauseMillis(lastInteractionAt: Long, now: Long): Long =
        (INTERACTION_PAUSE_MILLIS - (now - lastInteractionAt)).coerceAtLeast(0L)
}

internal object RecallSatellitePolicy {
    const val CYCLE_MILLIS = 60_000
    const val RADIUS_X = 94f
    const val RADIUS_Y = 58f
}

internal object RecallQueuePolicy {
    const val DWELL_MILLIS = 5_000L
    const val TRANSITION_MILLIS = 600
    const val BROWSE_RESUME_DELAY_MILLIS = 2_000L
    const val STANDARD_FULL_CARD_COUNT = 3
    const val VISIBLE_CARD_COUNT = 4
    const val MAX_QUEUE_ITEMS = 12

    fun canAdvance(
        itemCount: Int,
        autoSurfaceEnabled: Boolean,
        graphExpanded: Boolean,
        reducedMotion: Boolean,
        browsingAll: Boolean = false,
        menuOpen: Boolean = false,
        filterOverlayOpen: Boolean = false,
    ): Boolean = itemCount > VISIBLE_CARD_COUNT &&
        autoSurfaceEnabled &&
        graphExpanded &&
        !reducedMotion &&
        !browsingAll &&
        !menuOpen &&
        !filterOverlayOpen

    fun shouldEnterBrowse(itemCount: Int, isAtTop: Boolean, isScrollInProgress: Boolean): Boolean =
        itemCount > STANDARD_FULL_CARD_COUNT && isScrollInProgress && !isAtTop
}

internal data class MemoryPlanetListWindow(
    val cardHeightDp: Float,
    val fullCardCount: Int,
    val previewDp: Float,
    val windowHeightDp: Float,
)

internal object MemoryPlanetListWindowPolicy {
    const val STANDARD_CARD_HEIGHT_DP = 108f
    const val CARD_GAP_DP = 10f
    const val FOURTH_PREVIEW_DP = 66f

    fun calculate(fontScale: Float): MemoryPlanetListWindow {
        val normalizedScale = fontScale.coerceAtLeast(1f)
        val largeType = normalizedScale >= 1.25f
        val cardHeight = STANDARD_CARD_HEIGHT_DP * normalizedScale
        val fullCount = if (largeType) 2 else 3
        return MemoryPlanetListWindow(
            cardHeightDp = cardHeight,
            fullCardCount = fullCount,
            previewDp = FOURTH_PREVIEW_DP,
            windowHeightDp = cardHeight * fullCount + CARD_GAP_DP * fullCount + FOURTH_PREVIEW_DP,
        )
    }

    fun bottomPaddingDp(navigationHeightDp: Float, safeInsetDp: Float): Float =
        navigationHeightDp.coerceAtLeast(0f) + safeInsetDp.coerceAtLeast(0f) + 16f
}

internal object MemoryPlanetVNextLayoutPolicy {
    // The home surface is intentionally a single viewport: header + this card
    // must fit above the persistent bottom navigation on the compact emulator.
    const val CARD_HEIGHT_DP = 561f
    const val CONTROL_HEIGHT_DP = 48f
    const val CONTROL_DIVIDER_HEIGHT_DP = 1f
    const val GRAPH_HEIGHT_DP = 270f
    const val DIVIDER_HEIGHT_DP = 6f
    const val INSIGHT_HEIGHT_DP = 236f

    private const val HOME_TOP_PADDING_DP = 8f
    private const val HOME_BOTTOM_PADDING_DP = 18f
    private const val HEADER_HEIGHT_DP = 48f
    private const val HEADER_CARD_GAP_DP = 8f

    fun cardHeightForViewport(viewportHeightDp: Float): Float =
        (viewportHeightDp - HOME_TOP_PADDING_DP - HOME_BOTTOM_PADDING_DP - HEADER_HEIGHT_DP - HEADER_CARD_GAP_DP)
            .coerceAtLeast(CARD_HEIGHT_DP)

    fun graphHeightForCard(cardHeightDp: Float, hasControls: Boolean = true): Float {
        if (!hasControls) return GRAPH_HEIGHT_DP
        return (
            cardHeightDp - CONTROL_HEIGHT_DP - CONTROL_DIVIDER_HEIGHT_DP -
                DIVIDER_HEIGHT_DP - INSIGHT_HEIGHT_DP
            ).coerceAtLeast(GRAPH_HEIGHT_DP)
    }
}

internal fun <T> recallQueueWindow(items: List<T>, offset: Int, count: Int): List<T> {
    if (items.isEmpty() || count <= 0) return emptyList()
    val size = minOf(items.size, count)
    val start = offset.mod(items.size)
    return List(size) { index -> items[(start + index).mod(items.size)] }
}

internal data class RecallOrbitPoint(val x: Float, val y: Float)

internal fun recallOrbitPoint(
    centerX: Float,
    centerY: Float,
    radiusX: Float,
    radiusY: Float,
    angleDegrees: Float,
    tiltDegrees: Float = RecallOrbitPolicy.TILT_DEGREES,
): RecallOrbitPoint {
    val angle = Math.toRadians(angleDegrees.toDouble())
    val tilt = Math.toRadians(tiltDegrees.toDouble())
    val dx = cos(angle).toFloat() * radiusX
    val dy = sin(angle).toFloat() * radiusY
    return RecallOrbitPoint(
        x = centerX + dx * cos(tilt).toFloat() - dy * sin(tilt).toFloat(),
        y = centerY + dx * sin(tilt).toFloat() + dy * cos(tilt).toFloat(),
    )
}

internal data class RecallMemoryPresentation(
    val clipId: String,
    val clientRequestId: String,
    val topicId: String,
    val topicIds: List<String>,
    val title: String,
    val summary: String,
    val sourceType: String,
    val sourceLabel: String,
    val tags: List<String>,
    val capturedAt: String,
)

internal data class RecallTopicInsight(
    val topicId: String,
    val label: String,
    val colorSlot: Int,
    val inWindowCount: Int,
    val periodLabel: String,
    val summary: String,
    val recalledCount: Int,
    val keywords: List<String>,
)

internal fun recallTopicInsight(
    state: RecallUiState,
    topics: List<RecallDomainTopic>,
    activeTopicId: String,
    surfacedCount: Int = 0,
): RecallTopicInsight? {
    val topic = topics.firstOrNull { it.id == activeTopicId } ?: topics.firstOrNull() ?: return null
    val domainMemories = state.domain.value?.memories.orEmpty().filter { memory ->
        memory.primaryTopicId == topic.id || topic.id in memory.topicIds
    }
    val planetMemories = state.memoryPlanet.value?.topics.orEmpty()
        .firstOrNull { it.topicId == topic.id }
        ?.memories
        .orEmpty()
    val recordedRecallCount = domainMemories.count { it.recallCount > 0 }
    val keywords = domainMemories.flatMap { it.tags }
        .map(String::trim)
        .filter(String::isNotBlank)
        .distinct()
        .take(6)
        .ifEmpty {
            recallTopicKeywordFallback(
                (planetMemories.map { it.title } + domainMemories.map { it.label }),
            )
        }
    val summary = (domainMemories.map { it.summary } + planetMemories.map { it.summary })
        .firstOrNull { it.isNotBlank() }
        ?.trim()
        .orEmpty()
        .ifBlank { "围绕${topic.label}的近期记忆已整理到这里。" }
    return RecallTopicInsight(
        topicId = topic.id,
        label = topic.label,
        colorSlot = topic.colorSlot,
        inWindowCount = topic.clipCount,
        periodLabel = recallPeriodLabel(
            state.presentation.period,
            state.presentation.customStartDate,
            state.presentation.customEndDate,
        ),
        summary = summary,
        // A memory is considered "回溯" once it has appeared in the planet's
        // rotating satellite set. Keep server-recorded recall events as a
        // floor, so the number never regresses when the display rotates.
        recalledCount = maxOf(recordedRecallCount, surfacedCount).coerceAtMost(topic.clipCount),
        keywords = keywords,
    )
}

internal fun recallSurfacedMemoryCount(
    availableMemoryCount: Int,
    visibleMemoryLabels: Int,
    queueAdvanceCount: Int,
    topicMemoryCount: Int,
): Int {
    if (availableMemoryCount <= 0 || topicMemoryCount <= 0) return 0
    val initialCount = minOf(availableMemoryCount, visibleMemoryLabels.coerceIn(1, 5))
    return (initialCount + queueAdvanceCount.coerceAtLeast(0)).coerceAtMost(topicMemoryCount)
}

internal fun recallTopicKeywordFallback(values: List<String>): List<String> = values
    .flatMap { value -> value.split(Regex("[\\s,，。；;、/|:：]+")) }
    .map { it.trim().take(10) }
    .filter { it.length >= 2 }
    .distinct()
    .take(6)

internal fun recallTopicKeywordDisplay(values: List<String>): List<String> =
    values.ifEmpty { listOf("无") }

internal fun recallVisibleTopics(state: RecallUiState): List<RecallDomainTopic> = (
    state.memoryPlanet.value?.topics?.mapIndexed { index, topic ->
        RecallDomainTopic(
            id = topic.topicId,
            label = topic.displayName,
            shortLabel = topic.displayName,
            clipCount = topic.memoryCount,
            weight = topic.memoryCount.toDouble(),
            sizeWeight = topic.memoryCount.toDouble(),
            colorSlot = index,
        )
    } ?: state.domain.value?.topics.orEmpty()
)
    .filterNot { it.id in state.presentation.hiddenTopicIds }
    .take(state.presentation.visibleTopicCount.coerceIn(1, 5))

internal fun recallVisibleMemories(state: RecallUiState, forceTopic: Boolean = false): List<RecallMemoryPresentation> {
    val active = state.presentation.activeTopicId
    state.memoryPlanet.value?.let { planet ->
        val topicMemories = planet.topics.flatMap { topic ->
            topic.memories.map { memory -> memory.toPresentation(topic.topicId) }
        }
        // The planet endpoint intentionally returns five representative labels,
        // while the domain snapshot contains the bounded queue used for the
        // next satellite rotation. Merge both so a new memory can enter when
        // one of the five visible labels leaves the orbit.
        val domainMemories = state.domain.value?.memories.orEmpty().map(RecallDomainMemory::toPresentation)
        val unclassified = planet.unclassifiedPreview.map { memory -> memory.toPresentation("unclassified") }
        val unique = (topicMemories + domainMemories + unclassified).distinctBy(RecallMemoryPresentation::clipId)
        return unique
            .filter { active.isBlank() || it.topicId == active || active in it.topicIds }
            .take(RecallQueuePolicy.MAX_QUEUE_ITEMS)
    }
    val domainMemories = state.domain.value?.memories.orEmpty()
    val domainByClip = domainMemories.associateBy { memory -> memory.clipId.ifBlank { memory.id } }
    val remote = state.resurfaced.value?.items.orEmpty().map { item ->
        item.toPresentation().copy(topicIds = domainByClip[item.clipId]?.topicIds.orEmpty().ifEmpty { listOf(item.topicId) })
    }
    val domain = domainMemories.map(RecallDomainMemory::toPresentation)
    val merged = (remote + domain).distinctBy { it.clipId }
    val filtered = if (active.isBlank()) merged else merged.filter { it.topicId == active || active in it.topicIds }
    return filtered.take(RecallQueuePolicy.MAX_QUEUE_ITEMS)
}

private fun MemoryPlanetMemory.toPresentation(topicId: String) = RecallMemoryPresentation(
    clipId = clipId,
    clientRequestId = "",
    topicId = topicId,
    topicIds = listOf(topicId),
    title = title,
    summary = summary,
    sourceType = source,
    sourceLabel = source,
    tags = emptyList(),
    capturedAt = capturedAt,
)

private fun RecallResurfaceItem.toPresentation() = RecallMemoryPresentation(
    clipId, clientRequestId, topicId, listOf(topicId), title.ifBlank { "未命名记忆" }, summary.ifBlank { safeExcerpt }, sourceType,
    sourceLabel, tags.take(3), capturedAt,
)

private fun RecallDomainMemory.toPresentation() = RecallMemoryPresentation(
    clipId.ifBlank { id }, clientRequestId, primaryTopicId, topicIds.ifEmpty { listOf(primaryTopicId) }, label.ifBlank { shortLabel.ifBlank { "未命名记忆" } },
    summary.ifBlank { safeExcerpt }, sourceType, sourceLabel, tags.take(3), capturedAt,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun RecallHomeContent(
    state: RecallUiState,
    padding: PaddingValues,
    knowledgeBases: List<KnowledgeBaseSummary>,
    knowledgeBasesLoading: Boolean,
    knowledgeBaseListMessage: String,
    onRefreshKnowledgeBases: () -> Unit,
    onOpenDisplaySettings: () -> Unit,
    onRefresh: () -> Unit,
    onTopicSelected: (String) -> Unit,
    onPeriod: (RecallPeriod) -> Unit,
    onCustomRange: (String, String, String) -> Unit,
    customRangeAvailable: Boolean,
    onKnowledgeBaseSelected: (String) -> Unit,
    onReducedMotion: (Boolean) -> Unit,
    onRotateTopic: () -> Unit,
    onInteraction: () -> Unit,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
    onSuppress: (RecallMemoryPresentation) -> Unit,
    onRestore: (RecallSuppressedItem) -> Unit,
    onSuppressionPage: (String) -> Unit,
    onNoticeShown: () -> Unit,
    reducedMotionOverride: Boolean = false,
) {
    val palette = recallPalette()
    val context = LocalContext.current
    val systemReducedMotion = remember {
        runCatching { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE) == 0f }.getOrDefault(false)
    }
    val reducedMotion = systemReducedMotion || reducedMotionOverride
    val quality = rememberMemoryPlanetQuality(reducedMotion, systemReducedMotion)
    val presentation = state.presentation
    val topics = recallVisibleTopics(state)
    val listState = rememberLazyListState()
    var browsingAllMemories by rememberSaveable { mutableStateOf(false) }
    var memoryMenuOpen by remember { mutableStateOf(false) }
    var filterOverlay by rememberSaveable { mutableStateOf(RecallFilterOverlay.NONE) }
    var snackbarOpen by remember { mutableStateOf(false) }
    var planetVisible by remember { mutableStateOf(true) }
    val snackbars = remember { SnackbarHostState() }
    var showSuppressed by rememberSaveable { mutableStateOf(false) }
    val motionClock = remember { MemoryPlanetMotionClock() }
    val lifecycleActive = rememberMemoryPlanetLifecycleActive()
    val filterOverlayOpen = filterOverlay.isOpen
    val planetContent = memoryPlanetContentState(
        memoryPlanetLoading = state.memoryPlanet.loading,
        memoryPlanetError = state.memoryPlanet.error,
        domainError = state.domain.error,
        topicCount = topics.size,
    )

    MemoryPlanetMotionClockDriver(
        clock = motionClock,
        running = MemoryPlanetClockPolicy.shouldRun(
            lifecycleActive = lifecycleActive,
            planetVisible = planetVisible,
            graphExpanded = true,
            contentState = planetContent,
            quality = quality,
            reducedMotion = reducedMotion,
            browsingAll = browsingAllMemories,
            menuOpen = memoryMenuOpen,
            filterOverlayOpen = filterOverlayOpen,
            snackbarOpen = snackbarOpen,
            suppressionSheetOpen = showSuppressed,
        ),
        lastInteractionAt = presentation.lastInteractionAt,
    )

    LaunchedEffect(reducedMotion) { onReducedMotion(reducedMotion) }
    LaunchedEffect(state.notice) {
        if (state.notice.isNotBlank()) {
            snackbarOpen = true
            onInteraction()
            snackbars.showSnackbar(state.notice)
            snackbarOpen = false
            onNoticeShown()
        }
    }

    LaunchedEffect(listState) {
        snapshotFlow { listState.isScrollInProgress }.distinctUntilChanged().collect { if (it) onInteraction() }
    }
    LaunchedEffect(listState) {
        snapshotFlow {
            listState.layoutInfo.visibleItemsInfo.any { item ->
                item.key in setOf("graph", "loading", "error", "empty")
            }
        }.distinctUntilChanged().collect { visible -> planetVisible = visible }
    }
    LaunchedEffect(
        presentation.autoSurfaceEnabled,
        presentation.lastInteractionAt,
        presentation.activeTopicId,
        presentation.scope,
        reducedMotion,
        topics.size,
        browsingAllMemories,
        memoryMenuOpen,
        filterOverlayOpen,
    ) {
        if (browsingAllMemories || memoryMenuOpen || filterOverlayOpen) return@LaunchedEffect
        if (!RecallAutoRotationPolicy.canRotate(
                presentation,
                topics.size,
                reducedMotion,
                memoryMenuOpen,
                filterOverlayOpen,
            )
        ) return@LaunchedEffect
        val remainingPause = RecallOrbitPolicy.remainingPauseMillis(presentation.lastInteractionAt, System.currentTimeMillis())
        if (remainingPause > 0L) delay(remainingPause)
        delay(8_000L)
        onRotateTopic()
    }

    Box(Modifier.fillMaxSize().background(palette.page)) {
        BoxWithConstraints(
            Modifier
                .fillMaxSize()
                .padding(
                    top = padding.calculateTopPadding(),
                    bottom = padding.calculateBottomPadding(),
                ),
        ) {
            val cardHeightDp = MemoryPlanetVNextLayoutPolicy.cardHeightForViewport(maxHeight.value)
            RecallHomeList(
                state = state,
                listState = listState,
                modifier = Modifier.fillMaxSize(),
                cardHeightDp = cardHeightDp,
                onOpenDisplaySettings = onOpenDisplaySettings,
                reducedMotion = reducedMotion,
                onRefresh = onRefresh,
                onTopicSelected = onTopicSelected,
                onPeriod = onPeriod,
                onCustomRange = onCustomRange,
                customRangeAvailable = customRangeAvailable,
                onKnowledgeBaseSelected = onKnowledgeBaseSelected,
                knowledgeBases = knowledgeBases,
                knowledgeBasesLoading = knowledgeBasesLoading,
                knowledgeBaseListMessage = knowledgeBaseListMessage,
                onRefreshKnowledgeBases = onRefreshKnowledgeBases,
                motionElapsedMillis = motionClock.elapsedMillis,
                starfieldQuality = quality,
                planetContent = planetContent,
                onBrowsingAllChanged = { browsingAllMemories = it },
                menuOpen = memoryMenuOpen,
                filterOverlay = filterOverlay,
                onFilterOverlayEvent = { event ->
                    val transition = RecallFilterOverlayPolicy.reduce(filterOverlay, event)
                    filterOverlay = transition.overlay
                    if (transition.interactionRequired) onInteraction()
                },
                onMenuVisibilityChanged = { open ->
                    memoryMenuOpen = open
                    onInteraction()
                },
                onInteraction = onInteraction,
                onOpenOriginal = onOpenOriginal,
                onSuppress = onSuppress,
                onRestore = onRestore,
                onShowAllSuppressed = { showSuppressed = true },
            )
        }
        SnackbarHost(snackbars, Modifier.align(Alignment.BottomCenter).padding(bottom = padding.calculateBottomPadding()))
    }
    if (showSuppressed) {
        val page = state.suppressed.value
        ModalBottomSheet(
            onDismissRequest = { showSuppressed = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = palette.surface,
        ) {
            Column(
                Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 28.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("不再浮现的记忆", color = palette.ink, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("逐条恢复；每页最多 50 条，可前后翻页访问全部记忆。", color = palette.muted, fontSize = 12.sp)
                LazyColumn(Modifier.fillMaxWidth().height(420.dp)) {
                    items(page?.items.orEmpty(), key = { it.clipId }) { item ->
                        RecallSuppressedRow(item, onRestore)
                    }
                    item("page-controls") {
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            TextButton(
                                onClick = {
                                    page?.previousCursor
                                        ?.takeIf(String::isNotBlank)
                                        ?.let(onSuppressionPage)
                                },
                                enabled = !state.suppressed.loading &&
                                    !page?.previousCursor.isNullOrBlank(),
                            ) { Text("上一页") }
                            Text(
                                "本页 ${page?.items?.size ?: 0} 条",
                                color = palette.muted,
                                fontSize = 12.sp,
                                modifier = Modifier.align(Alignment.CenterVertically),
                            )
                            TextButton(
                                onClick = {
                                    page?.nextCursor
                                        ?.takeIf(String::isNotBlank)
                                        ?.let(onSuppressionPage)
                                },
                                enabled = !state.suppressed.loading &&
                                    !page?.nextCursor.isNullOrBlank(),
                            ) { Text(if (state.suppressed.loading) "读取中…" else "下一页") }
                        }
                    }
                }
            }
        }
    }
}

internal fun memoryPlanetContentState(
    memoryPlanetLoading: Boolean,
    memoryPlanetError: String,
    domainError: String,
    topicCount: Int,
): MemoryPlanetContentState = when {
    memoryPlanetLoading -> MemoryPlanetContentState.LOADING
    memoryPlanetError.isNotBlank() || domainError.isNotBlank() -> MemoryPlanetContentState.API_UNAVAILABLE
    topicCount == 0 -> MemoryPlanetContentState.EMPTY
    else -> MemoryPlanetContentState.NORMAL
}

@Composable
private fun RecallHomeList(
    state: RecallUiState,
    listState: LazyListState,
    modifier: Modifier,
    cardHeightDp: Float,
    knowledgeBases: List<KnowledgeBaseSummary>,
    knowledgeBasesLoading: Boolean,
    knowledgeBaseListMessage: String,
    onRefreshKnowledgeBases: () -> Unit,
    onOpenDisplaySettings: () -> Unit,
    reducedMotion: Boolean,
    onRefresh: () -> Unit,
    onTopicSelected: (String) -> Unit,
    onPeriod: (RecallPeriod) -> Unit,
    onCustomRange: (String, String, String) -> Unit,
    customRangeAvailable: Boolean,
    onKnowledgeBaseSelected: (String) -> Unit,
    motionElapsedMillis: Long,
    starfieldQuality: MemoryPlanetQuality,
    planetContent: MemoryPlanetContentState,
    onBrowsingAllChanged: (Boolean) -> Unit,
    menuOpen: Boolean,
    filterOverlay: RecallFilterOverlay,
    onFilterOverlayEvent: (RecallFilterOverlayEvent) -> Unit,
    onMenuVisibilityChanged: (Boolean) -> Unit,
    onInteraction: () -> Unit,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
    onSuppress: (RecallMemoryPresentation) -> Unit,
    onRestore: (RecallSuppressedItem) -> Unit,
    onShowAllSuppressed: () -> Unit,
) {
    val palette = recallPalette()
    val topics = recallVisibleTopics(state)
    val active = topics.firstOrNull { it.id == state.presentation.activeTopicId } ?: topics.firstOrNull()
    val activeTopicId = active?.id.orEmpty()
    val visibleMemories = recallVisibleMemories(
        state.copy(presentation = state.presentation.copy(activeTopicId = activeTopicId)),
    )
    val queueKey = visibleMemories.joinToString(separator = "|") { it.clipId }
    var queueOffset by remember(activeTopicId, queueKey) { mutableIntStateOf(0) }
    var queueAdvanceCount by remember(activeTopicId, queueKey) { mutableIntStateOf(0) }
    var browsingAll by remember(activeTopicId, queueKey) { mutableStateOf(false) }
    val queueProgress = remember(activeTopicId, queueKey) { Animatable(0f) }
    val topicInsight = recallTopicInsight(
        state = state,
        topics = topics,
        activeTopicId = activeTopicId,
        surfacedCount = recallSurfacedMemoryCount(
            availableMemoryCount = visibleMemories.size,
            visibleMemoryLabels = state.presentation.visibleMemoryLabels,
            queueAdvanceCount = queueAdvanceCount,
            topicMemoryCount = active?.clipCount ?: 0,
        ),
    )
    val isAtTop by remember(listState) {
        derivedStateOf { listState.firstVisibleItemIndex == 0 && listState.firstVisibleItemScrollOffset == 0 }
    }
    val queueCanAdvance = RecallQueuePolicy.canAdvance(
        itemCount = visibleMemories.size,
        autoSurfaceEnabled = state.presentation.autoSurfaceEnabled,
        graphExpanded = true,
        reducedMotion = reducedMotion,
        browsingAll = browsingAll,
        menuOpen = menuOpen,
        filterOverlayOpen = filterOverlay.isOpen,
    )

    LaunchedEffect(activeTopicId, queueKey) {
        browsingAll = false
        onBrowsingAllChanged(false)
    }

    LaunchedEffect(listState, activeTopicId, queueKey) {
        snapshotFlow {
            Triple(
                listState.firstVisibleItemIndex == 0 && listState.firstVisibleItemScrollOffset == 0,
                listState.isScrollInProgress,
                visibleMemories.size,
            )
        }.distinctUntilChanged().collect { (atTop, scrolling, itemCount) ->
            if (RecallQueuePolicy.shouldEnterBrowse(itemCount, atTop, scrolling)) {
                browsingAll = true
                onBrowsingAllChanged(true)
            }
        }
    }

    LaunchedEffect(browsingAll, isAtTop) {
        if (!browsingAll || !isAtTop) return@LaunchedEffect
        delay(RecallQueuePolicy.BROWSE_RESUME_DELAY_MILLIS)
        browsingAll = false
        onBrowsingAllChanged(false)
    }

    LaunchedEffect(
        activeTopicId,
        queueKey,
        queueCanAdvance,
        state.presentation.lastInteractionAt,
    ) {
        if (!queueCanAdvance) return@LaunchedEffect
        val remainingPause = RecallOrbitPolicy.remainingPauseMillis(
            state.presentation.lastInteractionAt,
            System.currentTimeMillis(),
        )
        if (remainingPause > 0L) delay(remainingPause)
        while (true) {
            if (queueProgress.value <= 0f) delay(RecallQueuePolicy.DWELL_MILLIS)
            val remainingTransition = (
                RecallQueuePolicy.TRANSITION_MILLIS * (1f - queueProgress.value.coerceIn(0f, 1f))
            ).toInt().coerceAtLeast(1)
            queueProgress.animateTo(
                targetValue = 1f,
                animationSpec = tween(remainingTransition, easing = FastOutSlowInEasing),
            )
            queueOffset = (queueOffset + 1).mod(visibleMemories.size)
            queueAdvanceCount += 1
            queueProgress.snapTo(0f)
        }
    }

    LazyColumn(
        modifier = modifier.background(palette.page),
        state = listState,
        userScrollEnabled = false,
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 18.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item("header") {
            RecallHeader(
                onOpenDisplaySettings = onOpenDisplaySettings,
                hasSuppressed = state.suppressed.value?.items.orEmpty().isNotEmpty(),
                onOpenSuppressed = onShowAllSuppressed,
            )
        }
        item("graph") {
            RecallPlanetCard(
                topics = topics,
                memories = visibleMemories,
                activeTopicId = activeTopicId,
                queueOffset = queueOffset,
                queueProgress = queueProgress.value,
                visibleMemoryLabels = state.presentation.visibleMemoryLabels,
                cardHeightDp = cardHeightDp,
                reducedMotion = reducedMotion,
                motionElapsedMillis = motionElapsedMillis,
                starfieldQuality = starfieldQuality,
                planetContent = planetContent,
                topicInsight = topicInsight,
                controls = {
                    RecallControls(
                        presentation = state.presentation,
                        knowledgeBases = knowledgeBases,
                        knowledgeBasesLoading = knowledgeBasesLoading,
                        knowledgeBaseListMessage = knowledgeBaseListMessage,
                        onRefreshKnowledgeBases = onRefreshKnowledgeBases,
                        onKnowledgeBaseSelected = onKnowledgeBaseSelected,
                        onPeriod = onPeriod,
                        onCustomRange = onCustomRange,
                        customRangeAvailable = customRangeAvailable,
                        filterOverlay = filterOverlay,
                        onFilterOverlayEvent = onFilterOverlayEvent,
                    )
                },
                onTopic = onTopicSelected,
                onInteraction = onInteraction,
                onEmptyRetry = onRefresh,
            )
        }
    }
}

@Composable
private fun RecallSuppressedEntry(
    items: List<RecallSuppressedItem>,
    hasMore: Boolean,
    onRestore: (RecallSuppressedItem) -> Unit,
    onShowAll: () -> Unit,
) {
    val palette = recallPalette()
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = palette.surface.copy(if (palette.dark) .9f else .7f),
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, palette.line),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                "不再浮现的记忆 · 本页 ${items.size} 条",
                color = palette.muted,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
            )
            items.take(5).forEach { item -> RecallSuppressedRow(item, onRestore) }
            if (items.size > 5 || hasMore) {
                TextButton(onClick = onShowAll) { Text("查看全部") }
            }
        }
    }
}

@Composable
private fun RecallSuppressedRow(
    item: RecallSuppressedItem,
    onRestore: (RecallSuppressedItem) -> Unit,
) {
    val palette = recallPalette()
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            item.title,
            Modifier.weight(1f),
            color = palette.ink,
            fontSize = 12.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = { onRestore(item) }) { Text("恢复") }
    }
}

@Composable
private fun RecallUnclassifiedEntry(
    count: Int,
    memories: List<MemoryPlanetMemory>,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
) {
    val palette = recallPalette()
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = palette.surface.copy(if (palette.dark) .9f else .7f),
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, palette.line),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("待归类 · $count", color = palette.muted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
            memories.take(3).forEach { memory ->
                Text(
                    memory.title,
                    Modifier.fillMaxWidth().clickable { onOpenOriginal(RecallOriginalTarget(memory.clipId)) }.padding(vertical = 4.dp),
                    color = palette.ink,
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun RecallHeader(
    onOpenDisplaySettings: () -> Unit,
    hasSuppressed: Boolean,
    onOpenSuppressed: () -> Unit,
) {
    val palette = recallPalette()
    var menuOpen by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().height(48.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "记忆星球",
            Modifier.weight(1f),
            color = palette.ink,
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Black,
        )
        IconButton(
            onClick = { menuOpen = true },
            modifier = Modifier.size(48.dp).semantics { contentDescription = "更多记忆星球选项" },
        ) {
            Icon(Icons.Rounded.MoreVert, null, tint = palette.ink)
        }
        DropdownMenu(menuOpen, { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text("显示设置") },
                onClick = { menuOpen = false; onOpenDisplaySettings() },
            )
            if (hasSuppressed) {
                DropdownMenuItem(
                    text = { Text("不再浮现的记忆") },
                    onClick = { menuOpen = false; onOpenSuppressed() },
                )
            }
        }
    }
}

@Composable
private fun RecallPlanetCard(
    topics: List<RecallDomainTopic>,
    memories: List<RecallMemoryPresentation>,
    activeTopicId: String,
    queueOffset: Int,
    queueProgress: Float,
    visibleMemoryLabels: Int,
    cardHeightDp: Float? = null,
    reducedMotion: Boolean,
    motionElapsedMillis: Long,
    starfieldQuality: MemoryPlanetQuality,
    planetContent: MemoryPlanetContentState,
    topicInsight: RecallTopicInsight?,
    controls: (@Composable () -> Unit)? = null,
    onTopic: (String) -> Unit,
    onInteraction: () -> Unit,
    onEmptyRetry: () -> Unit,
) {
    val palette = recallPalette()
    val populatedPlanet = topics.isNotEmpty() && planetContent == MemoryPlanetContentState.NORMAL
    val resolvedCardHeightDp = cardHeightDp ?: (
        MemoryPlanetVNextLayoutPolicy.GRAPH_HEIGHT_DP +
            MemoryPlanetVNextLayoutPolicy.DIVIDER_HEIGHT_DP +
            MemoryPlanetVNextLayoutPolicy.INSIGHT_HEIGHT_DP
        )
    val graphHeightDp = MemoryPlanetVNextLayoutPolicy.graphHeightForCard(
        cardHeightDp = resolvedCardHeightDp,
        hasControls = controls != null,
    )
    val orbitPhase = if (reducedMotion) 0f else ((motionElapsedMillis % RecallOrbitPolicy.CYCLE_MILLIS).toFloat() / RecallOrbitPolicy.CYCLE_MILLIS) * 360f
    val satellitePhase = if (reducedMotion) 0f else ((motionElapsedMillis % RecallSatellitePolicy.CYCLE_MILLIS).toFloat() / RecallSatellitePolicy.CYCLE_MILLIS) * 360f
    val planetBackground = if (palette.dark) {
        Brush.linearGradient(listOf(ColorTokens.DarkPlumSurface, ColorTokens.DarkPlumRaised, Color(0xFF3A2A45)))
    } else {
        Brush.linearGradient(listOf(Color(0xFFFEFDFF), Color(0xFFF7F3FF), Color(0xFFECE5FF)))
    }
    val cardModifier = Modifier
        .fillMaxWidth()
        .height(resolvedCardHeightDp.dp)
        .shadow(3.dp, RoundedCornerShape(20.dp), clip = false)
    Surface(
        modifier = cardModifier,
        color = Color.Transparent,
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, if (palette.dark) palette.line else ColorTokens.FlashBorder),
    ) {
        Column(Modifier.fillMaxSize().background(planetBackground)) {
            if (controls != null) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(MemoryPlanetVNextLayoutPolicy.CONTROL_HEIGHT_DP.dp)
                        .padding(horizontal = 12.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    controls()
                }
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(MemoryPlanetVNextLayoutPolicy.CONTROL_DIVIDER_HEIGHT_DP.dp)
                        .background(palette.line.copy(alpha = .32f)),
                )
            }
            if (populatedPlanet) {
                Column(Modifier.fillMaxWidth()) {
                    Box(
                        Modifier.fillMaxWidth().height(graphHeightDp.dp),
                    ) {
                        MemoryPlanetStarfield(
                            elapsedMillis = motionElapsedMillis,
                            dark = palette.dark,
                            quality = starfieldQuality,
                            content = planetContent,
                            reducedMotion = reducedMotion,
                            modifier = Modifier.matchParentSize(),
                        )
                        RecallPlanetGraph(
                            topics = topics,
                            memories = memories,
                            activeTopicId = activeTopicId,
                            graphHeightDp = graphHeightDp,
                            visibleMemoryLabels = visibleMemoryLabels,
                            queueOffset = queueOffset,
                            queueProgress = queueProgress,
                            reducedMotion = reducedMotion,
                            orbitPhase = orbitPhase,
                            satellitePhase = satellitePhase,
                            onTopic = onTopic,
                            onInteraction = onInteraction,
                        )
                    }
                    Box(
                        Modifier.fillMaxWidth().height(MemoryPlanetVNextLayoutPolicy.DIVIDER_HEIGHT_DP.dp).background(palette.soft),
                    )
                    RecallTopicInsightContent(
                        insight = topicInsight,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(MemoryPlanetVNextLayoutPolicy.INSIGHT_HEIGHT_DP.dp)
                            .background(palette.surface.copy(if (palette.dark) .96f else .9f)),
                    )
                }
            } else {
                Box(Modifier.fillMaxWidth().weight(1f)) {
                    when (planetContent) {
                        MemoryPlanetContentState.LOADING -> RecallPlanetStaticState(
                            content = MemoryPlanetContentState.LOADING,
                            quality = starfieldQuality,
                            reducedMotion = reducedMotion,
                            elapsedMillis = motionElapsedMillis,
                            modifier = Modifier.fillMaxSize(),
                        )
                        MemoryPlanetContentState.API_UNAVAILABLE -> RecallPlanetUnavailableContent(
                            retry = onEmptyRetry,
                            quality = starfieldQuality,
                            reducedMotion = reducedMotion,
                            elapsedMillis = motionElapsedMillis,
                        )
                        else -> RecallPlanetEmptyContent(
                            retry = onEmptyRetry,
                            quality = starfieldQuality,
                            reducedMotion = reducedMotion,
                            elapsedMillis = motionElapsedMillis,
                            modifier = Modifier.matchParentSize(),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecallTopicInsightContent(
    insight: RecallTopicInsight?,
    modifier: Modifier = Modifier,
) {
    val palette = recallPalette()
    if (insight == null) {
        Box(modifier, contentAlignment = Alignment.Center) {
            Text("还没有可浮现的主题", color = palette.muted, fontSize = 13.sp)
        }
        return
    }

    val accent = topicAccent(insight.colorSlot)
    Column(
        modifier = modifier.padding(horizontal = 20.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(7.dp),
    ) {
        Text("主题洞察", color = palette.muted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(14.dp).background(accent, CircleShape))
            Spacer(Modifier.width(10.dp))
            Text(
                insight.label,
                color = palette.ink,
                fontSize = 19.sp,
                fontWeight = FontWeight.Black,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Text(
                "${insight.periodLabel}入库 · ${insight.inWindowCount} 条",
                color = palette.accentText,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
            )
        }
        Text(
            insight.summary,
            color = palette.muted,
            fontSize = 13.sp,
            lineHeight = 21.sp,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Box(Modifier.fillMaxWidth().height(1.dp).background(palette.line.copy(alpha = .55f)))
        RecallInsightStatRow(Icons.Rounded.AutoAwesome, "已回溯", "${insight.recalledCount} 条")
        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text("近期关键词", color = palette.ink, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(7.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                recallTopicKeywordDisplay(insight.keywords).forEach { keyword ->
                    Surface(shape = RoundedCornerShape(10.dp), color = palette.soft) {
                        Text(
                            keyword,
                            Modifier.padding(horizontal = 9.dp, vertical = 5.dp),
                            color = palette.accentText,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun RecallInsightStatRow(
    icon: ImageVector,
    label: String,
    value: String,
) {
    val palette = recallPalette()
    Row(
        Modifier.fillMaxWidth().height(24.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, Modifier.size(18.dp), tint = palette.muted)
        Spacer(Modifier.width(10.dp))
        Text(label, Modifier.weight(1f), color = palette.ink, fontSize = 12.sp)
        Text(value, color = palette.accentText, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    }
}

private data class TopicOrbitSlot(val angleDegrees: Float, val color: Color, val icon: Int)

private val TopicOrbitSlots = listOf(
    TopicOrbitSlot(234f, Color(0xFFE6F8EF), 0),
    TopicOrbitSlot(306f, Color(0xFFE9F5FD), 1),
    TopicOrbitSlot(162f, Color(0xFFFFF3D8), 2),
    TopicOrbitSlot(18f, Color(0xFFFFEEDB), 3),
    TopicOrbitSlot(90f, Color(0xFFF0EBFF), 4),
)

@Composable
private fun RecallPlanetGraph(
    topics: List<RecallDomainTopic>,
    memories: List<RecallMemoryPresentation>,
    activeTopicId: String,
    graphHeightDp: Float,
    visibleMemoryLabels: Int,
    queueOffset: Int,
    queueProgress: Float,
    reducedMotion: Boolean,
    orbitPhase: Float,
    satellitePhase: Float,
    onTopic: (String) -> Unit,
    onInteraction: () -> Unit,
) {
    val graphHeight = graphHeightDp.dp
    BoxWithConstraints(Modifier.fillMaxWidth().height(graphHeight)) {
        val width = maxWidth
        val height = graphHeight
        val graphScale = (graphHeightDp / MemoryPlanetVNextLayoutPolicy.GRAPH_HEIGHT_DP).coerceIn(1f, 1.5f)
        val orbitCenterY = graphHeightDp * .49f
        val orbitWidth = (width - 48.dp).coerceAtLeast(260.dp)
        val orbitHeight = (
            (208f * graphScale).coerceAtMost(graphHeightDp * .78f)
        ).dp
        val innerOrbitHeight = (
            (142f * graphScale).coerceAtMost(orbitHeight.value * .74f)
        ).dp
        val satelliteRadiusY = RecallSatellitePolicy.RADIUS_Y * graphScale
        Canvas(Modifier.fillMaxSize()) {
            val center = androidx.compose.ui.geometry.Offset(size.width * .5f, orbitCenterY.dp.toPx())
            val orbitStroke = 1.5.dp.toPx()
            val orbitSizes = listOf(
                androidx.compose.ui.geometry.Size(
                    width = orbitWidth.toPx(),
                    height = orbitHeight.toPx(),
                ) to .48f,
                androidx.compose.ui.geometry.Size(
                    width = (orbitWidth - 74.dp).coerceAtLeast(0.dp).toPx(),
                    height = innerOrbitHeight.toPx(),
                ) to .36f,
            )
            rotate(degrees = 8f, pivot = center) {
                orbitSizes.forEach { (orbitSize, alpha) ->
                    drawOval(
                        color = RecallPurple.copy(alpha = alpha),
                        topLeft = androidx.compose.ui.geometry.Offset(
                            x = center.x - orbitSize.width / 2f,
                            y = center.y - orbitSize.height / 2f,
                        ),
                        size = orbitSize,
                        style = Stroke(orbitStroke),
                    )
                }
            }
        }
        MemoryCore(Modifier.align(Alignment.TopStart).offset(width * .5f - 20.dp, (orbitCenterY - 20f).dp))
        topics.take(5).forEachIndexed { index, topic ->
            val slot = TopicOrbitSlots[index]
            RecallTopicPlanet(
                topic = topic,
                active = topic.id == activeTopicId,
                slot = slot,
                parentWidth = width,
                orbitWidth = orbitWidth,
                orbitHeight = orbitHeight,
                graphHeight = graphHeight,
                orbitCenterY = orbitCenterY,
                orbitPhase = orbitPhase,
                reducedMotion = reducedMotion,
                onTopic = onTopic,
                onInteraction = onInteraction,
            )
        }
        AnimatedContent(
            targetState = activeTopicId,
            modifier = Modifier.fillMaxSize(),
            transitionSpec = {
                fadeIn(
                    animationSpec = tween(if (reducedMotion) 0 else 250, easing = LinearOutSlowInEasing),
                ) togetherWith fadeOut(
                    animationSpec = tween(if (reducedMotion) 0 else 200, easing = FastOutLinearInEasing),
                )
            },
            label = "recall-memory-satellites",
        ) { topicId ->
            Box(Modifier.fillMaxSize()) {
                val labelCount = visibleMemoryLabels.coerceIn(1, 5)
                val currentMemories = recallQueueWindow(memories, queueOffset, labelCount)
                val nextMemories = recallQueueWindow(memories, queueOffset + 1, labelCount)
                val transitionProgress = if (memories.size > labelCount) queueProgress.coerceIn(0f, 1f) else 0f
                val topicIndex = topics.indexOfFirst { it.id == topicId }
                val activeTopicPoint = if (topicIndex >= 0) {
                    recallOrbitPoint(
                        centerX = width.value / 2f,
                        centerY = orbitCenterY,
                        radiusX = orbitWidth.value / 2f,
                        radiusY = orbitHeight.value / 2f,
                        angleDegrees = TopicOrbitSlots[topicIndex].angleDegrees + orbitPhase,
                    )
                } else {
                    RecallOrbitPoint(width.value / 2f, orbitCenterY)
                }
                currentMemories.forEachIndexed { index, memory ->
                    val fromSlot = index.toFloat()
                    val toSlot = (index - 1).coerceAtLeast(0).toFloat()
                    val animatedSlot = if (index == 0) fromSlot else fromSlot + (toSlot - fromSlot) * transitionProgress
                    val satellitePoint = recallOrbitPoint(
                        centerX = activeTopicPoint.x,
                        centerY = activeTopicPoint.y,
                        radiusX = RecallSatellitePolicy.RADIUS_X,
                        radiusY = satelliteRadiusY,
                        angleDegrees = satellitePhase + animatedSlot * (360f / currentMemories.size.coerceAtLeast(1)),
                        tiltDegrees = 0f,
                    )
                    val x = (satellitePoint.x - 34f).coerceIn(0f, (width.value - 68f).coerceAtLeast(0f))
                    val y = (satellitePoint.y - 13f).coerceIn(0f, (height.value - 26f).coerceAtLeast(0f))
                    MemorySatellite(
                        label = memory.title,
                        sourceLabel = memory.sourceLabel,
                        modifier = Modifier
                            .offset(x.dp, y.dp)
                            .graphicsLayer {
                                alpha = if (index == 0) 1f - transitionProgress else 1f
                                val scale = if (index == 0) 1f - transitionProgress * .14f else 1f
                                scaleX = scale
                                scaleY = scale
                            },
                    )
                }
                if (transitionProgress > 0f && nextMemories.isNotEmpty()) {
                    val incoming = nextMemories.last()
                    val slot = nextMemories.lastIndex.toFloat()
                    val satellitePoint = recallOrbitPoint(
                        centerX = activeTopicPoint.x,
                        centerY = activeTopicPoint.y,
                        radiusX = RecallSatellitePolicy.RADIUS_X,
                        radiusY = satelliteRadiusY,
                        angleDegrees = satellitePhase + slot * (360f / nextMemories.size.coerceAtLeast(1)),
                        tiltDegrees = 0f,
                    )
                    val x = (satellitePoint.x - 34f).coerceIn(0f, (width.value - 68f).coerceAtLeast(0f))
                    val y = (satellitePoint.y - 13f).coerceIn(0f, (height.value - 26f).coerceAtLeast(0f))
                    MemorySatellite(
                        label = incoming.title,
                        sourceLabel = incoming.sourceLabel,
                        modifier = Modifier
                            .offset(x.dp, y.dp)
                            .graphicsLayer {
                                alpha = transitionProgress
                                val scale = .86f + transitionProgress * .14f
                                scaleX = scale
                                scaleY = scale
                            },
                    )
                }
            }
        }
    }
}

@Composable
private fun MemoryCore(modifier: Modifier = Modifier) {
    Box(modifier.size(40.dp), contentAlignment = Alignment.Center) {
        Box(Modifier.size(78.dp).border(1.dp, RecallPurple.copy(.12f), CircleShape))
        Box(Modifier.size(58.dp).border(1.dp, RecallPurple.copy(.18f), CircleShape))
        Surface(Modifier.size(40.dp), CircleShape, color = RecallPurple) {
            Box(contentAlignment = Alignment.Center) { Text("✦", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Black) }
        }
    }
}

@Composable
private fun RecallTopicPlanet(
    topic: RecallDomainTopic,
    active: Boolean,
    slot: TopicOrbitSlot,
    parentWidth: Dp,
    orbitWidth: Dp,
    orbitHeight: Dp,
    graphHeight: Dp,
    orbitCenterY: Float,
    orbitPhase: Float,
    reducedMotion: Boolean,
    onTopic: (String) -> Unit,
    onInteraction: () -> Unit,
) {
    val palette = recallPalette()
    val targetSize = if (active) 80.dp else 66.dp
    val size by animateDpAsState(targetSize, tween(if (reducedMotion) 0 else 250, easing = FastOutSlowInEasing), label = "topic-size")
    val interactionSource = remember(topic.id) { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    var dragX by remember(topic.id) { mutableFloatStateOf(0f) }
    var dragY by remember(topic.id) { mutableFloatStateOf(0f) }
    val point = recallOrbitPoint(
        centerX = parentWidth.value / 2f,
        centerY = orbitCenterY,
        radiusX = orbitWidth.value / 2f,
        radiusY = orbitHeight.value / 2f,
        angleDegrees = slot.angleDegrees + orbitPhase,
    )
    val safeMargin = 8.dp
    val x = (point.x.dp - size / 2 + dragX.dp).coerceIn(
        safeMargin,
        (parentWidth - size - safeMargin).coerceAtLeast(safeMargin),
    )
    val y = (point.y.dp - size / 2 + dragY.dp).coerceIn(
        safeMargin,
        (graphHeight - size - safeMargin).coerceAtLeast(safeMargin),
    )
    val topicLabel = topic.shortLabel.ifBlank { topic.label }.take(6)
    val topicLabelSize = when {
        active && topicLabel.length <= 4 -> 14.sp
        active -> 11.sp
        topicLabel.length > 4 -> 10.sp
        else -> 12.sp
    }
    Surface(
        modifier = Modifier
            .offset(x, y)
            .size(size)
            .clip(CircleShape)
            .pointerInput(topic.id) {
                detectDragGestures(
                    onDragStart = { onInteraction() },
                    onDragEnd = { dragX = 0f; dragY = 0f },
                ) { change, amount ->
                    change.consume()
                    dragX += amount.x / density
                    dragY += amount.y / density
                }
            }
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                role = Role.Button,
            ) { onInteraction(); onTopic(topic.id) }
            .semantics { contentDescription = "主题 ${topic.label}，${topic.clipCount} 条记忆" },
        shape = CircleShape,
        color = if (active) palette.soft else if (palette.dark) slot.color.copy(alpha = .22f) else slot.color,
        border = BorderStroke(
            if (active) 2.dp else 1.dp,
            when {
                active -> RecallPurple
                pressed -> palette.muted.copy(alpha = .62f)
                palette.dark -> palette.line
                else -> slot.color.copy(alpha = .8f)
            },
        ),
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(topicIcon(slot.icon), null, Modifier.size(if (active) 18.dp else 16.dp), tint = if (active) RecallBlue else topicAccent(slot.icon))
            Text(topicLabel, color = palette.ink, fontSize = topicLabelSize, fontWeight = FontWeight.Bold, maxLines = 1)
            Text("${topic.clipCount} 条", color = palette.muted, fontSize = 9.sp)
        }
    }
}

private fun topicIcon(slot: Int) = when (slot) {
    0 -> Icons.Rounded.School
    1 -> Icons.Rounded.Description
    2 -> Icons.Rounded.Description
    3 -> Icons.Rounded.Lightbulb
    else -> Icons.Rounded.Workspaces
}

private fun topicAccent(slot: Int) = when (slot) { 0 -> RecallGreen; 1 -> RecallBlue; 2 -> Color(0xFFF4B000); 3 -> RecallOrange; else -> RecallPurple }

@Composable
private fun MemorySatellite(label: String, sourceLabel: String, modifier: Modifier = Modifier) {
    val palette = recallPalette()
    Surface(modifier.width(68.dp).height(26.dp), RoundedCornerShape(8.dp), color = palette.surface.copy(.94f), border = BorderStroke(1.dp, palette.line)) {
        Row(Modifier.padding(horizontal = 5.dp), verticalAlignment = Alignment.CenterVertically) {
            PerClipSourceIcon(sourceLabel, Modifier.size(16.dp), compact = true)
            Spacer(Modifier.width(4.dp))
            Text(recallCompactSatelliteLabel(label), color = palette.ink, fontSize = 8.sp, maxLines = 1, overflow = TextOverflow.Clip)
        }
    }
}

internal fun recallCompactSatelliteLabel(value: String): String {
    val normalized = value.trim().ifBlank { "记忆" }
    fun width(text: String): Float = text.sumOf { if (it.code <= 0x7F) 0.5 else 1.0 }.toFloat()
    if (width(normalized) <= 4f) return normalized
    normalized.substringBefore(' ').takeIf { it.isNotBlank() && width(it) in 2f..4f }?.let { return it }
    var used = 0f
    return buildString {
        for (char in normalized) {
            val next = if (char.code <= 0x7F) .5f else 1f
            if (used + next > 4f) break
            append(char)
            used += next
        }
    }.trim().ifBlank { "记忆" }
}

@Composable
private fun RecallControls(
    presentation: RecallPresentationState,
    knowledgeBases: List<KnowledgeBaseSummary>,
    knowledgeBasesLoading: Boolean,
    knowledgeBaseListMessage: String,
    onRefreshKnowledgeBases: () -> Unit,
    onKnowledgeBaseSelected: (String) -> Unit,
    onPeriod: (RecallPeriod) -> Unit,
    onCustomRange: (String, String, String) -> Unit,
    customRangeAvailable: Boolean,
    filterOverlay: RecallFilterOverlay,
    onFilterOverlayEvent: (RecallFilterOverlayEvent) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RecallKnowledgeBaseControl(
            knowledgeBaseId = presentation.knowledgeBaseId,
            knowledgeBases = knowledgeBases,
            knowledgeBasesLoading = knowledgeBasesLoading,
            knowledgeBaseListMessage = knowledgeBaseListMessage,
            onRefreshKnowledgeBases = onRefreshKnowledgeBases,
            modifier = Modifier.weight(1f).padding(end = 8.dp),
            onKnowledgeBaseSelected = onKnowledgeBaseSelected,
            filterOverlay = filterOverlay,
            onFilterOverlayEvent = onFilterOverlayEvent,
        )
        RecallPeriodControl(
            period = presentation.period,
            customStartDate = presentation.customStartDate,
            customEndDate = presentation.customEndDate,
            modifier = Modifier.width(108.dp),
            onPeriod = onPeriod,
            onCustomRange = onCustomRange,
            customRangeAvailable = customRangeAvailable,
            filterOverlay = filterOverlay,
            onFilterOverlayEvent = onFilterOverlayEvent,
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecallPeriodControl(
    period: RecallPeriod,
    customStartDate: String,
    customEndDate: String,
    modifier: Modifier,
    onPeriod: (RecallPeriod) -> Unit,
    onCustomRange: (String, String, String) -> Unit,
    customRangeAvailable: Boolean,
    filterOverlay: RecallFilterOverlay,
    onFilterOverlayEvent: (RecallFilterOverlayEvent) -> Unit,
) {
    val open = filterOverlay == RecallFilterOverlay.PERIOD_MENU
    val datePickerOpen = filterOverlay == RecallFilterOverlay.DATE_PICKER
    Box(modifier) {
        val value = recallPeriodLabel(period, customStartDate, customEndDate)
        RecallControl(
            label = value,
            description = "周期筛选：$value",
            modifier = Modifier.fillMaxWidth(),
            active = true,
            contentAlignment = Alignment.CenterEnd,
            compactLabel = period == RecallPeriod.CUSTOM,
            onClick = {
                onFilterOverlayEvent(RecallFilterOverlayEvent.OPEN_PERIOD_MENU)
            },
        )
        DropdownMenu(open, { onFilterOverlayEvent(RecallFilterOverlayEvent.DISMISS) }) {
            DropdownMenuItem({ Text("本周") }, onClick = {
                onFilterOverlayEvent(RecallFilterOverlayEvent.SELECT)
                onPeriod(RecallPeriod.WEEKLY)
            })
            DropdownMenuItem({ Text("本月") }, onClick = {
                onFilterOverlayEvent(RecallFilterOverlayEvent.SELECT)
                onPeriod(RecallPeriod.MONTHLY)
            })
            DropdownMenuItem(
                { Text(if (customRangeAvailable) "自定义日期" else "自定义日期（当前服务端不支持）") },
                enabled = customRangeAvailable,
                onClick = { onFilterOverlayEvent(RecallFilterOverlayEvent.OPEN_DATE_PICKER) },
            )
        }
    }
    if (datePickerOpen) {
        val initialStart = customStartDate.toPickerMillis()
        val initialEnd = customEndDate.toPickerMillis()
        val pickerState = rememberDateRangePickerState(
            initialSelectedStartDateMillis = initialStart,
            initialSelectedEndDateMillis = initialEnd,
        )
        DatePickerDialog(
            onDismissRequest = { onFilterOverlayEvent(RecallFilterOverlayEvent.DISMISS) },
            confirmButton = {
                TextButton(
                    enabled = pickerState.selectedStartDateMillis != null &&
                        pickerState.selectedEndDateMillis != null,
                    onClick = {
                        val start = pickerState.selectedStartDateMillis?.toPickerDate()
                        val end = pickerState.selectedEndDateMillis?.toPickerDate()
                        if (start != null && end != null) {
                            onFilterOverlayEvent(RecallFilterOverlayEvent.CONFIRM)
                            onCustomRange(start, end, ZoneId.systemDefault().id)
                        }
                    },
                ) { Text("确定") }
            },
            dismissButton = {
                TextButton(onClick = { onFilterOverlayEvent(RecallFilterOverlayEvent.CANCEL) }) { Text("取消") }
            },
        ) {
            DateRangePicker(
                state = pickerState,
                title = { Text("选择记忆星球日期范围", Modifier.padding(16.dp)) },
                showModeToggle = false,
            )
        }
    }
}

internal fun recallPeriodLabel(period: RecallPeriod, customStartDate: String, customEndDate: String): String = when (period) {
    RecallPeriod.WEEKLY -> "本周"
    RecallPeriod.MONTHLY -> "本月"
    RecallPeriod.CUSTOM -> runCatching {
        val start = LocalDate.parse(customStartDate)
        val end = LocalDate.parse(customEndDate)
        if (start.year == end.year && start.month == end.month) {
            "${start.monthValue}/${start.dayOfMonth}–${end.dayOfMonth}"
        } else {
            "${start.monthValue}/${start.dayOfMonth}–${end.monthValue}/${end.dayOfMonth}"
        }
    }.getOrDefault("自定义")
}

private fun String.toPickerMillis(): Long? = runCatching {
    LocalDate.parse(this).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
}.getOrNull()

private fun Long.toPickerDate(): String =
    Instant.ofEpochMilli(this).atZone(ZoneOffset.UTC).toLocalDate().toString()

@Composable
private fun RecallKnowledgeBaseControl(
    knowledgeBaseId: String,
    knowledgeBases: List<KnowledgeBaseSummary>,
    knowledgeBasesLoading: Boolean,
    knowledgeBaseListMessage: String,
    onRefreshKnowledgeBases: () -> Unit,
    modifier: Modifier,
    onKnowledgeBaseSelected: (String) -> Unit,
    filterOverlay: RecallFilterOverlay,
    onFilterOverlayEvent: (RecallFilterOverlayEvent) -> Unit,
) {
    val open = filterOverlay == RecallFilterOverlay.KNOWLEDGE_BASE_MENU
    val selected = knowledgeBases.firstOrNull { it.id == knowledgeBaseId }
        ?: knowledgeBases.firstOrNull { it.isDefault }
        ?: knowledgeBases.firstOrNull()
    val value = selected?.displayName ?: "选择知识库"
    Box(modifier) {
        RecallControl(
            label = value,
            description = "知识库筛选：$value",
            modifier = Modifier.fillMaxWidth(),
            active = selected != null,
            contentAlignment = Alignment.CenterStart,
            onClick = {
                onFilterOverlayEvent(RecallFilterOverlayEvent.OPEN_KNOWLEDGE_BASE_MENU)
            },
        )
        DropdownMenu(open, { onFilterOverlayEvent(RecallFilterOverlayEvent.DISMISS) }) {
            when {
                knowledgeBasesLoading -> DropdownMenuItem(
                    text = { Text("正在读取知识库…") },
                    enabled = false,
                    onClick = {},
                )
                knowledgeBases.isEmpty() -> {
                    DropdownMenuItem(
                        text = { Text(knowledgeBaseListMessage.ifBlank { "暂无可用知识库" }) },
                        enabled = false,
                        onClick = {},
                    )
                    DropdownMenuItem(
                        text = { Text("刷新列表") },
                        onClick = {
                            onFilterOverlayEvent(RecallFilterOverlayEvent.SELECT)
                            onRefreshKnowledgeBases()
                        },
                    )
                }
            }
            knowledgeBases.forEach { knowledgeBase ->
                DropdownMenuItem(
                    text = {
                        Text(
                            if (knowledgeBase.id == knowledgeBaseId) {
                                "${knowledgeBase.displayName} · 当前"
                            } else {
                                knowledgeBase.displayName
                            },
                        )
                    },
                    onClick = {
                        onFilterOverlayEvent(RecallFilterOverlayEvent.SELECT)
                        onKnowledgeBaseSelected(knowledgeBase.id)
                    },
                )
            }
        }
    }
}

@Composable
private fun RecallControl(
    label: String,
    description: String,
    modifier: Modifier,
    active: Boolean = false,
    compactLabel: Boolean = false,
    contentAlignment: Alignment = Alignment.Center,
    onClick: () -> Unit,
) {
    val palette = recallPalette()
    val interactionSource = remember { MutableInteractionSource() }
    Box(
        modifier = modifier
            .height(40.dp)
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                role = Role.Button,
                onClick = onClick,
            )
            .semantics { contentDescription = description },
        contentAlignment = contentAlignment,
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                label,
                color = if (active) palette.accentText else palette.ink,
                fontSize = if (compactLabel) 10.sp else 12.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Icon(
                Icons.Rounded.KeyboardArrowDown,
                contentDescription = null,
                modifier = Modifier.size(14.dp),
                tint = if (active) palette.accentText.copy(alpha = .88f) else palette.muted,
            )
        }
    }
}

@Composable
private fun RecallFifoMemoryList(
    memories: List<RecallMemoryPresentation>,
    queueOffset: Int,
    progress: Float,
    animateQueue: Boolean,
    browsingAll: Boolean,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
    onSuppress: (RecallMemoryPresentation) -> Unit,
    onMenuVisibilityChanged: (Boolean) -> Unit,
) {
    val fontScale = LocalDensity.current.fontScale
    val window = MemoryPlanetListWindowPolicy.calculate(fontScale)
    val cardHeight = window.cardHeightDp.dp
    val cardGap = MemoryPlanetListWindowPolicy.CARD_GAP_DP.dp
    val cardStep = cardHeight + cardGap
    val current = recallQueueWindow(memories, queueOffset, RecallQueuePolicy.VISIBLE_CARD_COUNT)
    if (browsingAll) {
        val browseQueue = recallQueueWindow(memories, queueOffset, memories.size)
        Column(verticalArrangement = Arrangement.spacedBy(cardGap)) {
            RecallBrowseStatus()
            browseQueue.forEach { memory ->
                key(memory.clipId) {
                    RecallMemoryCard(
                        memory,
                        onOpenOriginal,
                        onSuppress,
                        onMenuVisibilityChanged,
                        Modifier.height(cardHeight),
                    )
                }
            }
        }
        return
    }

    val next = recallQueueWindow(memories, queueOffset + 1, RecallQueuePolicy.VISIBLE_CARD_COUNT)
    val transition = if (animateQueue) progress.coerceIn(0f, 1f) else 0f
    val visibleHeight = if (current.size <= window.fullCardCount) {
        cardHeight * current.size + cardGap * (current.size - 1).coerceAtLeast(0)
    } else {
        window.windowHeightDp.dp
    }
    Box(
        Modifier
            .fillMaxWidth()
            .height(visibleHeight)
            .clipToBounds(),
    ) {
        current.forEachIndexed { index, memory ->
            key("current:${memory.clipId}") {
                RecallMemoryCard(
                    memory = memory,
                    onOpenOriginal = onOpenOriginal,
                    onSuppress = onSuppress,
                    onMenuVisibilityChanged = onMenuVisibilityChanged,
                    modifier = Modifier
                        .offset(y = cardStep * index)
                        .height(cardHeight)
                        .graphicsLayer {
                            if (index == 0) {
                                alpha = 1f - transition
                                scaleY = 1f - transition * .16f
                                transformOrigin = TransformOrigin.Center
                            } else {
                                translationY = -cardStep.toPx() * transition
                            }
                        },
                )
            }
        }
        if (animateQueue && transition > 0f && next.isNotEmpty()) {
            val incoming = next.last()
            key("incoming:${incoming.clipId}") {
                RecallMemoryCard(
                    memory = incoming,
                    onOpenOriginal = onOpenOriginal,
                    onSuppress = onSuppress,
                    onMenuVisibilityChanged = onMenuVisibilityChanged,
                    modifier = Modifier
                        .offset(y = cardStep * RecallQueuePolicy.VISIBLE_CARD_COUNT)
                        .height(cardHeight)
                        .graphicsLayer {
                            translationY = -cardStep.toPx() * transition
                            alpha = transition
                            val scale = .92f + transition * .08f
                            scaleX = scale
                            scaleY = scale
                            transformOrigin = TransformOrigin.Center
                        },
                )
            }
        }
    }
}

@Composable
private fun RecallBrowseStatus() {
    val palette = recallPalette()
    Surface(
        modifier = Modifier.fillMaxWidth().height(34.dp),
        shape = RoundedCornerShape(12.dp),
        color = palette.surface.copy(if (palette.dark) .94f else .72f),
        border = BorderStroke(1.dp, RecallPurple.copy(alpha = .45f)),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                "浏览全部 · 返回顶部后继续",
                color = palette.accentText,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

@Composable
private fun RecallMemoryCard(
    memory: RecallMemoryPresentation,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
    onSuppress: (RecallMemoryPresentation) -> Unit,
    onMenuVisibilityChanged: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val palette = recallPalette()
    var menu by remember { mutableStateOf(false) }
    fun setMenuVisible(visible: Boolean) {
        if (menu == visible) return
        menu = visible
        onMenuVisibilityChanged(visible)
    }
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .clickable(role = Role.Button) {
                onOpenOriginal(RecallOriginalTarget(memory.clipId, memory.clientRequestId))
            }
            .semantics { contentDescription = "打开记忆：${memory.title}" },
        color = palette.surface.copy(if (palette.dark) .96f else .76f),
        shape = RoundedCornerShape(18.dp),
        border = BorderStroke(1.dp, palette.line),
    ) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.Top) {
            PerClipSourceIcon(memory.sourceLabel, Modifier.size(42.dp))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(memory.title, color = palette.ink, fontSize = 14.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(memory.summary, Modifier.padding(top = 3.dp), color = palette.muted, fontSize = 11.sp, lineHeight = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
                    memory.tags.take(3).forEach { tag ->
                        Surface(shape = RoundedCornerShape(9.dp), color = palette.soft) { Text(tag, Modifier.padding(horizontal = 8.dp, vertical = 3.dp), color = palette.accentText, fontSize = 9.sp) }
                    }
                    Spacer(Modifier.weight(1f))
                    Text(recallCardDate(memory.capturedAt), color = palette.muted, fontSize = 9.sp)
                }
            }
            Box {
                IconButton(onClick = { setMenuVisible(true) }, Modifier.size(48.dp)) { Icon(Icons.Rounded.MoreVert, "更多操作", tint = palette.muted) }
                DropdownMenu(menu, { setMenuVisible(false) }) {
                    DropdownMenuItem(
                        text = { Text("查看详情") },
                        leadingIcon = { Icon(Icons.Rounded.Description, null, Modifier.size(18.dp)) },
                        onClick = { setMenuVisible(false); onOpenOriginal(RecallOriginalTarget(memory.clipId, memory.clientRequestId)) },
                    )
                    DropdownMenuItem(
                        text = { Text("不再浮现", color = Color(0xFFD84A64)) },
                        leadingIcon = { Text("⊘", color = Color(0xFFD84A64), fontSize = 17.sp) },
                        onClick = { setMenuVisible(false); onSuppress(memory) },
                    )
                }
            }
        }
    }
}

@Composable
private fun RecallPlanetStaticState(
    content: MemoryPlanetContentState,
    quality: MemoryPlanetQuality,
    reducedMotion: Boolean,
    elapsedMillis: Long,
    modifier: Modifier = Modifier.height(250.dp),
) {
    val p = recallPalette()
    val background = if (p.dark) {
        Brush.linearGradient(listOf(ColorTokens.DarkPlumSurface, ColorTokens.DarkPlumRaised, Color(0xFF3A2A45)))
    } else {
        Brush.linearGradient(listOf(Color(0xFFFEFDFF), Color(0xFFF7F3FF), Color(0xFFECE5FF)))
    }
    Surface(
        modifier.fillMaxWidth(),
        RoundedCornerShape(20.dp),
        color = Color.Transparent,
        border = BorderStroke(1.dp, p.line),
    ) {
        Box(Modifier.fillMaxSize().background(background)) {
            MemoryPlanetStarfield(
                elapsedMillis = elapsedMillis,
                dark = p.dark,
                quality = if (quality == MemoryPlanetQuality.FULL) MemoryPlanetQuality.LITE else quality,
                content = content,
                reducedMotion = reducedMotion,
                modifier = Modifier.matchParentSize(),
            )
            if (content == MemoryPlanetContentState.LOADING) {
                Column(
                    Modifier.align(Alignment.Center).width(190.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(Modifier.size(42.dp).background(p.soft, CircleShape))
                    Box(Modifier.width(160.dp).height(12.dp).background(p.line.copy(alpha = .52f), RoundedCornerShape(8.dp)))
                    Box(Modifier.width(118.dp).height(10.dp).background(p.line.copy(alpha = .34f), RoundedCornerShape(8.dp)))
                }
            }
        }
    }
}

@Composable
private fun RecallPlanetUnavailableContent(
    retry: () -> Unit,
    quality: MemoryPlanetQuality,
    reducedMotion: Boolean,
    elapsedMillis: Long,
) {
    val p = recallPalette()
    Box(Modifier.fillMaxSize()) {
        MemoryPlanetStarfield(
            elapsedMillis = elapsedMillis,
            dark = p.dark,
            quality = if (quality == MemoryPlanetQuality.FULL) MemoryPlanetQuality.LITE else quality,
            content = MemoryPlanetContentState.API_UNAVAILABLE,
            reducedMotion = reducedMotion,
            modifier = Modifier.matchParentSize(),
        )
        Column(
            Modifier.align(Alignment.Center).padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("暂时无法加载记忆星球", color = p.ink, fontWeight = FontWeight.Bold)
            Text("检查连接后可以重新读取。", color = p.muted, fontSize = 12.sp)
            TextButton(onClick = retry) { Text("重新加载", color = p.accentText) }
        }
    }
}

@Composable
private fun RecallHomeLoading() {
    val p = recallPalette()
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(3) {
            Surface(
                Modifier.fillMaxWidth().height(108.dp),
                RoundedCornerShape(18.dp),
                color = p.surface.copy(if (p.dark) .96f else .76f),
                border = BorderStroke(1.dp, p.line),
            ) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.Top) {
                    Box(Modifier.size(40.dp).background(p.soft, RoundedCornerShape(10.dp)))
                    Spacer(Modifier.width(12.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Box(Modifier.width(170.dp).height(12.dp).background(p.line.copy(.5f), RoundedCornerShape(8.dp)))
                        Box(Modifier.fillMaxWidth().height(10.dp).background(p.line.copy(.34f), RoundedCornerShape(8.dp)))
                        Box(Modifier.width(96.dp).height(10.dp).background(p.line.copy(.28f), RoundedCornerShape(8.dp)))
                    }
                }
            }
        }
    }
}

@Composable
private fun RecallHomeError(
    message: String,
    retry: () -> Unit,
    showStarfield: Boolean,
    quality: MemoryPlanetQuality,
    reducedMotion: Boolean,
    elapsedMillis: Long,
) {
    val p = recallPalette()
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (showStarfield) {
            RecallPlanetStaticState(
                content = MemoryPlanetContentState.API_UNAVAILABLE,
                quality = quality,
                reducedMotion = reducedMotion,
                elapsedMillis = elapsedMillis,
            )
        }
        Surface(
            Modifier.fillMaxWidth().height(250.dp),
            RoundedCornerShape(18.dp),
            color = if (p.dark) Color(0xFF2A202A) else Color(0xFFFFF7F7),
            border = BorderStroke(1.dp, Color(0xFFFF8A9A)),
        ) {
            Column(
                Modifier.padding(22.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Box(Modifier.size(44.dp).background(Color(0xFFFFDDE2), CircleShape), contentAlignment = Alignment.Center) {
                    Text("!", color = Color(0xFFE34863), fontWeight = FontWeight.Black)
                }
                Text("暂时无法加载记忆", Modifier.padding(top = 18.dp), color = p.ink, fontWeight = FontWeight.Bold)
                Text(message, Modifier.padding(top = 8.dp), color = p.muted, maxLines = 3)
                Button(retry, Modifier.padding(top = 16.dp).height(48.dp), colors = ButtonDefaults.buttonColors(containerColor = RecallPurple)) { Text("重新加载") }
            }
        }
    }
}

@Composable
private fun RecallHomeEmpty(
    retry: () -> Unit,
    quality: MemoryPlanetQuality,
    reducedMotion: Boolean,
    elapsedMillis: Long,
) {
    val p = recallPalette()
    Surface(
        Modifier.fillMaxWidth().height(510.dp),
        RoundedCornerShape(18.dp),
        color = p.surface.copy(if (p.dark) .94f else .7f),
        border = BorderStroke(1.dp, p.line),
    ) {
        RecallPlanetEmptyContent(
            retry = retry,
            quality = quality,
            reducedMotion = reducedMotion,
            elapsedMillis = elapsedMillis,
            modifier = Modifier.fillMaxSize(),
        )
    }
}

@Composable
private fun RecallPlanetEmptyContent(
    retry: () -> Unit,
    quality: MemoryPlanetQuality,
    reducedMotion: Boolean,
    elapsedMillis: Long,
    modifier: Modifier = Modifier,
) {
    val p = recallPalette()
    Box(modifier) {
        MemoryPlanetStarfield(
            elapsedMillis = elapsedMillis,
            dark = p.dark,
            quality = if (quality == MemoryPlanetQuality.FULL) MemoryPlanetQuality.LITE else quality,
            content = MemoryPlanetContentState.EMPTY,
            reducedMotion = reducedMotion,
            modifier = Modifier.matchParentSize(),
        )
        Column(Modifier.align(Alignment.Center), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.size(44.dp).background(p.soft, CircleShape), contentAlignment = Alignment.Center) {
                Text("✦", color = p.accentText, fontSize = 22.sp)
            }
            Text("还没有可浮现的记忆", Modifier.padding(top = 18.dp), color = p.ink, fontWeight = FontWeight.Bold)
            Text("完成几次闪记后，记忆会在这里围绕主题自然出现。", Modifier.padding(top = 8.dp), color = p.muted, fontSize = 12.sp)
            Text("刷新", Modifier.clickable(onClick = retry).padding(14.dp), color = p.accentText, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable private fun RecallMemoryEmpty() { val p = recallPalette(); Surface(Modifier.fillMaxWidth(), RoundedCornerShape(18.dp), color = p.surface.copy(if (p.dark) .94f else .65f), border = BorderStroke(1.dp, p.line)) { Text("这个范围暂时没有可浮现的记忆", Modifier.padding(18.dp), color = p.muted) } }

internal fun recallCardDate(value: String, zoneId: java.time.ZoneId = java.time.ZoneId.systemDefault()): String {
    val instant = runCatching { java.time.Instant.parse(value) }.getOrNull() ?: return value.take(10)
    val dateTime = instant.atZone(zoneId)
    return "${dateTime.monthValue}月${dateTime.dayOfMonth}日 ${dateTime.toLocalTime().toString().take(5)}"
}

@Composable
internal fun RecallTopicFocusContent(
    state: RecallUiState,
    topicId: String,
    padding: PaddingValues,
    onBack: () -> Unit,
    onTopicSelected: (String) -> Unit,
    onInteraction: () -> Unit,
    onOpenOriginal: (RecallOriginalTarget) -> Unit,
    onSuppress: (RecallMemoryPresentation) -> Unit,
) {
    val palette = recallPalette()
    val context = LocalContext.current
    val reducedMotion = remember { runCatching { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE) == 0f }.getOrDefault(false) }
    val topics = recallVisibleTopics(state)
    val topic = topics.firstOrNull { it.id == topicId } ?: topics.firstOrNull()
    val memories = recallVisibleMemories(state.copy(presentation = state.presentation.copy(activeTopicId = topic?.id.orEmpty())), forceTopic = true)
    val snackbars = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    Box(Modifier.fillMaxSize().background(palette.page)) {
        LazyColumn(
            Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onBack, Modifier.size(48.dp)) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, "返回", tint = palette.accentText) }
                Spacer(Modifier.width(7.dp))
                Column { Text("主题", color = palette.muted, fontSize = 11.sp); Text(topic?.label.orEmpty(), color = palette.ink, fontSize = 25.sp, fontWeight = FontWeight.Black); Text("${topic?.clipCount ?: 0} 条相关记忆", color = palette.muted, fontSize = 11.sp) }
            }
        }
        item {
            RecallPlanetCard(
                topics = topics,
                memories = memories,
                activeTopicId = topic?.id.orEmpty(),
                queueOffset = 0,
                queueProgress = 0f,
                visibleMemoryLabels = state.presentation.visibleMemoryLabels,
                reducedMotion = reducedMotion,
                motionElapsedMillis = 0L,
                starfieldQuality = MemoryPlanetQuality.STATIC,
                planetContent = MemoryPlanetContentState.NORMAL,
                topicInsight = recallTopicInsight(state, topics, topic?.id.orEmpty()),
                onTopic = onTopicSelected,
                onInteraction = onInteraction,
                onEmptyRetry = {},
            )
        }
        item { Text("主题记忆", color = palette.ink, fontSize = 19.sp, fontWeight = FontWeight.Black) }
        items(memories, key = { it.clipId }) { memory ->
            RecallMemoryCard(
                memory = memory,
                onOpenOriginal = onOpenOriginal,
                onSuppress = onSuppress,
                onMenuVisibilityChanged = { onInteraction() },
            )
        }
        }
        SnackbarHost(snackbars, Modifier.align(Alignment.BottomCenter).padding(bottom = padding.calculateBottomPadding()))
    }
}
