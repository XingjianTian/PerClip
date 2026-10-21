package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClipProcessingStatusRefreshTest {
    @Test
    fun `one successful endpoint applies available remote state`() {
        val outcome = ClipProcessingStatusRefresh.resolve(
            sync = KnowledgeBaseApiResult.failure("ragflow sync not found"),
            enrichment = KnowledgeBaseApiResult.success(
                EnrichmentStatusResponse("completed", "summary", emptyList(), "zh", "text"),
            ),
        )

        assertTrue(outcome.shouldApplyRemoteState)
        assertEquals("处理状态已刷新。", outcome.message)
    }

    @Test
    fun `both missing endpoints report no sync record`() {
        val outcome = ClipProcessingStatusRefresh.resolve(
            sync = KnowledgeBaseApiResult.failure("ragflow sync not found"),
            enrichment = KnowledgeBaseApiResult.failure("enrichment not found"),
        )

        assertFalse(outcome.shouldApplyRemoteState)
        assertEquals("暂无同步记录。", outcome.message)
    }

    @Test
    fun `network failure remains explicit`() {
        val outcome = ClipProcessingStatusRefresh.resolve(
            sync = KnowledgeBaseApiResult.failure("连接 NAS 失败"),
            enrichment = KnowledgeBaseApiResult.failure("连接 NAS 失败"),
        )

        assertFalse(outcome.shouldApplyRemoteState)
        assertEquals("刷新处理状态失败：连接 NAS 失败", outcome.message)
    }
}
