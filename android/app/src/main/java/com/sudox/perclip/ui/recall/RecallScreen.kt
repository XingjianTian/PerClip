package com.sudox.perclip.ui.recall

import android.graphics.Paint
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.AutoStories
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.capabilities.AppFeatureAvailability
import com.sudox.perclip.capabilities.capabilityConfigurationFingerprint
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import com.sudox.perclip.recall.*
import com.sudox.perclip.recall.repository.RecallDomainRequest
import com.sudox.perclip.recall.repository.RecallInteractionRequest
import com.sudox.perclip.recall.repository.RecallResurfaceRequest
import com.sudox.perclip.recall.repository.MemoryPlanetWindow
import com.sudox.perclip.recall.repository.MemoryPlanetFallback
import com.sudox.perclip.recall.repository.MemoryPlanetLoadPolicy
import com.sudox.perclip.recall.repository.matches
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.ui.design.*
import java.time.LocalDate
import java.time.ZoneId
import kotlinx.coroutines.launch
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

/** Four Recall surfaces retain a caller-owned state, so leaving the tab never resets an in-progress revisit. */
@Composable
fun RecallScreen(
    contentPadding: PaddingValues,
    settings: PerClipSettings,
    localRecords: List<UploadRecord>,
    onOpenLocalClip: (String) -> Unit,
    onGoToSave: () -> Unit,
    onGoToSettings: () -> Unit = {},
    featureAvailability: AppFeatureAvailability = AppFeatureAvailability.AVAILABLE,
    memoryPlanetAvailability: AppFeatureAvailability = AppFeatureAvailability.AVAILABLE,
    unavailableMessage: String = "",
    holder: RecallStateHolder,
    knowledgeBases: List<KnowledgeBaseSummary> = emptyList(),
    knowledgeBasesLoading: Boolean = false,
    knowledgeBaseListMessage: String = "",
    onRefreshKnowledgeBases: () -> Unit = {},
    onSettingsChange: (PerClipSettings) -> Unit = {},
    controllerOverride: RecallController? = null,
) {
    val rememberedController = remember { RecallController() }
    val controller = controllerOverride ?: rememberedController
    val domainLoader = remember(controller) { RecallDomainLoader(controller::domain) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val state = holder.state
    val availableKnowledgeBases = knowledgeBases.filterNot { it.isArchived || it.deletedAt.isNotBlank() }
    val knowledgeBaseOptionsKey = availableKnowledgeBases.joinToString("|") { "${it.id}:${it.updatedAt}:${it.isDefault}" }
    val configurationFingerprint = remember(settings.apiUrl, settings.ingestToken) {
        capabilityConfigurationFingerprint(settings)
    }
    fun update(transform: (RecallUiState) -> RecallUiState) = holder.update(transform)
    fun updateDisplay(transform: (RecallUiState) -> RecallUiState) {
        holder.update(transform)
        RecallDisplayPreferenceStore.save(context, holder.state.presentation)
    }
    fun loadHome(
        period: RecallPeriod = holder.state.presentation.period,
        suppressionCursor: String = "",
    ) {
        if (period == RecallPeriod.CUSTOM && !RecallCustomRangePolicy.available(memoryPlanetAvailability)) {
            update {
                RecallUiReducer.notice(
                    RecallUiReducer.setPeriod(it, RecallPeriod.WEEKLY, System.currentTimeMillis()),
                    "当前服务端不支持精确历史日期，仅可读取本周或本月。",
                )
            }
            onSettingsChange(settings.copy(recallPeriodKind = "week", recallPeriodDays = 7))
            loadHome(RecallPeriod.WEEKLY)
            return
        }
        val presentation = holder.state.presentation
        val customDays = if (
            period == RecallPeriod.CUSTOM &&
            presentation.customStartDate.isNotBlank() &&
            presentation.customEndDate.isNotBlank()
        ) {
            runCatching {
                java.time.temporal.ChronoUnit.DAYS.between(
                    LocalDate.parse(presentation.customStartDate),
                    LocalDate.parse(presentation.customEndDate),
                ).toInt() + 1
            }.getOrDefault(7).coerceIn(1, 90)
        } else {
            period.days ?: 7
        }
        val requestedWindow = MemoryPlanetWindow(
            kind = when (period) {
                RecallPeriod.WEEKLY -> "week"
                RecallPeriod.MONTHLY -> "month"
                RecallPeriod.CUSTOM -> "custom"
            },
            days = customDays,
            startDate = presentation.customStartDate,
            endDate = presentation.customEndDate,
            timezone = presentation.customTimezone.ifBlank { ZoneId.systemDefault().id },
            knowledgeBaseId = presentation.knowledgeBaseId,
        )
        val planetSource = RecallPlanetSourcePolicy.forAvailability(memoryPlanetAvailability)
        val requestKey = RecallHomeRequestKey.create(
            configurationFingerprint,
            period,
            requestedWindow,
            planetSource = planetSource,
        )
        val homeRequest = holder.beginHomeRequest(requestKey)
        val suppressionGeneration = holder.beginSuppressions()
        update { it.copy(suppressed = it.suppressed.copy(loading = true, error = "")) }
        scope.launch {
            coroutineScope {
                val days = customDays
                val custom = period == RecallPeriod.CUSTOM
                val domain = async {
                    controller.domain(
                        settings,
                        RecallDomainRequest(
                            days = days,
                            topicLimit = 5,
                            memoryLimit = 80,
                            startDate = requestedWindow.startDate.takeIf { custom }.orEmpty(),
                            endDate = requestedWindow.endDate.takeIf { custom }.orEmpty(),
                            timezone = requestedWindow.timezone.takeIf { custom }.orEmpty(),
                            knowledgeBaseId = requestedWindow.knowledgeBaseId,
                        ),
                    )
                }
                val resurfaced = async {
                    controller.resurface(
                        settings,
                        RecallResurfaceRequest(
                            days = days,
                            limit = 8,
                            startDate = requestedWindow.startDate.takeIf { custom }.orEmpty(),
                            endDate = requestedWindow.endDate.takeIf { custom }.orEmpty(),
                            timezone = requestedWindow.timezone.takeIf { custom }.orEmpty(),
                            knowledgeBaseId = requestedWindow.knowledgeBaseId,
                        ),
                    )
                }
                val planet = if (MemoryPlanetLoadPolicy.shouldRequest(memoryPlanetAvailability)) {
                    async { controller.memoryPlanet(settings, requestedWindow) }
                } else {
                    null
                }
                val suppressions = async {
                    controller.suppressions(settings, cursor = suppressionCursor, limit = 50)
                }
                val domainResult = domain.await()
                val resurfaceResult = resurfaced.await()
                val planetResult = planet?.await()
                if (holder.isHomeRequestCurrent(homeRequest)) {
                    update { current ->
                        var next = if (domainResult.ok && domainResult.value != null) {
                            if (domainResult.value.matches(requestedWindow)) {
                                RecallUiReducer.domainLoaded(current, domainResult.value)
                            } else {
                                RecallUiReducer.domainFailed(current, "记忆星球主题响应与当前时间范围不一致。")
                            }
                        } else {
                            RecallUiReducer.domainFailed(current, domainResult.message.safeRecallMessage())
                        }
                        next = if (resurfaceResult.ok && resurfaceResult.value != null) {
                            if (resurfaceResult.value.matches(requestedWindow)) {
                                RecallUiReducer.resurfacedLoaded(next, resurfaceResult.value)
                            } else {
                                RecallUiReducer.resurfacedFailed(next, "自动浮现响应与当前时间范围不一致。")
                            }
                        } else {
                            RecallUiReducer.resurfacedFailed(next, resurfaceResult.message.safeRecallMessage())
                        }
                        val validPlanet = planetResult?.value?.takeIf {
                            planetResult.ok && it.window.matches(requestedWindow)
                        }
                        if (validPlanet != null) {
                            if (requestKey.planetSource == RecallPlanetSource.DEDICATED) {
                                holder.rememberPlanet(requestKey, validPlanet)
                            }
                            RecallUiReducer.memoryPlanetLoaded(next, validPlanet)
                        } else {
                            val cached = holder.cachedPlanet(requestKey)
                            val fallback = MemoryPlanetFallback.buildAvailable(
                                domain = next.domain.value,
                                resurfaced = next.resurfaced.value,
                                window = requestedWindow,
                            )
                            val selected = RecallPlanetSourcePolicy.selectFailureValue(
                                source = requestKey.planetSource,
                                cached = cached,
                                freshFallback = fallback,
                            )
                            val message = planetResult?.message?.safeRecallMessage()
                                ?.ifBlank { "记忆星球响应与当前时间范围不一致。" }
                                ?: "当前服务端未提供记忆星球，已显示兼容数据。"
                            when {
                                selected != null && selected === cached -> RecallUiReducer.notice(
                                    RecallUiReducer.memoryPlanetLoaded(next, selected),
                                    "$message 已保留这个时间范围上次成功的数据。",
                                )
                                selected != null -> RecallUiReducer.notice(
                                    RecallUiReducer.memoryPlanetLoaded(next, selected),
                                    message,
                                )
                                else -> RecallUiReducer.notice(
                                    RecallUiReducer.memoryPlanetFailed(next, message),
                                    message,
                                )
                            }
                        }
                    }
                }
                val suppressionsResult = suppressions.await()
                if (holder.isSuppressionsCurrent(suppressionGeneration)) {
                    update { current ->
                        if (suppressionsResult.ok && suppressionsResult.value != null) {
                            RecallUiReducer.suppressionsLoaded(current, suppressionsResult.value)
                        } else {
                            RecallUiReducer.suppressionsFailed(
                                current,
                                suppressionsResult.message.safeRecallMessage(),
                            )
                        }
                    }
                }
            }
        }
    }
    fun loadOverview() {
        val generation = holder.beginOverview()
        update(RecallUiReducer::overviewLoading)
        scope.launch { controller.overview(settings).let { result ->
            if (!holder.isOverviewCurrent(generation)) return@let
            update { current -> if (result.ok && result.value != null) RecallUiReducer.overviewLoaded(current, result.value) else RecallUiReducer.overviewFailed(current, result.message.safeRecallMessage()) }
        } }
    }
    fun refreshOverview() {
        if (featureAvailability == AppFeatureAvailability.AVAILABLE) loadOverview()
        else update { RecallUiReducer.overviewFailed(it, unavailableMessage.ifBlank { "当前服务端未提供记忆星球接口，请前往设置检查。" }) }
    }
    fun loadTopic(topicId: String, filter: RecallTopicFilter = holder.state.topicFilter) {
        val generation = holder.beginTopic()
        update { RecallUiReducer.topicLoading(it, filter) }
        scope.launch { controller.topic(settings, topicId, filter = filter).let { result ->
            val activeTopic = holder.state.destination as? RecallDestination.Topic
            if (!holder.isTopicCurrent(generation) || activeTopic?.topicId != topicId) return@let
            update { current -> if (result.ok && result.value != null) RecallUiReducer.topicLoaded(current, result.value) else RecallUiReducer.topicFailed(current, result.message.safeRecallMessage()) }
        } }
    }
    fun loadWeekly() {
        val generation = holder.beginWeekly()
        update(RecallUiReducer::weeklyLoading)
        scope.launch { controller.weekly(settings).let { result ->
            if (!holder.isWeeklyCurrent(generation) || holder.state.destination != RecallDestination.Weekly) return@let
            update { current -> if (result.ok && result.value != null) RecallUiReducer.weeklyLoaded(current, result.value) else RecallUiReducer.weeklyFailed(current, result.message.safeRecallMessage()) }
        } }
    }
    fun startSession(topicId: String = "", limit: Int = 8) {
        val generation = holder.beginSession()
        holder.navigate(RecallDestination.Session(null))
        update(RecallUiReducer::sessionLoading)
        scope.launch { controller.createSession(settings, RecallSessionRequest(topicId = topicId, limit = limit)).let { result ->
            if (!holder.isSessionCurrent(generation) || holder.state.destination != RecallDestination.Session(null)) return@let
            update { current -> if (result.ok && result.value != null) RecallUiReducer.sessionLoaded(current.copy(destination = RecallDestination.Session(result.value.session.id)), result.value) else RecallUiReducer.sessionFailed(current, result.message.safeRecallMessage()) }
        } }
    }
    fun openOriginal(target: RecallOriginalTarget) {
        when (val strategy = RecallUiReducer.originalStrategy(target, localRecords.map { it.clip.id }.toSet())) {
            is RecallOriginalStrategy.LocalDetail -> onOpenLocalClip(strategy.localClipId)
            is RecallOriginalStrategy.SafeRemoteSheet -> if (target.clientRequestId.isBlank() && target.serverClipId.isNotBlank()) {
                val request = holder.beginOriginalResolve()
                scope.launch {
                controller.clip(settings, target.serverClipId).let { result ->
                    val resolved = result.value
                    val localId = resolved?.let { RecallUiReducer.localClipId(it.clientRequestId, localRecords.map { record -> record.clip.id }.toSet()) }
                    if (!holder.isOriginalResolveCurrent(request)) return@let
                    if (result.ok && localId != null) onOpenLocalClip(localId)
                    else update { RecallUiReducer.showOriginal(it, RecallOriginalStrategy.SafeRemoteSheet(target, resolved)) }
                }
            } } else update { RecallUiReducer.showOriginal(it, strategy) }
        }
    }
    fun navigate(destination: RecallDestination) = holder.navigate(destination)
    fun back() { holder.back() }
    fun suppress(memory: RecallMemoryPresentation) {
        scope.launch {
            val result = controller.recordInteraction(
                settings,
                RecallInteractionRequest(
                    surface = "resurface",
                    action = "suppress",
                    nodeId = "clip:${memory.clipId}",
                    clipId = memory.clipId,
                    metadata = com.sudox.perclip.recall.repository.RecallInteractionMetadata(source = "memory_planet"),
                ),
            )
            if (result.ok) loadHome() else update { RecallUiReducer.memoryPlanetFailed(it, result.message.safeRecallMessage()) }
        }
    }
    fun restore(memory: RecallSuppressedItem) {
        val suppressionPage = holder.state.suppressed.value
        val refreshCursor = if (
            suppressionPage?.items?.size == 1 &&
            suppressionPage.previousCursor.isNotBlank()
        ) {
            suppressionPage.previousCursor
        } else {
            suppressionPage?.cursor.orEmpty()
        }
        scope.launch {
            val result = controller.recordInteraction(
                settings,
                RecallInteractionRequest(
                    surface = "resurface",
                    action = "restore",
                    nodeId = "clip:${memory.clipId}",
                    clipId = memory.clipId,
                    metadata = com.sudox.perclip.recall.repository.RecallInteractionMetadata(
                        source = "memory_planet",
                    ),
                ),
            )
            if (result.ok) {
                update { RecallUiReducer.suppressionRestored(it, memory.clipId) }
                loadHome(suppressionCursor = refreshCursor)
            } else {
                update {
                    RecallUiReducer.suppressionsFailed(
                        it,
                        result.message.safeRecallMessage(),
                    )
                }
            }
        }
    }
    fun loadSuppressionPage(cursor: String) {
        if (cursor.isBlank()) return
        val generation = holder.beginSuppressions()
        update { it.copy(suppressed = it.suppressed.copy(loading = true, error = "")) }
        scope.launch {
            val result = controller.suppressions(settings, cursor = cursor, limit = 50)
            if (!holder.isSuppressionsCurrent(generation)) return@launch
            update { current ->
                if (result.ok && result.value != null) {
                    RecallUiReducer.suppressionPageLoaded(current, result.value)
                } else {
                    RecallUiReducer.suppressionsFailed(current, result.message.safeRecallMessage())
                }
            }
        }
    }
    LaunchedEffect(holder) {
        holder.applyDisplayPreferencesOnce(RecallDisplayPreferenceStore.load(context))
        val selection = RecallSelectionStore.load(context)
        if (holder.state.presentation.activeTopicId.isBlank() && selection.activeTopicId.isNotBlank()) {
            holder.update { current ->
                current.copy(
                    presentation = current.presentation.copy(
                        activeTopicId = selection.activeTopicId,
                        pinnedTopicId = selection.activeTopicId.takeIf { selection.scope == RecallScope.ACTIVE_TOPIC }.orEmpty(),
                        scope = selection.scope,
                        knowledgeBaseId = selection.knowledgeBaseId,
                    ),
                )
            }
        }
    }
    LaunchedEffect(
        settings.recallPeriodKind,
        settings.recallPeriodDays,
        settings.recallCustomStartDate,
        settings.recallCustomEndDate,
        settings.recallCustomTimezone,
        settings.reduceMotion,
    ) {
        holder.update { current ->
            current.copy(presentation = current.presentation.copy(
                period = when (settings.recallPeriodKind) {
                    "month" -> RecallPeriod.MONTHLY
                    "custom" -> RecallPeriod.CUSTOM
                    else -> RecallPeriod.WEEKLY
                },
                customStartDate = settings.recallCustomStartDate,
                customEndDate = settings.recallCustomEndDate,
                customTimezone = settings.recallCustomTimezone,
                autoSurfaceEnabled = true,
                // Stage 23.13 removes the home-page fold state. Keep the
                // legacy setting readable for migration, but always present
                // the planet and its insight together.
                graphExpanded = true,
                reducedMotion = settings.reduceMotion,
            ))
        }
    }
    LaunchedEffect(knowledgeBaseOptionsKey, configurationFingerprint, featureAvailability) {
        if (featureAvailability != AppFeatureAvailability.AVAILABLE) return@LaunchedEffect
        val currentId = holder.state.presentation.knowledgeBaseId
        val currentAvailable = currentId.isBlank() || availableKnowledgeBases.any { it.id == currentId }
        val fallback = availableKnowledgeBases.firstOrNull { it.isDefault } ?: availableKnowledgeBases.firstOrNull()
        val nextId = when {
            currentId.isNotBlank() && currentAvailable -> currentId
            fallback != null -> fallback.id
            else -> ""
        }
        if (nextId != currentId) {
            update { RecallUiReducer.setKnowledgeBase(it, nextId, System.currentTimeMillis()) }
            RecallSelectionStore.save(context, holder.state.presentation)
            loadHome()
        }
    }
    LaunchedEffect(
        configurationFingerprint,
        featureAvailability,
        memoryPlanetAvailability,
        state.destination,
        state.domain,
        state.resurfaced,
    ) {
        holder.prepareOverviewForConfiguration(
            "$configurationFingerprint|$featureAvailability|$memoryPlanetAvailability",
        )
        if (featureAvailability == AppFeatureAvailability.UNAVAILABLE) {
            if (holder.state.destination != RecallDestination.Overview) holder.navigate(RecallDestination.Overview)
            update { RecallUiReducer.domainFailed(it, unavailableMessage.ifBlank { "当前服务端未提供记忆星球接口，请更新服务端或检查 API 地址" }) }
        } else if (featureAvailability == AppFeatureAvailability.AVAILABLE) {
            if (RecallHomeLoadPolicy.shouldLoad(holder.state)) loadHome()
        }
    }
    BackHandler(enabled = state.pendingOriginal != null || state.destination != RecallDestination.Overview) {
        if (state.pendingOriginal != null) holder.dismissOriginal() else back()
    }
    when (val destination = state.destination) {
        RecallDestination.Overview -> RecallHomeContent(
            state = state,
            padding = contentPadding,
            knowledgeBases = availableKnowledgeBases,
            knowledgeBasesLoading = knowledgeBasesLoading,
            knowledgeBaseListMessage = knowledgeBaseListMessage,
            onRefreshKnowledgeBases = onRefreshKnowledgeBases,
            onOpenDisplaySettings = { navigate(RecallDestination.DisplaySettings) },
            onRefresh = { if (featureAvailability == AppFeatureAvailability.AVAILABLE) loadHome() },
            onTopicSelected = { topicId ->
                val now = System.currentTimeMillis()
                update { RecallUiReducer.selectTopic(it, topicId, now) }
                RecallSelectionStore.save(context, holder.state.presentation)
                scope.launch { controller.recordInteraction(settings, RecallInteractionRequest(surface = "graph", action = "open_topic", nodeId = topicId, topicId = topicId)) }
            },
            onPeriod = { period ->
                update { RecallUiReducer.setPeriod(it, period, System.currentTimeMillis()) }
                if (period != RecallPeriod.CUSTOM) {
                    onSettingsChange(
                        settings.copy(
                            recallPeriodDays = period.days ?: 7,
                            recallPeriodKind = if (period == RecallPeriod.MONTHLY) "month" else "week",
                        ),
                    )
                    loadHome(period)
                }
            },
            onCustomRange = { startDate, endDate, timezone ->
                update {
                    RecallUiReducer.setCustomRange(
                        it,
                        startDate,
                        endDate,
                        timezone,
                        System.currentTimeMillis(),
                    )
                }
                onSettingsChange(
                    settings.copy(
                        recallPeriodKind = "custom",
                        recallCustomStartDate = startDate,
                        recallCustomEndDate = endDate,
                        recallCustomTimezone = timezone,
                    ),
                )
                loadHome(RecallPeriod.CUSTOM)
            },
            customRangeAvailable = RecallCustomRangePolicy.available(memoryPlanetAvailability),
            onKnowledgeBaseSelected = { knowledgeBaseId ->
                update { RecallUiReducer.setKnowledgeBase(it, knowledgeBaseId, System.currentTimeMillis()) }
                RecallSelectionStore.save(context, holder.state.presentation)
                if (featureAvailability == AppFeatureAvailability.AVAILABLE) loadHome()
            },
            onReducedMotion = { reduced -> update { RecallUiReducer.setReducedMotion(it, reduced) } },
            onRotateTopic = { update(RecallUiReducer::rotateTopic) },
            onInteraction = { update { RecallUiReducer.markInteraction(it, System.currentTimeMillis()) } },
            onOpenOriginal = ::openOriginal,
            onSuppress = ::suppress,
            onRestore = ::restore,
            onSuppressionPage = ::loadSuppressionPage,
            onNoticeShown = { update(RecallUiReducer::noticeShown) },
            reducedMotionOverride = settings.reduceMotion,
        )
        is RecallDestination.Topic -> RecallTopicFocusContent(
            state = state,
            topicId = destination.topicId,
            padding = contentPadding,
            onBack = ::back,
            onTopicSelected = { topicId -> update { RecallUiReducer.selectTopic(it, topicId, System.currentTimeMillis()) }; navigate(RecallDestination.Topic(topicId)) },
            onInteraction = { update { RecallUiReducer.markInteraction(it, System.currentTimeMillis()) } },
            onOpenOriginal = ::openOriginal,
            onSuppress = ::suppress,
        )
        is RecallDestination.Session -> SessionContent(state, ::back, { action ->
            val response = state.session.value ?: return@SessionContent
            val item = response.currentItem ?: return@SessionContent
            if (state.actionInFlight) return@SessionContent
            val generation = holder.beginAction()
            update(RecallUiReducer::actionStarted); scope.launch { controller.action(settings, response.session.id, item.id, RecallEventRequest(action)).let { result ->
                val current = holder.state.session.value
                if (!holder.isActionCurrent(generation) || holder.state.destination != RecallDestination.Session(response.session.id) || current?.currentItem?.id != item.id) return@let
                update { latest -> if (result.ok && result.value != null) RecallUiReducer.actionApplied(latest, action, result.value) else RecallUiReducer.actionFailed(latest, result.message.safeRecallMessage()) }
                if (result.ok && action == RecallEventAction.OPEN_ORIGINAL) openOriginal(RecallOriginalTarget(item.clipId, item.clientRequestId))
            } }
        }, { navigate(RecallDestination.Weekly); loadWeekly() }, contentPadding)
        RecallDestination.Weekly -> WeeklyContent(state, ::back, ::loadWeekly, { id -> navigate(RecallDestination.Topic(id)); loadTopic(id) }, ::startSession, ::openOriginal, contentPadding)
        RecallDestination.DisplaySettings -> RecallDisplaySettingsContent(
            state = state,
            padding = contentPadding,
            onBack = ::back,
            onVisibleTopicCount = { count -> updateDisplay { RecallUiReducer.setVisibleTopicCount(it, count) } },
            onVisibleMemoryLabels = { count -> updateDisplay { RecallUiReducer.setVisibleMemoryLabels(it, count) } },
            onTopicVisible = { topicId, visible -> updateDisplay { RecallUiReducer.setTopicVisible(it, topicId, visible) } },
            onRestoreDefaults = { updateDisplay(RecallUiReducer::restoreDisplayDefaults) },
        )
    }
    (state.pendingOriginal as? RecallOriginalStrategy.SafeRemoteSheet)?.let { strategy -> RecallOriginalSheet(settings, strategy, holder::dismissOriginal) }
}

@Composable private fun RecallTopBar(title: String, onBack: (() -> Unit)? = null, onRefresh: (() -> Unit)? = null) = Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) { if (onBack != null) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, "返回") }; Text(title, Modifier.weight(1f), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black); if (onRefresh != null) IconButton(onClick = onRefresh) { Icon(Icons.Rounded.Refresh, "重新加载") } }

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun OverviewContent(state: RecallUiState, refresh: () -> Unit, onTopic: (String) -> Unit, onStart: () -> Unit, onWeekly: () -> Unit, onSave: () -> Unit, onSettings: () -> Unit, padding: PaddingValues, onOriginal: (RecallOriginalTarget) -> Unit) {
    val overview = state.overview.value; var showTopics by remember(overview?.graph) { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(bottom = 24.dp)) {
        val metricPresentation = when { overview != null -> MetricPresentation.Data(overview.metrics.recallCount, overview.metrics.newTopicCount, overview.metrics.reviewedRatio); state.overview.loading -> MetricPresentation.Loading; else -> MetricPresentation.Unavailable }
        item { RecallTopBar("记忆星球", onRefresh = refresh); RangeMetrics(metricPresentation) }
        if (state.overview.loading && overview == null) item { OverviewSkeleton() }; if (state.overview.error.isNotBlank()) item { RecallError(state.overview.error, refresh, if (state.overview.error.needsSettingsAction()) onSettings else null); OverviewPlaceholder() }
        if (overview != null && overview.metrics.eligibleClipCount == 0) item { RecallEmpty("近 7 日还没有可浮现的闪记", "先保存一些内容，它们会在这里重新浮现。", "去闪记", onSave) }
        if (overview != null && overview.metrics.eligibleClipCount > 0) {
            item { Button(onClick = onStart, Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) { Text("开始重温", fontWeight = FontWeight.Bold) } }
            item { val hasTopics = overview.graph.nodes.any { it.type.equals("topic", true) }; SectionHeader("知识关系图谱", if (hasTopics) "全部主题 >" else "") { showTopics = true }; RecallGraphPanel(overview.graph, onTopic, onOriginal) }
            item { SectionHeader("重新浮现", "更多 >", onWeekly) }
            items(overview.highlights.take(3), key = { it.title + it.occurredAt }) { h -> RecallLine(h.title, h.subtitle, recallRelativeDate(h.occurredAt)) { if (h.topicId.isNotBlank()) onTopic(h.topicId) else if (h.clipId.isNotBlank()) onOriginal(RecallOriginalTarget(h.clipId, h.clientRequestId)) } }
        }
    }
    if (showTopics && overview != null) ModalBottomSheet(onDismissRequest = { showTopics = false }) { LazyColumn(Modifier.padding(horizontal = 20.dp).fillMaxWidth(), contentPadding = PaddingValues(bottom = 28.dp)) { item { Text("全部主题", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black, modifier = Modifier.padding(bottom = 8.dp)) }; items(overview.graph.nodes.filter { it.type.equals("topic", true) }.sortedWith(compareByDescending<RecallGraphNode> { it.weight }.thenBy { it.label }), key = { it.id }) { node -> RecallLine(node.label, "${node.weight} 条关联", "") { showTopics = false; onTopic(node.topicId.ifBlank { node.id }) } } } }
}

