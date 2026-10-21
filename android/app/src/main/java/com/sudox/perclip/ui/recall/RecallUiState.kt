package com.sudox.perclip.ui.recall

import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.mapSaver
import com.sudox.perclip.recall.RecallEventAction
import com.sudox.perclip.recall.RecallEventResponse
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallProgress
import com.sudox.perclip.recall.RecallSessionResponse
import com.sudox.perclip.recall.RecallTopicDetail
import com.sudox.perclip.recall.RecallTopicFilter
import com.sudox.perclip.recall.RecallWeeklyReview
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallResurfacePage
import com.sudox.perclip.recall.repository.MemoryPlanet
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.recall.repository.RecallSuppressionPage
import com.sudox.perclip.recall.repository.MemoryPlanetWindow
import com.sudox.perclip.capabilities.AppFeatureAvailability

object RecallCustomRangePolicy {
    fun available(memoryPlanetAvailability: AppFeatureAvailability) =
        memoryPlanetAvailability == AppFeatureAvailability.AVAILABLE
}

enum class RecallPlanetSource {
    DEDICATED,
    FALLBACK,
}

data class RecallHomeRequestKey(
    val configurationFingerprint: String,
    val period: RecallPeriod,
    val startDate: String,
    val endDate: String,
    val timezone: String,
    val knowledgeBaseId: String,
    val planetSource: RecallPlanetSource,
) {
    companion object {
        fun create(
            configurationFingerprint: String,
            period: RecallPeriod,
            window: MemoryPlanetWindow,
            knowledgeBaseId: String = window.knowledgeBaseId,
            planetSource: RecallPlanetSource = RecallPlanetSource.DEDICATED,
        ) =
            RecallHomeRequestKey(
                configurationFingerprint = configurationFingerprint,
                period = period,
                startDate = if (period == RecallPeriod.CUSTOM) window.startDate else "",
                endDate = if (period == RecallPeriod.CUSTOM) window.endDate else "",
                timezone = window.timezone,
                knowledgeBaseId = knowledgeBaseId,
                planetSource = planetSource,
            )
    }
}

object RecallPlanetSourcePolicy {
    fun forAvailability(availability: AppFeatureAvailability): RecallPlanetSource =
        if (availability == AppFeatureAvailability.AVAILABLE) {
            RecallPlanetSource.DEDICATED
        } else {
            RecallPlanetSource.FALLBACK
        }

    fun selectFailureValue(
        source: RecallPlanetSource,
        cached: MemoryPlanet?,
        freshFallback: MemoryPlanet?,
    ): MemoryPlanet? =
        if (source == RecallPlanetSource.FALLBACK) {
            freshFallback
        } else {
            cached ?: freshFallback
        }
}

data class RecallHomeRequest(
    val key: RecallHomeRequestKey,
    val domainGeneration: Long,
    val resurfaceGeneration: Long,
    val planetGeneration: Long,
)

enum class RecallPeriod(val days: Int?) {
    WEEKLY(7), MONTHLY(30), CUSTOM(null),
}

enum class RecallScope { ALL_TOPICS, ACTIVE_TOPIC }

data class RecallPresentationState(
    val activeTopicId: String = "",
    val pinnedTopicId: String = "",
    val knowledgeBaseId: String = "",
    val graphExpanded: Boolean = true,
    val autoSurfaceEnabled: Boolean = true,
    val period: RecallPeriod = RecallPeriod.WEEKLY,
    val scope: RecallScope = RecallScope.ALL_TOPICS,
    val userInteracting: Boolean = false,
    val lastInteractionAt: Long = 0L,
    val visibleTopicCount: Int = 5,
    val visibleMemoryLabels: Int = 5,
    val hiddenTopicIds: Set<String> = emptySet(),
    val reducedMotion: Boolean = false,
    val customStartDate: String = "",
    val customEndDate: String = "",
    val customTimezone: String = "",
)

/** The four Recall surfaces intentionally live in one local state machine. */
sealed interface RecallDestination {
    data object Overview : RecallDestination
    data object DisplaySettings : RecallDestination
    data class Topic(val topicId: String) : RecallDestination
    data class Session(val sessionId: String?) : RecallDestination
    data object Weekly : RecallDestination
}

data class RecallResource<T>(
    val value: T? = null,
    val loading: Boolean = false,
    val error: String = "",
) {
    val isEmpty get() = value == null && !loading && error.isBlank()
}

