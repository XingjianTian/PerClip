package com.sudox.perclip.knowledge

import com.sudox.perclip.config.PerClipSettings
import java.util.LinkedHashMap
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

interface KnowledgeListRemote {
    fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage>
    fun summary(settings: PerClipSettings, query: KnowledgeListQuery): KnowledgeBaseApiResult<KnowledgeListSummary>
    fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage>
}

class KnowledgeListApiRemote(private val api: KnowledgeBaseApi = KnowledgeBaseApi()) : KnowledgeListRemote {
    override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
        api.listKnowledgeV2(settings, query, cursor, limit)
    override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) = api.knowledgeSummary(settings, query)
    override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
        api.knowledgeChanges(settings, afterRevision, limit)
}

/** Owns v2 cache/network ordering. UI receives immutable snapshots only. */
class KnowledgeRepository(
    private val cache: KnowledgeMemoryCacheStore,
    private val remote: KnowledgeListRemote = KnowledgeListApiRemote(),
) {
    private val queryLocks = ConcurrentHashMap<String, Mutex>()
    private val changeLocks = ConcurrentHashMap<String, Mutex>()
    private val generation = AtomicLong(0)
    private val pendingLock = Mutex()
    private val pendingHeads = LinkedHashMap<PendingKey, KnowledgeListPage>(16, 0.75f, true)

    suspend fun cached(
        configuration: String,
        query: KnowledgeListQuery,
        mode: KnowledgeReadMode,
    ): KnowledgeRepositoryState = withContext(Dispatchers.IO) {
        val current = generation.incrementAndGet()
        val syncError = cache.syncError(configuration)
        KnowledgeRepositoryState(
            mode = mode,
            snapshot = cache.load(configuration, query),
            partialSyncFailure = syncError.isNotBlank(),
            syncError = syncError,
            generation = current,
        )
    }

    suspend fun synchronize(
        settings: PerClipSettings,
        configuration: String,
        query: KnowledgeListQuery,
        mode: KnowledgeReadMode,
        forceHead: Boolean = false,
    ): KnowledgeRepositoryState = withContext(Dispatchers.IO) {
        val normalized = query.normalized()
        val requestGeneration = generation.get()
        if (mode != KnowledgeReadMode.V2_LOCAL_FIRST) {
            return@withContext KnowledgeRepositoryState(
                mode, cache.load(configuration, normalized), generation = requestGeneration,
            )
        }
        val lock = queryLocks.getOrPut("$configuration:${normalized.key}") { Mutex() }
        lock.withLock {
            val before = cache.load(configuration, normalized)
            if (!before.initialized) {
                return@withLock synchronizeFirstPage(
                    settings, configuration, normalized, mode, requestGeneration,
                )
            }

            val summaryResult = remote.summary(settings, normalized)
            if (summaryResult.ok && summaryResult.value != null) {
                cache.saveSummary(configuration, normalized, summaryResult.value)
            }
            val changeError = consumeGlobalChanges(settings, configuration)
            val headResult = remote.list(settings, normalized, "", PAGE_SIZE)
            val headPage = headResult.value
            if (headResult.ok && headPage != null) {
                val known = before.items.mapTo(hashSetOf()) { it.clip.clipId }
                val newCount = headPage.items.count { it.clip.clipId !in known }
                if (requestGeneration != generation.get()) {
                    return@withLock stale(mode, configuration, normalized)
                }
                val pendingKey = PendingKey(configuration, normalized.key)
                if (forceHead || !normalized.baseQuery || newCount == 0) {
                    cache.savePage(configuration, normalized, headPage, append = false)
                    removePending(pendingKey)
                } else {
                    putPending(pendingKey, headPage)
                }

                val errors = failures(
                    summaryResult.takeUnless { it.ok }?.message,
                    changeError,
                )
                persistAttemptError(configuration, normalized, errors, changeError)
                val refreshed = cache.load(configuration, normalized)
                val stableSnapshot = if (!forceHead && normalized.baseQuery && newCount > 0) {
                    refreshed.copy(items = refreshed.items.filter { it.clip.clipId in known })
                } else {
                    refreshed
                }
                return@withLock KnowledgeRepositoryState(
                    mode = mode,
                    snapshot = stableSnapshot,
                    partialSyncFailure = errors.isNotBlank(),
                    syncError = errors,
                    newContentCount = if (forceHead || !normalized.baseQuery) 0 else newCount,
                    generation = requestGeneration,
                )
            }

            val errors = failures(
                headResult.message.ifBlank { "知识列表同步失败" },
                summaryResult.takeUnless { it.ok }?.message,
                changeError,
            )
            persistAttemptError(configuration, normalized, errors, changeError)
            val anySuccess = summaryResult.ok || changeError.isBlank()
            KnowledgeRepositoryState(
                mode = mode,
                snapshot = cache.load(configuration, normalized),
                offline = !anySuccess,
                partialSyncFailure = anySuccess,
                syncError = errors,
                generation = requestGeneration,
            )
        }
    }

    private suspend fun synchronizeFirstPage(
        settings: PerClipSettings,
        configuration: String,
        query: KnowledgeListQuery,
        mode: KnowledgeReadMode,
        requestGeneration: Long,
    ): KnowledgeRepositoryState {
        val (summaryResult, headResult) = coroutineScope {
            val summary = async { remote.summary(settings, query) }
            val head = async { remote.list(settings, query, "", PAGE_SIZE) }
            summary.await() to head.await()
        }
        if (summaryResult.ok && summaryResult.value != null) {
            cache.saveSummary(configuration, query, summaryResult.value)
        }
        val headPage = headResult.value
        if (headResult.ok && headPage != null) {
            cache.savePage(
                configuration, query, headPage, append = false,
                initialWatermark = headPage.summary.revision,
            )
            val changeError = consumeGlobalChanges(settings, configuration)
            if (requestGeneration != generation.get()) return stale(mode, configuration, query)
            val errors = failures(summaryResult.takeUnless { it.ok }?.message, changeError)
            persistAttemptError(configuration, query, errors, changeError)
            return KnowledgeRepositoryState(
                mode = mode,
                snapshot = cache.load(configuration, query),
                partialSyncFailure = errors.isNotBlank(),
                syncError = errors,
                generation = requestGeneration,
            )
        }
        val errors = failures(
            headResult.message.ifBlank { "知识列表同步失败" },
            summaryResult.takeUnless { it.ok }?.message,
        )
        cache.saveError(configuration, query.key, errors)
        return KnowledgeRepositoryState(
            mode = mode,
            snapshot = cache.load(configuration, query),
            offline = true,
            syncError = errors,
            generation = requestGeneration,
        )
    }

    suspend fun acceptNewContent(
        configuration: String,
        query: KnowledgeListQuery,
        mode: KnowledgeReadMode,
    ): KnowledgeRepositoryState = withContext(Dispatchers.IO) {
        val normalized = query.normalized()
        val pending = takePending(PendingKey(configuration, normalized.key))
        if (pending != null) cache.savePage(configuration, normalized, pending, append = false)
        KnowledgeRepositoryState(
            mode = mode,
            snapshot = cache.load(configuration, normalized),
            generation = generation.get(),
        )
    }

    suspend fun loadNext(
        settings: PerClipSettings,
        configuration: String,
        query: KnowledgeListQuery,
        mode: KnowledgeReadMode,
    ): KnowledgeRepositoryState = withContext(Dispatchers.IO) {
        val normalized = query.normalized()
        val requestGeneration = generation.get()
        val lock = queryLocks.getOrPut("$configuration:${normalized.key}") { Mutex() }
        lock.withLock {
            val before = cache.load(configuration, normalized)
            if (mode != KnowledgeReadMode.V2_LOCAL_FIRST || before.complete || before.nextCursor.isBlank()) {
                return@withLock KnowledgeRepositoryState(mode, before, generation = requestGeneration)
            }
            val requestedCursor = before.nextCursor
            val result = remote.list(settings, normalized, requestedCursor, PAGE_SIZE)
            val page = result.value
            val cursorProgress = page != null && (!page.hasMore || page.nextCursor.isNotBlank()) &&
                page.nextCursor != requestedCursor
            val success = result.ok && page != null && cursorProgress
            val error = when {
                !result.ok || page == null -> result.message.ifBlank { "下一页同步失败" }
                !cursorProgress -> "下一页游标未推进"
                else -> ""
            }
            if (success) {
                cache.savePage(configuration, normalized, page, append = true)
            } else {
                cache.saveError(configuration, normalized.key, error)
            }
            if (requestGeneration != generation.get()) return@withLock stale(mode, configuration, normalized)
            KnowledgeRepositoryState(
                mode = mode,
                snapshot = cache.load(configuration, normalized),
                partialSyncFailure = !success,
                syncError = error,
                pageLoadFailure = !success,
                generation = requestGeneration,
            )
        }
    }

    private suspend fun consumeGlobalChanges(settings: PerClipSettings, configuration: String): String {
        val lock = changeLocks.getOrPut(configuration) { Mutex() }
        return lock.withLock {
            var watermark = cache.watermark(configuration)
            repeat(MAX_CHANGE_PAGES) {
                currentCoroutineContext().ensureActive()
                val result = remote.changes(settings, watermark, CHANGE_PAGE_SIZE)
                val page = result.value
                if (!result.ok || page == null) {
                    val error = result.message.ifBlank { "全局变更同步失败" }
                    cache.saveSyncError(configuration, error)
                    return@withLock error
                }
                val shouldContinue = page.hasMore || page.currentRevision > page.nextRevision
                if (page.nextRevision < watermark || (shouldContinue && page.nextRevision <= watermark)) {
                    val error = "全局变更水位未推进"
                    cache.saveSyncError(configuration, error)
                    return@withLock error
                }
                cache.applyChanges(configuration, page)
                watermark = page.nextRevision
                if (!shouldContinue) return@withLock ""
            }
            val error = "全局变更超过最大页数 $MAX_CHANGE_PAGES"
            cache.saveSyncError(configuration, error)
            error
        }
    }

    private fun persistAttemptError(
        configuration: String,
        query: KnowledgeListQuery,
        error: String,
        changeError: String,
    ) {
        if (error.isNotBlank()) cache.saveError(configuration, query.key, error)
        if (changeError.isNotBlank()) cache.saveSyncError(configuration, changeError)
    }

    private suspend fun putPending(key: PendingKey, page: KnowledgeListPage) = pendingLock.withLock {
        pendingHeads.remove(key)
        pendingHeads[key] = page
        while (pendingHeads.size > MAX_PENDING_HEADS) {
            pendingHeads.remove(pendingHeads.entries.first().key)
        }
    }

    private suspend fun removePending(key: PendingKey) = pendingLock.withLock {
        pendingHeads.remove(key)
        Unit
    }

    private suspend fun takePending(key: PendingKey): KnowledgeListPage? = pendingLock.withLock {
        pendingHeads.remove(key)
    }

    internal suspend fun pendingCount(): Int = pendingLock.withLock { pendingHeads.size }

    private fun stale(mode: KnowledgeReadMode, configuration: String, query: KnowledgeListQuery) =
        KnowledgeRepositoryState(
            mode = mode,
            snapshot = cache.load(configuration, query),
            generation = generation.get(),
        )

    private fun failures(vararg values: String?): String = values
        .mapNotNull { it?.trim()?.takeIf(String::isNotBlank) }
        .distinct()
        .joinToString(" · ")

    companion object {
        const val PAGE_SIZE = 50
        const val PREFETCH_DISTANCE = 8
        const val CHANGE_PAGE_SIZE = 100
        const val SEARCH_DEBOUNCE_MS = 300L
        const val MAX_CHANGE_PAGES = 1_000
        const val MAX_PENDING_HEADS = 10
    }
}