private sealed interface MetricPresentation { data class Data(val recall: Int, val topics: Int, val ratio: Double) : MetricPresentation; data object Loading : MetricPresentation; data object Unavailable : MetricPresentation }
@Composable private fun RangeMetrics(presentation: MetricPresentation) = PerClipCard(Modifier.padding(horizontal = 20.dp, vertical = 4.dp), containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .55f)) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text("近 7 日记忆", fontWeight = FontWeight.Bold); Icon(Icons.Rounded.CalendarMonth, null) }; Spacer(Modifier.height(12.dp)); Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { when (presentation) { is MetricPresentation.Data -> { Metric("回看次数", presentation.recall.toString()); Metric("新主题", presentation.topics.toString()); Metric("已重温", "${(presentation.ratio * 100).toInt()}%") }; MetricPresentation.Loading -> repeat(3) { Metric("加载中", "···") }; MetricPresentation.Unavailable -> { Metric("回看次数", "—"); Metric("新主题", "—"); Metric("已重温", "—") } } } }
@Composable private fun Metric(label: String, value: String) = Column { Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Black); Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
@Composable private fun OverviewSkeleton() = Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) { OverviewPlaceholder(); Spacer(Modifier.height(12.dp)); OverviewPlaceholder(); Spacer(Modifier.height(8.dp)); OverviewPlaceholder() }
@Composable private fun OverviewPlaceholder() = Surface(Modifier.fillMaxWidth().height(74.dp), RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .48f)) { Box(contentAlignment = Alignment.Center) { Text("·  ·  ·", color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = .38f)) } }
@Composable private fun SectionHeader(title: String, action: String, onClick: () -> Unit) = Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) { Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold); if (action.isNotBlank()) Text(action, Modifier.clickable(onClick = onClick), color = MaterialTheme.colorScheme.onSurfaceVariant) }

