package com.sudox.perclip.capture

import com.sudox.perclip.knowledge.KnowledgeBaseSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class CaptureMetadataPolicyTest {
    @Test
    fun defaultOnlyCachesCurrentDefaultForDisplayWithoutCreatingManualOverride() {
        val metadata = CaptureMetadataPolicy.defaultOnly(
            KnowledgeBaseSummary(id = "kb-default", name = "个人收藏", isDefault = true),
        )

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, metadata.routingMode)
        assertEquals("kb-default", metadata.knowledgeBaseId)
        assertEquals("个人收藏", metadata.knowledgeBaseName)
        assertEquals("default", metadata.routingDecisionType)
        assertFalse(metadata.manualOverride)
    }

    @Test
    fun defaultOnlyDoesNotInventTargetWhenCacheHasNoDefault() {
        val metadata = CaptureMetadataPolicy.defaultOnly(defaultKnowledgeBase = null)

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, metadata.routingMode)
        assertEquals("", metadata.knowledgeBaseId)
        assertEquals("", metadata.knowledgeBaseName)
        assertFalse(metadata.manualOverride)
    }
}