data class RecallOriginalTarget(val serverClipId: String, val clientRequestId: String = "")
data class RecallOriginalResolve(val generation: Long, val destination: RecallDestination)

sealed interface RecallOriginalStrategy {
    data class LocalDetail(val localClipId: String) : RecallOriginalStrategy
    data class SafeRemoteSheet(val target: RecallOriginalTarget, val loadedClip: com.sudox.perclip.recall.RecallClip? = null) : RecallOriginalStrategy
}

data class RecallUiState(
    val destination: RecallDestination = RecallDestination.Overview,
    val overview: RecallResource<RecallOverview> = RecallResource(),
    val topic: RecallResource<RecallTopicDetail> = RecallResource(),
    val weekly: RecallResource<RecallWeeklyReview> = RecallResource(),
    val session: RecallResource<RecallSessionResponse> = RecallResource(),
    val topicFilter: RecallTopicFilter = RecallTopicFilter.ALL,
    val revealedItemId: String = "",
    val revealedText: String = "",
    val actionInFlight: Boolean = false,
    val pendingOriginal: RecallOriginalStrategy? = null,
    val domain: RecallResource<RecallDomainSnapshot> = RecallResource(),
    val resurfaced: RecallResource<RecallResurfacePage> = RecallResource(),
    val memoryPlanet: RecallResource<MemoryPlanet> = RecallResource(),
    val suppressed: RecallResource<RecallSuppressionPage> = RecallResource(value = RecallSuppressionPage()),
    val notice: String = "",
    val presentation: RecallPresentationState = RecallPresentationState(),
) {
    val currentProgress: RecallProgress get() = session.value?.progress ?: RecallProgress()
}

/** Caller-owned Recall state and request generations; stale async work cannot rewrite a newer surface. */
@Stable
class RecallStateHolder(initial: RecallUiState = RecallUiState()) {
    var state by mutableStateOf(initial)
        private set

    private var overviewGeneration = 0L
    private var topicGeneration = 0L
    private var weeklyGeneration = 0L
    private var sessionGeneration = 0L
    private var actionGeneration = 0L
    private var originalGeneration = 0L
    private var domainGeneration = 0L
    private var resurfaceGeneration = 0L
    private var memoryPlanetGeneration = 0L
    private var suppressionGeneration = 0L
    private var configurationFingerprint = ""
    private var homeRequestKey: RecallHomeRequestKey? = null
    private val lastGoodPlanets = linkedMapOf<RecallHomeRequestKey, MemoryPlanet>()
    private var displayPreferencesInitialized = false