@Composable private fun RecallGraphPanel(graph: RecallGraph, onTopic: (String) -> Unit, onOriginal: (RecallOriginalTarget) -> Unit, mode: RecallGraphMode = RecallGraphMode.OVERVIEW, focusTopicId: String = "") {
    if (graph.nodes.isEmpty()) { PerClipCard(Modifier.padding(horizontal = 20.dp)) { Text("暂时没有足够的关系数据", color = MaterialTheme.colorScheme.onSurfaceVariant) }; return }
    val density = LocalDensity.current; val style = with(density) { RecallGraphStylePx(25.dp.toPx(), 7.dp.toPx(), 104.dp.toPx(), 62.dp.toPx(), 12.dp.toPx(), 12.dp.toPx()) }
    val context = LocalContext.current
    val motionScale = remember { runCatching { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE) }.getOrDefault(1f) }
    val simulation = remember(graph, mode, focusTopicId) { RecallForceSimulation() }
    var layout by remember(graph, mode, focusTopicId) { mutableStateOf(RecallGraphLayout()) }
    val outline = MaterialTheme.colorScheme.outline; val accent = MaterialTheme.colorScheme.primary; val accentInk = MaterialTheme.colorScheme.onPrimary; val topicInk = ColorTokens.InkBlack; val clipInk = MaterialTheme.colorScheme.onSurface; val canvasColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = .50f)
    var canvasSize by remember(graph) { mutableStateOf(IntSize.Zero) }
    LaunchedEffect(graph, canvasSize, mode, focusTopicId, motionScale) {
        if (canvasSize == IntSize.Zero) return@LaunchedEffect
        simulation.reset(graph, canvasSize.width.toFloat(), canvasSize.height.toFloat(), style, mode, focusTopicId)
        if (motionScale == 0f) { layout = simulation.settled(); return@LaunchedEffect }
        var previous = 0L; var frame = 0
        while (true) { val now = withFrameNanos { it }; if (previous != 0L && frame++ % 2 == 0) { simulation.tick(((now - previous) / 1_000_000_000f).coerceAtMost(.05f)); layout = simulation.snapshot() }; previous = now }
    }
    Surface(Modifier.fillMaxWidth().padding(horizontal = 20.dp), RoundedCornerShape(22.dp), color = canvasColor, tonalElevation = 0.dp) { Column(Modifier.padding(10.dp)) {
        var draggedNodeId by remember(graph, mode, focusTopicId) { mutableStateOf<String?>(null) }
        Canvas(Modifier.fillMaxWidth().height(206.dp).onSizeChanged { canvasSize = it }.pointerInput(layout) { detectTapGestures { tap ->
            layout.hitTest(RecallGraphPoint(tap.x, tap.y))?.let { hit -> when (val target = RecallUiReducer.graphTapTarget(hit)) { is RecallGraphTapTarget.Topic -> if (target.topicId.isNotBlank()) onTopic(target.topicId); is RecallGraphTapTarget.Original -> if (target.target.serverClipId.isNotBlank()) onOriginal(target.target) } }
        } }.pointerInput(layout) { detectDragGestures(onDragStart = { start -> draggedNodeId = layout.hitTest(RecallGraphPoint(start.x, start.y))?.id; draggedNodeId?.let { simulation.dragStart(it, start.x, start.y) } }, onDrag = { change, _ -> draggedNodeId?.let { simulation.dragMove(it, change.position.x, change.position.y); layout = simulation.snapshot(); change.consume() } }, onDragEnd = { draggedNodeId?.let(simulation::dragEnd); draggedNodeId = null }) }) {
            val drawn = layout; val driftY = 0f
            for (x in 8..size.width.toInt() step 22) for (y in 8..size.height.toInt() step 22) drawCircle(outline.copy(alpha = .12f), .9f, androidx.compose.ui.geometry.Offset(x.toFloat(), y.toFloat()))
            graph.edges.forEach { edge -> val a = drawn.nodes.firstOrNull { it.id == edge.source }?.point; val b = drawn.nodes.firstOrNull { it.id == edge.target }?.point; if (a != null && b != null) drawLine(outline.copy(.20f), androidx.compose.ui.geometry.Offset(a.x, a.y + driftY), androidx.compose.ui.geometry.Offset(b.x, b.y + driftY), 1f) }
            drawn.nodes.forEach { node -> val isTopic = node.type.equals("topic", true); val point = androidx.compose.ui.geometry.Offset(node.point.x, node.point.y + driftY); val topicColor = when (node.colorSlot.mod(4)) { 1 -> Color(0xFFCFEAD9); 2 -> Color(0xFFCFE4F5); 3 -> Color(0xFFE4D8F3); else -> Color(0xFFF7D9BE) }; val fill = if (node.isFocus) accent else if (isTopic) topicColor else topicColor.copy(alpha = .42f); drawCircle(fill, node.radius, point); drawCircle(if (node.isFocus) accent.copy(.75f) else outline.copy(.24f), node.radius, point, style = Stroke(if (isTopic) 1.1f else .8f)); drawIntoCanvas { canvas ->
                val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = (if (node.isFocus) accentInk else if (isTopic) topicInk else clipInk).toArgb(); textAlign = if (isTopic) Paint.Align.CENTER else if (node.labelPoint.x >= node.point.x) Paint.Align.LEFT else Paint.Align.RIGHT; typeface = android.graphics.Typeface.create(android.graphics.Typeface.DEFAULT, if (isTopic) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL); textSize = if (isTopic) fitTopicLabelFontSize(this, node.shortLabel, node.radius) else 9.dp.toPx() }
                if (isTopic) {
                    val centeredBaseline = point.y - (paint.ascent() + paint.descent()) / 2f
                    canvas.nativeCanvas.drawText(node.shortLabel, point.x, centeredBaseline, paint)
                } else canvas.nativeCanvas.drawText(node.compactLabel, node.labelPoint.x, node.labelPoint.y + driftY, paint)
            } }
        }
    } }
}

