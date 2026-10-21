package com.sudox.perclip.knowledge

data class ClipProcessingStatusRefreshOutcome(
    val shouldApplyRemoteState: Boolean,
    val message: String,
)

object ClipProcessingStatusRefresh {
    fun resolve(
        sync: KnowledgeBaseApiResult<RagflowSyncStatusResponse>,
        enrichment: KnowledgeBaseApiResult<EnrichmentStatusResponse>,
    ): ClipProcessingStatusRefreshOutcome {
        if (sync.ok || enrichment.ok) {
            return ClipProcessingStatusRefreshOutcome(
                shouldApplyRemoteState = true,
                message = "处理状态已刷新。",
            )
        }
        if (isNotFound(sync.message) && isNotFound(enrichment.message)) {
            return ClipProcessingStatusRefreshOutcome(
                shouldApplyRemoteState = false,
                message = "暂无同步记录。",
            )
        }
        return ClipProcessingStatusRefreshOutcome(
            shouldApplyRemoteState = false,
            message = "刷新处理状态失败：${sync.message.ifBlank { enrichment.message.ifBlank { "网络请求失败。" } }}",
        )
    }

    private fun isNotFound(message: String): Boolean =
        message.contains("not found", ignoreCase = true) || message.contains("没有找到")
}
