package com.sudox.perclip.knowledge

import com.sudox.perclip.config.PerClipSettings
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeTopicPaginatorTest {
    @Test
    fun registryPolicyAllowsConfiguredV2AndLegacyIncludingAllScopeButNeverLocalOnly() {
        assertTrue(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.V2_LOCAL_FIRST))
        assertTrue(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.LEGACY_QUALITY_READ))
        assertFalse(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.LOCAL_ONLY))
        assertFalse(KnowledgeTopicRegistryPolicy.shouldLoad(false, true, KnowledgeReadMode.V2_LOCAL_FIRST))
        assertFalse(KnowledgeTopicRegistryPolicy.shouldLoad(true, false, KnowledgeReadMode.V2_LOCAL_FIRST))
        // Registry ownership is configuration-only; an All-scope empty ID list is not an input.
        assertTrue(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.V2_LOCAL_FIRST))
    }

    @Test
    fun registryCoordinatorLoadsOncePerConfigurationAndAcceptsAuthoritativeEmpty() = runBlocking {
        var calls = 0
        val coordinator = KnowledgeTopicRegistryCoordinator {
            calls += 1
            KnowledgeBaseApiResult.success(
                if (calls == 1) TopicRegistry(listOf(TopicLabel("work", "工作"))) else TopicRegistry(emptyList()),
            )
        }
        val first = coordinator.load(settings(), "config-a")
        val same = coordinator.load(settings(), "config-a")
        val empty = coordinator.load(settings("token-b"), "config-b")

        assertEquals(2, calls)
        assertEquals(listOf("work"), first.registry.topics.map { it.id })
        assertEquals(first, same)
        assertTrue(empty.loaded)
        assertTrue(empty.registry.topics.isEmpty())
    }

    @Test
    fun registryCoordinatorIsolatesConfigurationsDiscardsStaleAndRetainsLastGoodOnFailure() = runBlocking {
        val enteredA = CompletableDeferred<Unit>()
        val releaseA = CompletableDeferred<Unit>()
        var failB = false
        var calls = 0
        val coordinator = KnowledgeTopicRegistryCoordinator { settings ->
            calls += 1
            when (settings.ingestToken) {
                "token-a" -> {
                    enteredA.complete(Unit)
                    releaseA.await()
                    KnowledgeBaseApiResult.success(TopicRegistry(listOf(TopicLabel("a", "A"))))
                }
                else -> if (failB) {
                    KnowledgeBaseApiResult.failure("registry unavailable")
                } else {
                    KnowledgeBaseApiResult.success(TopicRegistry(listOf(TopicLabel("b", "B"))))
                }
            }
        }
        val staleA = async { coordinator.load(settings("token-a"), "config-a") }
        enteredA.await()
        val currentB = coordinator.load(settings("token-b"), "config-b")
        releaseA.complete(Unit)
        val staleResult = staleA.await()

        assertEquals("config-b", staleResult.configuration)
        assertEquals(listOf("b"), staleResult.registry.topics.map { it.id })
        assertEquals(listOf("b"), currentB.registry.topics.map { it.id })

        failB = true
        val failedRefresh = coordinator.load(settings("token-b"), "config-b", force = true)
        assertTrue(failedRefresh.loaded)
        assertEquals(listOf("b"), failedRefresh.registry.topics.map { it.id })
        assertEquals("registry unavailable", failedRefresh.error)
        assertEquals(3, calls)
    }

    @Test
    fun loadsOneHundredTwentySyntheticItemsAcrossIndependentKnowledgeBaseCursors() = runBlocking {
        val calls = mutableListOf<Pair<String, String>>()
        val paginator = KnowledgeTopicPaginator { _, knowledgeBaseId, cursor, _ ->
            calls += knowledgeBaseId to cursor
            val start = cursor.removePrefix("cursor-").toIntOrNull() ?: 0
            val count = if (knowledgeBaseId == "kb-a") 71 else 50
            val end = minOf(start + 40, count)
            KnowledgeBaseApiResult.success(
                KnowledgeTopicPage(
                    knowledgeBaseId,
                    knowledgeBaseId,
                    (start until end).map { index ->
                        clip(
                            // pc_...46 (decimal 70) is deliberately returned by both
                            // libraries so the All-scope merge proves public-ID deduplication.
                            id = if (knowledgeBaseId == "kb-a") index else 70 + index,
                            capturedAt = "2026-07-${((index % 20) + 1).toString().padStart(2, '0')}T00:00:00Z",
                        )
                    },
                    nextCursor = if (end < count) "cursor-$end" else "",
                ),
            )
        }
        val state = paginator.load(settings(), listOf("kb-a", "kb-b"))
        assertEquals(120, state.items.size)
        assertEquals(setOf("kb-a", "kb-b"), state.completedKnowledgeBaseIds)
        assertTrue(calls.contains("kb-a" to "cursor-40"))
        assertTrue(calls.contains("kb-b" to "cursor-40"))
        assertEquals(state.items.map { it.clipId }.distinct(), state.items.map { it.clipId })
        assertEquals(
            state.items.sortedWith(compareByDescending<KnowledgeTopicClip> { it.capturedAt }.thenBy { it.clipId }),
            state.items,
        )
        calls.clear()
        val refreshed = paginator.load(
            settings(),
            listOf("kb-a", "kb-b"),
            KnowledgeTopicPaginationState(knowledgeBaseIds = listOf("kb-a", "kb-b")),
        )
        assertEquals(state.items, refreshed.items)
        assertTrue(calls.contains("kb-a" to ""))
        assertTrue(calls.contains("kb-b" to ""))
    }

    @Test
    fun partialFailureRetainsResultsAndRetryResumesOnlyFailedKnowledgeBase() = runBlocking {
        var failB = true
        val calls = mutableListOf<Pair<String, String>>()
        val paginator = KnowledgeTopicPaginator { _, kb, cursor, _ ->
            calls += kb to cursor
            if (kb == "kb-b" && failB) {
                KnowledgeBaseApiResult.failure("暂时失败")
            } else {
                KnowledgeBaseApiResult.success(
                    KnowledgeTopicPage(kb, kb, listOf(clip(if (kb == "kb-a") 1 else 2)), ""),
                )
            }
        }
        val partial = paginator.load(settings(), listOf("kb-a", "kb-b"))
        assertEquals(1, partial.items.size)
        assertEquals(setOf("kb-a"), partial.completedKnowledgeBaseIds)
        assertEquals("暂时失败", partial.failuresByKnowledgeBase["kb-b"])

        failB = false
        calls.clear()
        val recovered = paginator.load(settings(), listOf("kb-a", "kb-b"), partial)
        assertEquals(2, recovered.items.size)
        assertTrue(recovered.failuresByKnowledgeBase.isEmpty())
        assertEquals(listOf("kb-b" to ""), calls)
    }

    @Test
    fun capIsExplicitAndStopsFurtherCursorRequests() = runBlocking {
        var calls = 0
        val paginator = KnowledgeTopicPaginator { _, kb, cursor, limit ->
            calls += 1
            val start = cursor.removePrefix("next-").toIntOrNull() ?: 0
            KnowledgeBaseApiResult.success(
                KnowledgeTopicPage(
                    kb,
                    kb,
                    (start until start + limit).map(::clip),
                    "next-${start + limit}",
                ),
            )
        }
        val state = paginator.load(settings(), listOf("kb-a"), cap = 120)
        assertEquals(120, state.items.size)
        assertTrue(state.capped)
        assertEquals(2, calls)
        assertFalse(state.completedKnowledgeBaseIds.contains("kb-a"))
    }

    @Test
    fun sameKnowledgeBaseIdsReloadAfterApiOrTokenChangeWithoutOldItemsOrRegistry() = runBlocking {
        val calls = mutableListOf<String>()
        val paginator = KnowledgeTopicPaginator { settings, kb, _, _ ->
            calls += "${settings.normalized().apiUrl}|$kb"
            val id = if (settings.ingestToken == "token-a") 1 else 2
            KnowledgeBaseApiResult.success(
                KnowledgeTopicPage(kb, kb, listOf(clip(id)), ""),
            )
        }
        val firstSettings =
            PerClipSettings("http://127.0.0.1:18082/a", "token-a", "test", true, false)
        val secondSettings =
            PerClipSettings("http://127.0.0.1:18082/b", "token-b", "test", true, false)
        val first = paginator.load(firstSettings, listOf("same-kb"))
        val second = paginator.load(secondSettings, listOf("same-kb"), first)

        assertEquals(listOf(clip(2)), second.items)
        assertEquals(2, calls.size)
        assertTrue(first.cacheKey != second.cacheKey)
        assertFalse(second.cacheKey.contains("token-b"))
        assertFalse(second.cacheKey.contains("127.0.0.1"))

        assertTrue(
            KnowledgeRemoteCacheVisibility.pagination(
                second.cacheKey,
                listOf("same-kb"),
                first,
            ).items.isEmpty(),
        )
    }

    @Test
    fun loadedCountNeverUsesSearchMatchCountAndClearRestoresWithoutReload() {
        val items = listOf(
            clip(1).copy(title = "Alpha"),
            clip(2).copy(title = "Beta"),
            clip(3).copy(title = "Gamma"),
        )
        val state = KnowledgeTopicPaginationState(items = items)

        val oneMatch = KnowledgeRemoteSearch.filter(items, "Alpha")
        assertEquals(1, oneMatch.size)
        assertEquals("已加载 3 条", KnowledgeRemoteSearch.loadedLabel(state))
        assertEquals("当前匹配 1 条", KnowledgeRemoteSearch.matchLabel("Alpha", oneMatch.size))

        val zeroMatches = KnowledgeRemoteSearch.filter(items, "No match")
        assertTrue(zeroMatches.isEmpty())
        assertEquals("已加载 3 条", KnowledgeRemoteSearch.loadedLabel(state))
        assertEquals("当前匹配 0 条", KnowledgeRemoteSearch.matchLabel("No match", 0))

        val capped = KnowledgeTopicPaginationState(
            items = (1..500).map(::clip),
            capped = true,
        )
        assertEquals(1, KnowledgeRemoteSearch.filter(capped.items, "Synthetic 499").size)
        assertEquals("已加载至上限 · 500 条", KnowledgeRemoteSearch.loadedLabel(capped))

        assertEquals(items, KnowledgeRemoteSearch.filter(items, ""))
        assertEquals("", KnowledgeRemoteSearch.matchLabel("", items.size))
    }

    private fun clip(id: Int, capturedAt: String = "2026-07-01T00:00:00Z") =
        KnowledgeTopicClip(
            clipId = "pc_${id.toString(16).padStart(32, '0')}",
            title = "Synthetic $id",
            capturedAt = capturedAt,
        )

    private fun settings(token: String = "token") =
        PerClipSettings("http://127.0.0.1:18082", token, "test", true, false)
}