@Composable private fun TopicContent(state: RecallUiState, topicId: String, back: () -> Unit, reload: (String, RecallTopicFilter) -> Unit, relatedTopic: (String) -> Unit, start: (String, Int) -> Unit, openOriginal: (RecallOriginalTarget) -> Unit, padding: PaddingValues) { val topic = state.topic.value; LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(bottom = 24.dp)) { item { RecallTopBar(topic?.topic?.label ?: "主题", back) }; item { Row(Modifier.padding(horizontal = 20.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) { RecallTopicFilter.entries.forEach { filter -> FilterChip(selected = state.topicFilter == filter, onClick = { reload(topicId, filter) }, label = { Text(when(filter){RecallTopicFilter.ALL->"7日内";RecallTopicFilter.FREQUENT->"高频";RecallTopicFilter.UNRECALLED->"未重温"}) }) } } }; if(state.topic.loading && topic == null) item { RecallLoading() }; if(state.topic.error.isNotBlank()) item { RecallError(state.topic.error, retry = { reload(topicId, state.topicFilter) }) }; if(topic != null) { item { Text("服务器主题记忆 · ${topic.metrics.clipCount} 条", Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant); RecallGraphPanel(topic.graph, { selected -> if (selected != topicId) relatedTopic(selected) }, openOriginal, RecallGraphMode.TOPIC, topicId); Button(onClick = { start(topicId, minOf(8, topic.metrics.clipCount.coerceAtLeast(1))) }, modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) { Text("重温这个主题") } }; if(topic.items.isEmpty()) item { RecallEmpty("这个筛选下暂时没有闪记", "换一个筛选看看。", "返回主题", back) }; items(topic.items, key = { it.clipId }) { clip -> TopicClipRow(clip) { openOriginal(RecallOriginalTarget(clip.clipId, clip.clientRequestId)) } } } } }
@Composable private fun TopicClipRow(clip: RecallTopicClip, view: () -> Unit) = PerClipCard(Modifier.padding(horizontal = 20.dp, vertical = 5.dp)) { Text(clip.title, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis); Text(clip.summary, maxLines = 2, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant); Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) { Text("查看原文", Modifier.clickable(onClick = view).padding(8.dp), color = MaterialTheme.colorScheme.primary) } }

