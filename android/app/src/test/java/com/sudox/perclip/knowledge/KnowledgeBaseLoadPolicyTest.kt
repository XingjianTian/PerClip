package com.sudox.perclip.knowledge

import com.sudox.perclip.StartTab
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeBaseLoadPolicyTest {
    @Test fun knowledgeSurfaceLoadsWhenCapabilityArrives() {
        assertTrue(KnowledgeBaseLoadPolicy.shouldLoad(true, true, "new", "", false))
    }

    @Test fun flashTabDoesNotRequestKnowledgeBaseListForDestinationLabel() {
        assertFalse(KnowledgeBaseLoadPolicy.isRemoteListSurface(StartTab.Save.index, managementOpen = false))
        assertTrue(KnowledgeBaseLoadPolicy.isRemoteListSurface(StartTab.Recents.index, managementOpen = false))
        assertFalse(KnowledgeBaseLoadPolicy.isRemoteListSurface(StartTab.Recents.index, managementOpen = true))
    }

    @Test fun tabRoundTripAndUnrelatedTabsDoNotCreateRequestStorm() {
        assertFalse(KnowledgeBaseLoadPolicy.shouldLoad(true, true, "same", "same", false))
        assertFalse(KnowledgeBaseLoadPolicy.shouldLoad(true, true, "new", "", true))
        assertFalse(KnowledgeBaseLoadPolicy.shouldLoad(false, true, "new", "", false))
        assertFalse(KnowledgeBaseLoadPolicy.shouldLoad(true, false, "new", "", false))
    }
}
