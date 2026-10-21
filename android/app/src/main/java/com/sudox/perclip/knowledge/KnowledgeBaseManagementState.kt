package com.sudox.perclip.knowledge

data class KnowledgeBaseManagementState(
    val listLoading: Boolean = false,
    val knowledgeBases: List<KnowledgeBaseSummary> = emptyList(),
    val listError: String = "",
    val mutationMessage: String = "",
    val listLoadedSuccessfully: Boolean = false,
    val capabilitiesLoading: Boolean = false,
    val capabilities: RagflowCapabilitySummary? = null,
    val capabilitiesError: String = "",
    val lastSuccessfulLoad: Long? = null,
) {
    val showEmpty: Boolean get() = listLoadedSuccessfully && !listLoading && knowledgeBases.isEmpty()
    val defaultName: String get() = knowledgeBases.firstOrNull { it.isDefault }?.displayName ?: "未设置"
    val activeCount: Int get() = knowledgeBases.count { !it.isArchived && it.deletedAt.isBlank() }
    val archivedCount: Int get() = knowledgeBases.count { it.isArchived && it.deletedAt.isBlank() }

    fun withListResult(result: KnowledgeBaseApiResult<KnowledgeBaseListResponse>, now: Long): KnowledgeBaseManagementState =
        if (result.ok) copy(
            listLoading = false,
            knowledgeBases = result.value?.knowledgeBases?.let(KnowledgeBaseUiLogic::sortForManagement).orEmpty(),
            listError = "",
            listLoadedSuccessfully = true,
            lastSuccessfulLoad = now,
        ) else copy(listLoading = false, listError = result.message)

    fun withCapabilitiesResult(result: KnowledgeBaseApiResult<RagflowCapabilitySummary>): KnowledgeBaseManagementState =
        if (result.ok) copy(capabilitiesLoading = false, capabilities = result.value, capabilitiesError = "")
        else copy(capabilitiesLoading = false, capabilitiesError = result.message)

    fun finishMutation(
        mutationMessage: String,
        listResult: KnowledgeBaseApiResult<KnowledgeBaseListResponse>,
        now: Long,
    ): KnowledgeBaseManagementState = withListResult(listResult, now).copy(mutationMessage = mutationMessage)
}