@Composable private fun SessionContent(state: RecallUiState, back: () -> Unit, action: (RecallEventAction) -> Unit, weekly: () -> Unit, padding: PaddingValues) { val response = state.session.value; val progress = state.currentProgress; val progressText = if (response?.session?.status == "completed") "${progress.total} / ${progress.total}" else "${progress.currentPosition.coerceAtLeast(1)} / ${progress.total}"; Column(Modifier.fillMaxSize().padding(padding)) { RecallTopBar("重温", back); if (state.session.loading && response == null) RecallLoading() else if (state.session.error.isNotBlank()) RecallError(state.session.error, retry = {}) else { val item = response?.currentItem; if (response == null || item == null) { RecallEmpty(if (response?.session?.status == "completed") "这轮重温完成" else "当前没有可重温的内容", if (response?.session?.status == "completed") "这一轮已看完 ${progress.completed} 条内容。" else "回到首页后可以稍后再试。", "返回记忆星球", back); if (response?.session?.status == "completed") OutlinedButton(onClick = weekly, modifier = Modifier.padding(horizontal = 20.dp)) { Text("查看周回顾") } } else { LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(bottom = 16.dp)) { item { Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 2.dp), horizontalArrangement = Arrangement.End) { PerClipBadge(progressText, PerClipStatusTone.Neutral) } }; item { PerClipCard(Modifier.padding(horizontal = 20.dp, vertical = 8.dp), containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(.7f)) { Icon(Icons.Rounded.AutoStories, "重温", tint = MaterialTheme.colorScheme.primary); Text(item.title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Black); Text("这条内容在说什么", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant); Surface(Modifier.fillMaxWidth().padding(top = 8.dp), RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.primary.copy(alpha = .16f)) { Text(item.summary.ifBlank { item.cue }, Modifier.padding(16.dp), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold) }; val expanded = state.revealedItemId == item.id; Surface(Modifier.fillMaxWidth().padding(top = 16.dp).clickable { if (!expanded) action(RecallEventAction.REVEAL) }, RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surface.copy(alpha = .64f)) { Column(Modifier.padding(14.dp)) { Text(if (expanded) "更多片段" else "再看一眼", fontWeight = FontWeight.Bold); Text(if (expanded) state.revealedText.ifBlank { item.revealText } else "展开更多", Modifier.padding(top = 4.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) } }; Spacer(Modifier.height(12.dp)); Text(item.tags.take(3).joinToString(" · "), style = MaterialTheme.typography.labelSmall); Text(listOf(item.knowledgeBaseName, item.sourceLabel, recallRelativeDate(item.capturedAt)).filter(String::isNotBlank).joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } } }; if (state.actionInFlight) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) ; Button(onClick = { action(RecallEventAction.REMEMBERED) }, enabled = !state.actionInFlight, modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp)) { Text(if (state.actionInFlight) "处理中…" else "看完了") }; Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedButton(onClick = { action(RecallEventAction.LATER) }, enabled = !state.actionInFlight, modifier = Modifier.weight(1f)) { Text("稍后再看") }; OutlinedButton(onClick = { action(RecallEventAction.OPEN_ORIGINAL) }, enabled = !state.actionInFlight, modifier = Modifier.weight(1f)) { Text("查看原文") } } } } } }

