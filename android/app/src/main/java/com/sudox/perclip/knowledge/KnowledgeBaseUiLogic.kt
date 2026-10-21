package com.sudox.perclip.knowledge

object KnowledgeBaseUiLogic {
    fun sortForManagement(items: List<KnowledgeBaseSummary>): List<KnowledgeBaseSummary> {
        return items.sortedWith(
            compareByDescending<KnowledgeBaseSummary> { it.isDefault }
                .thenBy { it.isArchived }
                .thenByDescending { it.updatedAt }
                .thenBy { it.name.lowercase() },
        )
    }

    fun activeSaveTargets(items: List<KnowledgeBaseSummary>): List<KnowledgeBaseSummary> {
        return sortForManagement(items).filterNot { it.isArchived || it.deletedAt.isNotBlank() }
    }

}
