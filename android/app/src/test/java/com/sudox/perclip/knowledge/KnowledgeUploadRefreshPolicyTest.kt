package com.sudox.perclip.knowledge

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeUploadRefreshPolicyTest {
    @Test
    fun refreshesOneNewCompletionOnlyForRemoteKnowledge() {
        assertTrue(
            KnowledgeUploadRefreshPolicy.shouldRefresh(
                completionRevision = 2,
                handledRevision = 1,
                mode = KnowledgeReadMode.V2_LOCAL_FIRST,
                scope = KnowledgeLibraryScope.All,
            ),
        )
        assertFalse(
            KnowledgeUploadRefreshPolicy.shouldRefresh(
                completionRevision = 2,
                handledRevision = 2,
                mode = KnowledgeReadMode.V2_LOCAL_FIRST,
                scope = KnowledgeLibraryScope.All,
            ),
        )
        assertFalse(
            KnowledgeUploadRefreshPolicy.shouldRefresh(
                completionRevision = 2,
                handledRevision = 1,
                mode = KnowledgeReadMode.LOCAL_ONLY,
                scope = KnowledgeLibraryScope.All,
            ),
        )
        assertFalse(
            KnowledgeUploadRefreshPolicy.shouldRefresh(
                completionRevision = 2,
                handledRevision = 1,
                mode = KnowledgeReadMode.V2_LOCAL_FIRST,
                scope = KnowledgeLibraryScope.Unassigned,
            ),
        )
    }

    @Test
    fun advancesPastIneligibleOrStaleCompletion() {
        assertEquals(3, KnowledgeUploadRefreshPolicy.handledRevision(3, 1))
        assertEquals(3, KnowledgeUploadRefreshPolicy.handledRevision(2, 3))
    }
}
