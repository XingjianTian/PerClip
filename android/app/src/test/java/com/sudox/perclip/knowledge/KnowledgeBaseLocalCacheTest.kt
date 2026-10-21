package com.sudox.perclip.knowledge

import com.sudox.perclip.config.PerClipSettings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeBaseLocalCacheTest {
    private fun settings(apiUrl: String, token: String) = PerClipSettings(
        apiUrl = apiUrl,
        ingestToken = token,
        deviceName = "test",
        wifiOnlyLargeFiles = true,
        persistentQuickEntry = false,
    )

    @Test
    fun codecKeepsOnlyActiveTargetsAndRestoresDefault() {
        val source = listOf(
            KnowledgeBaseSummary(
                id = "default",
                name = "个人收藏",
                description = "默认",
                isDefault = true,
                topTopics = listOf(
                    KnowledgeBaseTopicSummary("topic:ai", "AI 工具", 7),
                    KnowledgeBaseTopicSummary("topic:android", "Android", 5),
                ),
            ),
            KnowledgeBaseSummary(id = "ai", name = "AI 知识库"),
            KnowledgeBaseSummary(id = "old", name = "已归档", isArchived = true),
        )

        val restored = KnowledgeBaseCacheCodec.decode(KnowledgeBaseCacheCodec.encode(source))

        assertEquals(listOf("default", "ai"), restored.map { it.id })
        assertTrue(restored.first().isDefault)
        assertFalse(restored.any { it.isArchived })
        assertEquals(listOf("AI 工具", "Android"), restored.first().topTopics.map { it.label })
        assertEquals(7, restored.first().topTopics.first().clipCount)
    }

    @Test
    fun malformedCacheIsIgnored() {
        assertEquals(emptyList<KnowledgeBaseSummary>(), KnowledgeBaseCacheCodec.decode("not-json"))
    }

    @Test
    fun cacheScopeIsStableForNormalizedConfiguration() {
        val first = KnowledgeBaseCacheScope.fromSettings(settings(" https://example.test/ ", " token "))
        val second = KnowledgeBaseCacheScope.fromSettings(settings("https://example.test", "token"))

        assertEquals(first, second)
    }

    @Test
    fun cacheScopeSeparatesServerAndAccountConfiguration() {
        val baseline = KnowledgeBaseCacheScope.fromSettings(settings("https://one.test", "token-a"))

        assertFalse(baseline == KnowledgeBaseCacheScope.fromSettings(settings("https://two.test", "token-a")))
        assertFalse(baseline == KnowledgeBaseCacheScope.fromSettings(settings("https://one.test", "token-b")))
    }
}
