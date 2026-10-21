package com.sudox.perclip.knowledge

internal object KnowledgeManagementPresentation {
    val supportedPlatformLabels = listOf("小红书", "知乎", "微信", "网页", "Bilibili", "X", "Medium", "更多")

    fun active(items: List<KnowledgeBaseSummary>) = items.filter { !it.isArchived && it.deletedAt.isBlank() }

    fun archived(items: List<KnowledgeBaseSummary>) = items.filter { it.isArchived && it.deletedAt.isBlank() }

    fun menuActions(item: KnowledgeBaseSummary): List<String> = buildList {
        if (!item.isDefault && !item.isArchived) add("set_default")
        if (!item.isArchived) add("rename")
        if (!item.isDefault && !item.isArchived) add("delete_mapping")
    }
}