@Composable private fun WeeklyContent(state: RecallUiState, back: () -> Unit, reload: () -> Unit, onTopic: (String) -> Unit, start: (String, Int) -> Unit, original: (RecallOriginalTarget) -> Unit, padding: PaddingValues) { val weekly = state.weekly.value; LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(bottom = 24.dp)) { item { RecallTopBar("周回顾", back, reload) }; if (state.weekly.loading && weekly == null) item { RecallLoading() }; if (state.weekly.error.isNotBlank()) item { RecallError(state.weekly.error, reload) }; weekly?.let { review -> item { PerClipSectionCard("这一周重新浮现了什么") { Text(review.summary.summaryText.ifBlank { "这一周的内容正在慢慢重新浮现。" }); Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Metric("保存", review.summary.savedCount.toString()); Metric("回看", review.summary.recallCount.toString()); Metric("主题", review.summary.topicCount.toString()); Metric("连接", review.summary.connectionCount.toString()) } } }; item { SectionHeader("高频主题", "", {}); review.topTopics.take(5).forEachIndexed { index, topic -> RecallLine("${index + 1}. ${topic.label}", "${topic.recallCount} 次回看 · ${topic.clipCount} 条", "") { onTopic(topic.topicId) } } }; if (review.mostRecalled.isNotEmpty()) item { SectionHeader("最常回看的内容", "", {}); review.mostRecalled.take(5).forEach { RecallLine(it.title, "回看 ${it.recallCount} 次", "") { original(RecallOriginalTarget(it.clipId)) } } }; item { SectionHeader("建议再看", "", {}); review.suggestedItems.take(5).forEach { SuggestedRow(it) { start(it.topicId, 8) } } } } } }
@Composable private fun SuggestedRow(item: RecallWeeklyItem, start: () -> Unit) = RecallLine(item.title, item.topicLabel, "重温", start)
@Composable private fun RecallLine(title: String, subtitle: String, trailing: String, onClick: () -> Unit) = PerClipCard(Modifier.padding(horizontal = 20.dp, vertical = 4.dp).clickable(onClick = onClick)) { Row(verticalAlignment = Alignment.CenterVertically) { Column(Modifier.weight(1f)) { Text(title, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis); if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis) }; if (trailing.isNotBlank()) Text(trailing, color = MaterialTheme.colorScheme.primary) } }
@Composable private fun RecallLoading() = Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = MaterialTheme.colorScheme.primary) }
@Composable private fun RecallError(message: String, retry: () -> Unit, settings: (() -> Unit)? = null) = PerClipCard(Modifier.padding(20.dp), containerColor = MaterialTheme.colorScheme.errorContainer) { Text(message); Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) { Text("重新加载", Modifier.padding(top = 8.dp).clickable(onClick = retry), color = MaterialTheme.colorScheme.onErrorContainer, fontWeight = FontWeight.Bold); if (settings != null) Text("去设置", Modifier.padding(top = 8.dp).clickable(onClick = settings), color = MaterialTheme.colorScheme.onErrorContainer, fontWeight = FontWeight.Bold) } }
@Composable private fun RecallEmpty(title: String, body: String, action: String, click: () -> Unit) = Column(Modifier.padding(20.dp)) { PerClipEmptyState(title, body); Button(onClick = click, Modifier.padding(top = 12.dp)) { Text(action) } }

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun RecallOriginalSheet(settings: PerClipSettings, strategy: RecallOriginalStrategy.SafeRemoteSheet, dismiss: () -> Unit) { val controller = remember { RecallController() }; var clip by remember(strategy.target.serverClipId) { mutableStateOf(strategy.loadedClip) }; var failed by remember(strategy.target.serverClipId) { mutableStateOf(false) }; val uriHandler = LocalUriHandler.current; LaunchedEffect(strategy.target.serverClipId) { if (clip == null && strategy.target.serverClipId.isNotBlank()) controller.clip(settings, strategy.target.serverClipId).let { if (it.ok) clip = it.value else failed = true } }; ModalBottomSheet(onDismissRequest = dismiss) { LazyColumn(Modifier.fillMaxWidth().padding(horizontal = 20.dp), contentPadding = PaddingValues(bottom = 28.dp)) { item { Text(clip?.title ?: "原文", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold); Text(clip?.summary ?: if (failed) "暂时无法加载安全原文。" else "正在加载…", Modifier.padding(top = 8.dp)); if (clip?.safeText?.isNotBlank() == true) Text(clip!!.safeText, Modifier.padding(top = 12.dp)) }; clip?.tags?.take(3)?.let { tags -> item { Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) { tags.forEach { PerClipBadge(it, PerClipStatusTone.Neutral) } } } }; clip?.filename?.takeIf(String::isNotBlank)?.let { file -> item { Text(file, Modifier.padding(top = 12.dp), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) } }; clip?.url?.takeIf { it.startsWith("https://") || it.startsWith("http://") }?.let { url -> item { Text("在浏览器中打开", Modifier.padding(vertical = 16.dp).clickable { runCatching { uriHandler.openUri(url) } }, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold) } } } } }
private fun String.needsSettingsAction(): Boolean =
    contains("服务端") || contains("认证") || contains("token", ignoreCase = true) || contains("API", ignoreCase = true)

/** A measured label candidate, kept pure so the fit bounds have unit-test coverage. */
internal data class TopicLabelMeasure(val width: Float, val height: Float)

/** Finds the largest label size inside the central safe chord of a topic circle. */
internal fun fitTopicLabelFontSize(radius: Float, measure: (Float) -> TopicLabelMeasure): Float {
    val safeWidth = radius * 1.42f
    val safeHeight = radius * .78f
    var low = 8f
    var high = radius * .94f
    repeat(12) {
        val candidate = (low + high) / 2f
        val measured = measure(candidate)
        if (measured.width <= safeWidth && measured.height <= safeHeight) low = candidate else high = candidate
    }
    return low
}

/** Fits the actual final Paint/typeface through the same testable search. */
private fun fitTopicLabelFontSize(paint: Paint, label: String, radius: Float): Float =
    fitTopicLabelFontSize(radius) { candidate ->
        paint.textSize = candidate
        val metrics = paint.fontMetrics
        TopicLabelMeasure(paint.measureText(label), metrics.descent - metrics.ascent)
    }