    fun update(transform: (RecallUiState) -> RecallUiState) { state = transform(state) }
    fun update(next: RecallUiState) { state = next }
    internal fun applyDisplayPreferencesOnce(preferences: RecallDisplayPreferences): Boolean {
        if (displayPreferencesInitialized) return false
        update { RecallUiReducer.applyDisplayPreferences(it, preferences) }
        displayPreferencesInitialized = true
        return true
    }
    fun beginOverview() = ++overviewGeneration
    fun beginTopic() = ++topicGeneration
    fun beginWeekly() = ++weeklyGeneration
    fun beginSession() = ++sessionGeneration
    fun beginAction() = ++actionGeneration
    fun beginOriginal() = ++originalGeneration
    fun beginDomain() = ++domainGeneration
    fun beginResurface() = ++resurfaceGeneration
    fun beginMemoryPlanet() = ++memoryPlanetGeneration
    fun beginSuppressions() = ++suppressionGeneration
    fun beginHomeRequest(key: RecallHomeRequestKey): RecallHomeRequest {
        homeRequestKey = key
        val cached = lastGoodPlanets[key]
        update {
            it.copy(
                domain = RecallResource(loading = true),
                resurfaced = RecallResource(loading = true),
                memoryPlanet = RecallResource(value = cached, loading = true),
                notice = "",
            )
        }
        return RecallHomeRequest(key, ++domainGeneration, ++resurfaceGeneration, ++memoryPlanetGeneration)
    }
    fun isHomeRequestCurrent(request: RecallHomeRequest) =
        request.key == homeRequestKey &&
            isDomainCurrent(request.domainGeneration) &&
            isResurfaceCurrent(request.resurfaceGeneration) &&
            isMemoryPlanetCurrent(request.planetGeneration)
    fun cachedPlanet(key: RecallHomeRequestKey) = lastGoodPlanets[key]
    fun rememberPlanet(key: RecallHomeRequestKey, value: MemoryPlanet) {
        lastGoodPlanets[key] = value
        while (lastGoodPlanets.size > 4) lastGoodPlanets.remove(lastGoodPlanets.keys.first())
    }
    fun beginOriginalResolve() = RecallOriginalResolve(++originalGeneration, state.destination)
    fun isOverviewCurrent(generation: Long) = generation == overviewGeneration
    fun isTopicCurrent(generation: Long) = generation == topicGeneration
    fun isWeeklyCurrent(generation: Long) = generation == weeklyGeneration
    fun isSessionCurrent(generation: Long) = generation == sessionGeneration
    fun isActionCurrent(generation: Long) = generation == actionGeneration
    fun isOriginalCurrent(generation: Long) = generation == originalGeneration
    fun isDomainCurrent(generation: Long) = generation == domainGeneration
    fun isResurfaceCurrent(generation: Long) = generation == resurfaceGeneration
    fun isMemoryPlanetCurrent(generation: Long) = generation == memoryPlanetGeneration
    fun isSuppressionsCurrent(generation: Long) = generation == suppressionGeneration
    fun isOriginalResolveCurrent(request: RecallOriginalResolve) =
        request.generation == originalGeneration && request.destination == state.destination
    fun invalidateOriginal() { ++originalGeneration }
    fun prepareOverviewForConfiguration(fingerprint: String): Boolean {
        if (fingerprint == configurationFingerprint) return false
        if (configurationFingerprint.isBlank() && (state.domain.value != null || state.overview.value != null)) {
            configurationFingerprint = fingerprint
            return false
        }
        configurationFingerprint = fingerprint
        homeRequestKey = null
        lastGoodPlanets.clear()
        ++overviewGeneration
        ++domainGeneration
        ++resurfaceGeneration
        ++memoryPlanetGeneration
        ++suppressionGeneration
        update { it.copy(overview = RecallResource(), domain = RecallResource(), resurfaced = RecallResource(), memoryPlanet = RecallResource(), suppressed = RecallResource(value = RecallSuppressionPage())) }
        return true
    }
    fun navigate(destination: RecallDestination) {
        invalidateOriginal()
        update { RecallUiReducer.navigate(it, destination) }
    }
    fun dismissOriginal() {
        invalidateOriginal()
        update(RecallUiReducer::dismissOriginal)
    }
    fun back(): Boolean {
        val target = RecallUiReducer.back(state) ?: return false
        invalidateOriginal()
        update(target)
        return true
    }
}

internal val RecallStateHolderSaver = mapSaver(
    save = { holder ->
        val presentation = holder.state.presentation
        mapOf(
            "activeTopicId" to presentation.activeTopicId,
            "pinnedTopicId" to presentation.pinnedTopicId,
            "knowledgeBaseId" to presentation.knowledgeBaseId,
            "scope" to presentation.scope.name,
            "lastInteractionAt" to presentation.lastInteractionAt,
        )
    },
    restore = { saved ->
        val scope = runCatching {
            RecallScope.valueOf(saved["scope"] as String)
        }.getOrDefault(RecallScope.ALL_TOPICS)
        RecallStateHolder(
            RecallUiState(
                presentation = RecallPresentationState(
                    activeTopicId = saved["activeTopicId"] as String,
                    pinnedTopicId = saved["pinnedTopicId"] as String,
                    knowledgeBaseId = saved["knowledgeBaseId"] as? String ?: "",
                    scope = scope,
                    lastInteractionAt = saved["lastInteractionAt"] as Long,
                ),
            ),
        )
    },
)

object RecallUiReducer {
    fun navigate(state: RecallUiState, destination: RecallDestination) = state.copy(destination = destination, pendingOriginal = null)

    /** Returns true only when Recall consumed the back press. */
    fun back(state: RecallUiState): RecallUiState? = when (state.destination) {
        RecallDestination.Overview -> null
        RecallDestination.DisplaySettings, is RecallDestination.Topic, is RecallDestination.Session, RecallDestination.Weekly -> state.copy(destination = RecallDestination.Overview, pendingOriginal = null)
    }

    fun overviewLoading(state: RecallUiState) = state.copy(overview = state.overview.copy(loading = true, error = ""))
    fun overviewLoaded(state: RecallUiState, value: RecallOverview) = state.copy(overview = RecallResource(value = value))
    fun overviewFailed(state: RecallUiState, message: String) = state.copy(overview = state.overview.copy(loading = false, error = message))

