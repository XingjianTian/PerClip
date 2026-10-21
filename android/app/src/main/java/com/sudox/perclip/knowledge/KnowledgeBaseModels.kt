package com.sudox.perclip.knowledge

data class KnowledgeBaseTopicSummary(
    val id: String,
    val label: String,
    val clipCount: Int,
)

data class KnowledgeBaseSummary(
    val id: String,
    val name: String,
    val description: String = "",
    val icon: String = "",
    val color: String = "",
    val isDefault: Boolean = false,
    val isArchived: Boolean = false,
    val ragflowDatasetId: String = "",
    val ragflowDatasetName: String = "",
    val templateKey: String = "general",
    val createdAt: String = "",
    val updatedAt: String = "",
    val deletedAt: String = "",
    val topTopics: List<KnowledgeBaseTopicSummary> = emptyList(),
) {
    val displayName: String
        get() = name.ifBlank { "未命名知识库" }

    val ragflowShortId: String
        get() = if (ragflowDatasetId.isBlank()) "未绑定" else ragflowDatasetId.take(8)
}

data class KnowledgeBaseListResponse(
    val ok: Boolean,
    val knowledgeBases: List<KnowledgeBaseSummary>,
)

data class KnowledgeBaseMutationResponse(
    val ok: Boolean,
    val knowledgeBase: KnowledgeBaseSummary,
    val ragflowDatasetDeleted: Boolean = false,
)

data class ClipRouteDecisionSummary(
    val clipId: String,
    val clientRequestId: String,
    val knowledgeBaseId: String,
    val knowledgeBaseName: String = "",
    val ragflowDatasetId: String = "",
    val decisionType: String,
    val matchedRuleId: String = "",
    val matchedRuleIds: List<String> = emptyList(),
    val confidence: Double = 0.0,
    val manualOverride: Boolean = false,
    val reason: String,
    val createdAt: String = "",
    val previousKnowledgeBaseId: String = "",
    val reindexStatus: String = "",
    val lineageId: String = "",
)

data class RagflowCapabilitySummary(
    val adapterStatus: String,
    val configured: Boolean,
    val capabilities: Map<String, String>,
    val notes: List<String> = emptyList(),
)

data class RagflowProbeSummary(
    val configured: Boolean,
    val status: String,
    val capabilities: Map<String, String>,
    val warnings: List<String> = emptyList(),
    val latencyMs: Long? = null,
)

data class RagflowSyncStatusResponse(
    val operation: String,
    val status: String,
    val dryRun: Boolean,
    val reason: String,
    val targetDatasetId: String,
    val documentId: String,
    val planSummary: String,
)

data class EnrichmentStatusResponse(
    val status: String,
    val summary: String,
    val tags: List<String>,
    val language: String,
    val extractedText: String,
)

data class KnowledgeBaseApiResult<T>(
    val ok: Boolean,
    val value: T?,
    val message: String = "",
) {
    companion object {
        fun <T> success(value: T): KnowledgeBaseApiResult<T> = KnowledgeBaseApiResult(
            ok = true,
            value = value,
        )

        fun <T> failure(message: String): KnowledgeBaseApiResult<T> = KnowledgeBaseApiResult(
            ok = false,
            value = null,
            message = message,
        )
    }
}
