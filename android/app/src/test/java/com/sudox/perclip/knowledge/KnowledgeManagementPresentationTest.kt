package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeManagementPresentationTest {
    @Test fun supportedPlatformOrderStaysStable() {
        assertEquals(
            listOf("小红书", "知乎", "微信", "网页", "Bilibili", "X", "Medium", "更多"),
            KnowledgeManagementPresentation.supportedPlatformLabels,
        )
    }

    @Test fun activeAndArchivedGroupingExcludesDeletedMappings() {
        val active = KnowledgeBaseSummary("active", "活跃")
        val archived = KnowledgeBaseSummary("archived", "归档", isArchived = true)
        val deleted = KnowledgeBaseSummary("deleted", "删除", deletedAt = "2026-07-30")
        val values = listOf(archived, deleted, active)
        assertEquals(listOf(active), KnowledgeManagementPresentation.active(values))
        assertEquals(listOf(archived), KnowledgeManagementPresentation.archived(values))
    }

    @Test fun currentDefaultHasNoSetDefaultOrDeleteAction() {
        val current = KnowledgeBaseSummary("default", "默认", isDefault = true)
        val other = KnowledgeBaseSummary("other", "其他")
        val archived = KnowledgeBaseSummary("old", "旧库", isArchived = true)
        assertEquals(listOf("rename"), KnowledgeManagementPresentation.menuActions(current))
        assertEquals(listOf("set_default", "rename", "delete_mapping"), KnowledgeManagementPresentation.menuActions(other))
        assertTrue(KnowledgeManagementPresentation.menuActions(archived).isEmpty())
        assertFalse(KnowledgeManagementPresentation.menuActions(current).contains("delete_mapping"))
    }
}
