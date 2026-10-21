package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class KnowledgeBaseUiLogicTest {
    @Test
    fun activeTargetsFilterArchivedAndSortDefaultFirst() {
        val archived = KnowledgeBaseSummary(id = "kb_archived", name = "Archived", isArchived = true)
        val normal = KnowledgeBaseSummary(id = "kb_normal", name = "Normal", updatedAt = "2026-07-08")
        val default = KnowledgeBaseSummary(id = "kb_default", name = "Default", isDefault = true, updatedAt = "2026-07-01")

        val targets = KnowledgeBaseUiLogic.activeSaveTargets(listOf(archived, normal, default))

        assertEquals(listOf("kb_default", "kb_normal"), targets.map { it.id })
        assertFalse(targets.any { it.isArchived })
    }
}
