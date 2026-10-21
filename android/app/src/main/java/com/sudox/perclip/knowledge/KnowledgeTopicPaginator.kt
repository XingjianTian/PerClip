package com.sudox.perclip.knowledge

import com.sudox.perclip.capabilities.capabilityConfigurationFingerprint
import com.sudox.perclip.config.PerClipSettings
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

data class KnowledgeTopicPaginationState(
    val cacheKey: String = "",
    val knowledgeBaseIds: List<String> = emptyList(),
    val items: List<KnowledgeTopicClip> = emptyList(),
    val nextCursorByKnowledgeBase: Map<String, String> = emptyMap(),
    val completedKnowledgeBaseIds: Set<String> = emptySet(),
    val failuresByKnowledgeBase: Map<String, String> = emptyMap(),
    val capped: Boolean = false,
    val loading: Boolean = false,
)

/**
 * Exhausts each Knowledge Base cursor independently. A failed library keeps
 * all successful pages and can resume from its own cursor on retry.
 */
class KnowledgeTopicPaginator(
    private val fetch: suspend (
        PerClipSettings,
        String,
        String,
        Int,
    ) -> KnowledgeBaseApiResult<KnowledgeTopicPage>,
) {
    suspend fun load(
        settings: PerClipSettings,
        knowledgeBaseIds: List<String>,
        previous: KnowledgeTopicPaginationState = KnowledgeTopicPaginationState(),
        cap: Int = UI_ITEM_CAP,
    ): KnowledgeTopicPaginationState {
        val targets = knowledgeBaseIds.distinct()
        val cacheKey = KnowledgeRemoteCacheKey.create(settings, targets)
        val seed = if (
            previous.cacheKey == cacheKey &&
            previous.knowledgeBaseIds.toSet() == targets.toSet()
        ) {
            previous
        } else {
            KnowledgeTopicPaginationState(
                cacheKey = cacheKey,
                knowledgeBaseIds = targets,
            )
        }
        val byId = seed.items.associateByTo(linkedMapOf()) { it.clipId }
        val cursors = seed.nextCursorByKnowledgeBase.toMutableMap()
        val completed = seed.completedKnowledgeBaseIds.toMutableSet()
        val failures = mutableMapOf<String, String>()
        var capped = seed.capped || byId.size >= cap

        for (knowledgeBaseId in targets) {
            if (capped || knowledgeBaseId in completed) continue
            var cursor = cursors[knowledgeBaseId].orEmpty()
            while (!capped) {
                val result = fetch(
                    settings,
                    knowledgeBaseId,
                    cursor,
                    minOf(PAGE_SIZE, cap - byId.size),
                )
                val page = result.value
                if (!result.ok || page == null) {
                    failures[knowledgeBaseId] = result.message.ifBlank { "加载失败，请重试。" }
                    break
                }
                page.items.forEach { item -> byId.putIfAbsent(item.clipId, item) }
                val next = page.nextCursor
                if (next.isBlank()) {
                    cursors.remove(knowledgeBaseId)
                    completed += knowledgeBaseId
                    break
                }
                cursors[knowledgeBaseId] = next
                cursor = next
                capped = byId.size >= cap
            }
        }
        return KnowledgeTopicPaginationState(
            cacheKey = cacheKey,
            knowledgeBaseIds = targets,
            items = byId.values.sortedWith(
                compareByDescending<KnowledgeTopicClip> { it.capturedAt.toSortableInstant() }
                    .thenBy { it.clipId },
            ),
            nextCursorByKnowledgeBase = cursors,
            completedKnowledgeBaseIds = completed,
            failuresByKnowledgeBase = failures,
            capped = capped,
            loading = false,
        )
    }

    private fun String.toSortableInstant(): Instant =
        runCatching { Instant.parse(this) }.getOrDefault(Instant.EPOCH)

    companion object {
        const val PAGE_SIZE = 100
        const val UI_ITEM_CAP = 500

        fun network(api: KnowledgeBaseApi = KnowledgeBaseApi()) = KnowledgeTopicPaginator {
                settings,
                knowledgeBaseId,
                cursor,
                limit,
            ->
            withContext(Dispatchers.IO) {
                api.listTopicClips(settings, knowledgeBaseId, cursor, limit)
            }
        }
    }
}