    fun homeLoading(state: RecallUiState) = state.copy(
        domain = state.domain.copy(loading = true, error = ""),
        resurfaced = state.resurfaced.copy(loading = true, error = ""),
        memoryPlanet = state.memoryPlanet.copy(loading = true, error = ""),
        suppressed = state.suppressed.copy(loading = true, error = ""),
    )

    fun domainLoaded(state: RecallUiState, value: RecallDomainSnapshot): RecallUiState {
        val topics = value.topics
        val restoredActive = state.presentation.activeTopicId
        val active = restoredActive.ifBlank { topics.firstOrNull()?.id.orEmpty() }
        val loaded = state.copy(
            domain = RecallResource(value = value),
            presentation = state.presentation.copy(activeTopicId = active),
        )
        return if (restoredActive.isNotBlank() && state.memoryPlanet.loading) loaded else ensureVisibleActiveTopic(loaded)
    }

    fun domainFailed(state: RecallUiState, message: String) = state.copy(domain = state.domain.copy(loading = false, error = message))
    fun resurfacedLoaded(state: RecallUiState, value: RecallResurfacePage) = state.copy(resurfaced = RecallResource(value = value))
    fun resurfacedFailed(state: RecallUiState, message: String) = state.copy(resurfaced = state.resurfaced.copy(loading = false, error = message))
    fun memoryPlanetLoaded(state: RecallUiState, value: MemoryPlanet) = ensureVisibleActiveTopic(
        state.copy(memoryPlanet = RecallResource(value = value)),
    )
    fun memoryPlanetFailed(state: RecallUiState, message: String) = state.copy(memoryPlanet = state.memoryPlanet.copy(loading = false, error = message))
    fun notice(state: RecallUiState, message: String) = state.copy(notice = message)
    fun noticeShown(state: RecallUiState) = state.copy(notice = "")
    fun suppressionsLoaded(state: RecallUiState, value: RecallSuppressionPage) =
        state.copy(suppressed = RecallResource(value = value))
    fun suppressionPageLoaded(state: RecallUiState, value: RecallSuppressionPage) =
        state.copy(suppressed = RecallResource(value = value))
    fun suppressionsFailed(state: RecallUiState, message: String) =
        state.copy(suppressed = state.suppressed.copy(loading = false, error = message))
    fun suppressionRestored(state: RecallUiState, clipId: String): RecallUiState {
        val page = state.suppressed.value ?: return state
        return state.copy(
            suppressed = RecallResource(value = page.copy(items = page.items.filterNot { it.clipId == clipId })),
        )
    }

    fun selectTopic(state: RecallUiState, topicId: String, now: Long) = state.copy(
        presentation = state.presentation.copy(
            activeTopicId = topicId,
            pinnedTopicId = topicId,
            userInteracting = true,
            lastInteractionAt = now,
        ),
    )

    fun setKnowledgeBase(state: RecallUiState, knowledgeBaseId: String, now: Long) = state.copy(
        presentation = state.presentation.copy(
            knowledgeBaseId = knowledgeBaseId,
            activeTopicId = "",
            pinnedTopicId = "",
            scope = RecallScope.ALL_TOPICS,
            userInteracting = true,
            lastInteractionAt = now,
        ),
    )

    fun rotateTopic(state: RecallUiState): RecallUiState {
        val topics = recallVisibleTopics(state)
        if (topics.size < 2) return state
        val current = topics.indexOfFirst { it.id == state.presentation.activeTopicId }.coerceAtLeast(0)
        return state.copy(presentation = state.presentation.copy(activeTopicId = topics[(current + 1) % topics.size].id, userInteracting = false))
    }

    fun markInteraction(state: RecallUiState, now: Long) = state.copy(
        presentation = state.presentation.copy(userInteracting = true, lastInteractionAt = now),
    )

    fun setGraphExpanded(state: RecallUiState, expanded: Boolean, now: Long) = state.copy(
        presentation = state.presentation.copy(graphExpanded = expanded, userInteracting = true, lastInteractionAt = now),
    )

    fun setPeriod(state: RecallUiState, period: RecallPeriod, now: Long) = state.copy(
        presentation = state.presentation.copy(period = period, userInteracting = true, lastInteractionAt = now),
    )

    fun setCustomRange(
        state: RecallUiState,
        startDate: String,
        endDate: String,
        timezone: String,
        now: Long,
    ) = state.copy(
        presentation = state.presentation.copy(
            period = RecallPeriod.CUSTOM,
            customStartDate = startDate,
            customEndDate = endDate,
            customTimezone = timezone,
            userInteracting = true,
            lastInteractionAt = now,
        ),
    )