/** Contains only irreversible connection identity plus the selected KB set. */
object KnowledgeRemoteCacheKey {
    fun create(settings: PerClipSettings, knowledgeBaseIds: List<String>): String {
        val ids = knowledgeBaseIds.distinct().sorted().joinToString("\u0000")
        return capabilityConfigurationFingerprint(settings) + "|" + ids
    }
}

object KnowledgeRemoteCacheVisibility {
    fun pagination(
        requestKey: String,
        knowledgeBaseIds: List<String>,
        state: KnowledgeTopicPaginationState,
    ): KnowledgeTopicPaginationState =
        state.takeIf { it.cacheKey == requestKey }
            ?: KnowledgeTopicPaginationState(
                cacheKey = requestKey,
                knowledgeBaseIds = knowledgeBaseIds,
            )

}

data class KnowledgeTopicRegistryState(
    val configuration: String = "",
    val registry: TopicRegistry = TopicRegistry(emptyList()),
    val loaded: Boolean = false,
    val error: String = "",
)

object KnowledgeTopicRegistryPolicy {
    fun shouldLoad(
        settingsConfigured: Boolean,
        topicReadAvailable: Boolean,
        mode: KnowledgeReadMode,
    ): Boolean = settingsConfigured && topicReadAvailable &&
        (mode == KnowledgeReadMode.V2_LOCAL_FIRST || mode == KnowledgeReadMode.LEGACY_QUALITY_READ)
}

/** Process-local last-good registry cache isolated by service configuration. */
class KnowledgeTopicRegistryCoordinator(
    private val fetch: suspend (PerClipSettings) -> KnowledgeBaseApiResult<TopicRegistry>,
) {
    private val lock = Mutex()
    private val cached = LinkedHashMap<String, KnowledgeTopicRegistryState>(4, 0.75f, true)
    private var activeConfiguration = ""
    private var generation = 0L

    suspend fun load(
        settings: PerClipSettings,
        configuration: String,
        force: Boolean = false,
    ): KnowledgeTopicRegistryState {
        val request = lock.withLock {
            if (activeConfiguration != configuration) {
                activeConfiguration = configuration
                generation += 1
            }
            val existing = cached[configuration]
            if (!force && existing?.loaded == true) return existing
            RegistryRequest(configuration, ++generation)
        }
        val result = fetch(settings)
        return lock.withLock {
            if (request.configuration != activeConfiguration || request.generation != generation) {
                return@withLock visibleState(activeConfiguration)
            }
            val previous = cached[configuration]
            val next = if (result.ok && result.value != null) {
                KnowledgeTopicRegistryState(configuration, result.value, loaded = true)
            } else {
                KnowledgeTopicRegistryState(
                    configuration = configuration,
                    registry = previous?.registry ?: TopicRegistry(emptyList()),
                    loaded = previous?.loaded == true,
                    error = result.message.ifBlank { "主题列表暂不可用" },
                )
            }
            cached[configuration] = next
            while (cached.size > MAX_CONFIGURATIONS) cached.remove(cached.keys.first())
            next
        }
    }

    suspend fun deactivate(configuration: String): KnowledgeTopicRegistryState = lock.withLock {
        activeConfiguration = configuration
        generation += 1
        KnowledgeTopicRegistryState(configuration = configuration)
    }

    private fun visibleState(configuration: String): KnowledgeTopicRegistryState =
        cached[configuration] ?: KnowledgeTopicRegistryState(configuration = configuration)

    private data class RegistryRequest(val configuration: String, val generation: Long)

    companion object {
        private const val MAX_CONFIGURATIONS = 4

        fun network(api: KnowledgeBaseApi = KnowledgeBaseApi()) =
            KnowledgeTopicRegistryCoordinator { settings ->
                withContext(Dispatchers.IO) { api.topicRegistry(settings) }
            }
    }
}

object KnowledgeRemoteSearch {
    fun filter(items: List<KnowledgeTopicClip>, query: String): List<KnowledgeTopicClip> {
        val normalized = query.trim()
        if (normalized.isEmpty()) return items
        return items.filter { item ->
            listOf(item.title, item.summary, item.source)
                .any { it.contains(normalized, ignoreCase = true) }
        }
    }

    fun loadedLabel(state: KnowledgeTopicPaginationState): String =
        if (state.capped) {
            "已加载至上限 · ${state.items.size} 条"
        } else {
            "已加载 ${state.items.size} 条"
        }

    fun matchLabel(query: String, matchingCount: Int): String =
        if (query.isBlank()) "" else "当前匹配 $matchingCount 条"
}