    fun setScope(state: RecallUiState, scope: RecallScope, now: Long) = state.copy(
        presentation = state.presentation.copy(
            scope = scope,
            pinnedTopicId = if (scope == RecallScope.ACTIVE_TOPIC) state.presentation.activeTopicId else state.presentation.pinnedTopicId,
            userInteracting = true,
            lastInteractionAt = now,
        ),
    )

    fun setReducedMotion(state: RecallUiState, reduced: Boolean) = state.copy(
        presentation = state.presentation.copy(reducedMotion = reduced),
    )

    internal fun applyDisplayPreferences(state: RecallUiState, preferences: RecallDisplayPreferences): RecallUiState {
        val next = state.presentation.copy(
            visibleTopicCount = preferences.visibleTopicCount.coerceIn(1, 5),
            visibleMemoryLabels = preferences.visibleMemoryLabels.coerceIn(1, 5),
            hiddenTopicIds = preferences.hiddenTopicIds,
        )
        return ensureVisibleActiveTopic(state.copy(presentation = next))
    }

    fun setVisibleTopicCount(state: RecallUiState, count: Int): RecallUiState = ensureVisibleActiveTopic(
        state.copy(presentation = state.presentation.copy(visibleTopicCount = count.coerceIn(1, 5))),
    )

    fun setVisibleMemoryLabels(state: RecallUiState, count: Int): RecallUiState = state.copy(
        presentation = state.presentation.copy(visibleMemoryLabels = count.coerceIn(1, 5)),
    )

    fun setTopicVisible(state: RecallUiState, topicId: String, visible: Boolean): RecallUiState {
        val topicIds = state.domain.value?.topics.orEmpty().map { it.id }.toSet()
        if (topicId !in topicIds) return state
        val currentlyVisible = topicIds - state.presentation.hiddenTopicIds
        if (!visible && topicId in currentlyVisible && currentlyVisible.size <= 1) return state
        val hidden = if (visible) state.presentation.hiddenTopicIds - topicId else state.presentation.hiddenTopicIds + topicId
        return ensureVisibleActiveTopic(state.copy(presentation = state.presentation.copy(hiddenTopicIds = hidden)))
    }

    fun restoreDisplayDefaults(state: RecallUiState): RecallUiState = ensureVisibleActiveTopic(
        state.copy(
            presentation = state.presentation.copy(
                visibleTopicCount = 5,
                visibleMemoryLabels = 5,
                hiddenTopicIds = emptySet(),
            ),
        ),
    )

    private fun ensureVisibleActiveTopic(state: RecallUiState): RecallUiState {
        val visible = recallVisibleTopics(state)
        val active = state.presentation.activeTopicId.takeIf { id -> visible.any { it.id == id } }
            ?: visible.firstOrNull()?.id.orEmpty()
        return state.copy(presentation = state.presentation.copy(activeTopicId = active))
    }

    fun topicLoading(state: RecallUiState, filter: RecallTopicFilter = state.topicFilter) = state.copy(topicFilter = filter, topic = state.topic.copy(loading = true, error = ""))
    fun topicLoaded(state: RecallUiState, value: RecallTopicDetail) = state.copy(topic = RecallResource(value = value))
    fun topicFailed(state: RecallUiState, message: String) = state.copy(topic = state.topic.copy(loading = false, error = message))

    fun weeklyLoading(state: RecallUiState) = state.copy(weekly = state.weekly.copy(loading = true, error = ""))
    fun weeklyLoaded(state: RecallUiState, value: RecallWeeklyReview) = state.copy(weekly = RecallResource(value = value))
    fun weeklyFailed(state: RecallUiState, message: String) = state.copy(weekly = state.weekly.copy(loading = false, error = message))

    fun sessionLoading(state: RecallUiState) = state.copy(session = state.session.copy(loading = true, error = ""), actionInFlight = false)
    fun sessionLoaded(state: RecallUiState, value: RecallSessionResponse) = state.copy(session = RecallResource(value = value), actionInFlight = false)
    fun sessionFailed(state: RecallUiState, message: String) = state.copy(session = state.session.copy(loading = false, error = message), actionInFlight = false)
    fun actionStarted(state: RecallUiState) = if (state.actionInFlight) state else state.copy(actionInFlight = true)

    /** Reveal changes only the reveal presentation; it deliberately cannot advance progress. */
    fun actionApplied(state: RecallUiState, action: RecallEventAction, response: RecallEventResponse): RecallUiState = when (action) {
        RecallEventAction.REVEAL -> state.copy(
            actionInFlight = false,
            revealedItemId = response.item.id,
            revealedText = response.revealText,
        )
        RecallEventAction.OPEN_ORIGINAL -> state.copy(actionInFlight = false)
        RecallEventAction.REMEMBERED, RecallEventAction.LATER -> {
            val previous = state.session.value
            val mergedItems = mergeSessionItems(previous?.items.orEmpty(), response.item, response.currentItem)
            state.copy(
                actionInFlight = false,
                session = RecallResource(value = RecallSessionResponse(response.session, mergedItems, response.currentItem, response.progress)),
                revealedItemId = "",
                revealedText = "",
            )
        }
    }

    /** Retains snapshot order while applying the acted item before the next server item. */
    private fun mergeSessionItems(
        previous: List<com.sudox.perclip.recall.RecallSessionItem>,
        acted: com.sudox.perclip.recall.RecallSessionItem,
        current: com.sudox.perclip.recall.RecallSessionItem?,
    ): List<com.sudox.perclip.recall.RecallSessionItem> = listOfNotNull(acted, current).fold(previous) { items, replacement ->
        val index = items.indexOfFirst { it.id == replacement.id }
        when {
            index >= 0 -> items.toMutableList().also { it[index] = replacement }
            replacement.position > 0 -> items.toMutableList().also { mutable ->
                val insertion = mutable.indexOfFirst { it.position > replacement.position }
                if (insertion >= 0) mutable.add(insertion, replacement) else mutable += replacement
            }
            else -> items + replacement
        }
    }

    fun actionFailed(state: RecallUiState, message: String) = state.copy(actionInFlight = false, session = state.session.copy(error = message))
    fun showOriginal(state: RecallUiState, strategy: RecallOriginalStrategy) = state.copy(pendingOriginal = strategy)
    fun dismissOriginal(state: RecallUiState) = state.copy(pendingOriginal = null)

    fun localClipId(clientRequestId: String, localClipIds: Set<String>): String? = localClipIds
        .sortedByDescending { it.length }
        .firstOrNull { localId -> clientRequestId == localId || clientRequestId.startsWith("$localId:") }

    fun originalStrategy(target: RecallOriginalTarget, localClipIds: Set<String>): RecallOriginalStrategy =
        localClipId(target.clientRequestId, localClipIds)?.let(RecallOriginalStrategy::LocalDetail)
            ?: RecallOriginalStrategy.SafeRemoteSheet(target)

    fun graphTapTarget(node: RecallGraphNodeLayout): RecallGraphTapTarget =
        if (node.type.equals("clip", true) || node.clipId.isNotBlank()) RecallGraphTapTarget.Original(RecallOriginalTarget(node.clipId))
        else RecallGraphTapTarget.Topic(node.topicId)

    fun progressLabel(progress: RecallProgress): String = "${progress.completed.coerceAtLeast(0)} / ${progress.total.coerceAtLeast(0)}"
}

object RecallOverviewLoadPolicy {
    fun shouldLoad(state: RecallUiState): Boolean =
        state.destination == RecallDestination.Overview && state.overview.isEmpty

    fun requestIfNeeded(state: RecallUiState, request: () -> Unit): Boolean {
        if (!shouldLoad(state)) return false
        request()
        return true
    }
}

object RecallHomeLoadPolicy {
    fun shouldLoad(state: RecallUiState): Boolean =
        state.destination == RecallDestination.Overview &&
            state.domain.isEmpty &&
            state.resurfaced.isEmpty &&
            state.memoryPlanet.isEmpty
}

sealed interface RecallGraphTapTarget {
    data class Topic(val topicId: String) : RecallGraphTapTarget
    data class Original(val target: RecallOriginalTarget) : RecallGraphTapTarget
}

/** UTC strings from the contract are deliberately rendered without device-locale parsing failures. */
fun recallRelativeDate(value: String, nowEpochMillis: Long = System.currentTimeMillis()): String {
    if (value.isBlank()) return ""
    val instant = runCatching { java.time.Instant.parse(value) }.getOrNull() ?: return value.take(10)
    val days = java.time.Duration.between(instant, java.time.Instant.ofEpochMilli(nowEpochMillis)).toDays()
    return when {
        days <= 0 -> "今天"
        days == 1L -> "昨天"
        days in 2..6 -> "$days 天前"
        else -> instant.atZone(java.time.ZoneId.systemDefault()).toLocalDate().toString()
    }
}
