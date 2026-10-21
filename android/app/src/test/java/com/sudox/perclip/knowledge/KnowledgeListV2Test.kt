package com.sudox.perclip.knowledge

import com.sudox.perclip.capabilities.AppCapabilities
import com.sudox.perclip.capabilities.AppCapabilityResult
import com.sudox.perclip.capabilities.AppContracts
import com.sudox.perclip.capabilities.AppFeatures
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.ui.KnowledgeAttachmentFilter
import com.sudox.perclip.ui.KnowledgeTimeFilter
import com.sudox.perclip.upload.ClipLibraryTypeFilter
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeListV2Test {
    @Test fun readModeRequiresExactV2CapabilityAndContract() {
        assertEquals(KnowledgeReadMode.LOCAL_ONLY, KnowledgeReadModeResolver.resolve(false, null))
        assertEquals(KnowledgeReadMode.LOCAL_ONLY, KnowledgeReadModeResolver.resolve(true, null))
        assertEquals(KnowledgeReadMode.V2_LOCAL_FIRST, KnowledgeReadModeResolver.resolve(true, null, cachedV2 = true))
        assertEquals(KnowledgeReadMode.LEGACY_QUALITY_READ, KnowledgeReadModeResolver.resolve(true, capability(v2 = false, quality = true)))
        assertEquals(KnowledgeReadMode.V2_LOCAL_FIRST, KnowledgeReadModeResolver.resolve(true, capability(v2 = true, quality = true)))
        val wrong = capability(v2 = true, quality = true, contract = "perclip.knowledge-list.v1")
        assertEquals(KnowledgeReadMode.LEGACY_QUALITY_READ, KnowledgeReadModeResolver.resolve(true, wrong))
    }

    @Test fun normalizedQueryKeyIsStableHashedAndScopeSensitive() {
        val first = KnowledgeListQuery(listOf("kb b", "kb&a", "kb b"), " 中文 & 100%_ ", source = " 微信 ")
        val same = KnowledgeListQuery(listOf("kb&a", "kb b"), "中文 & 100%_", source = "微信")
        assertEquals(first.key, same.key)
        assertEquals(64, first.key.length)
        assertFalse(first.key.contains("中文"))
        assertNotEquals(first.key, same.copy(text = "different").key)
    }

    @Test fun parserCoversListSummaryMembershipIdentityAndChanges() {
        val item = """{"public_clip_id":"pc_00000000000000000000000000000001","knowledge_base_ids":["kb-a","kb-b"],"knowledge_base_id":"kb-a","knowledge_base_name":"A","title":"标题","summary":"摘要","source":"微信","source_type":"url","captured_at":"2026-07-28T00:00:00Z","safe_display_url":"https://example.com/path","has_attachment":false,"topic_assignment":{"contract_version":"perclip.topic-assignment.v1","primary":{"topic_id":"work","display_name":"工作"},"secondary":[],"entities":[],"keywords":[],"unclassified":false,"manual_override":false,"topic_disabled":false},"item_revision":7,"updated_at":"2026-07-28T01:00:00Z","correlation_identity":"local:1"}"""
        val list = KnowledgeTopicJson.parseKnowledgeList("""{"ok":true,"contract_version":"perclip.knowledge-list.v2","scope":{"knowledge_base_ids":["kb-a","kb-b"]},"summary":{"total_count":501,"matching_count":1,"revision":9,"generated_at":"now"},"items":[$item],"next_cursor":"kl_safe","has_more":true}""")
        assertEquals(501, list.summary.totalCount)
        assertEquals(1, list.summary.matchingCount)
        assertEquals(listOf("kb-a", "kb-b"), list.items.single().knowledgeBaseIds)
        assertEquals("local:1", list.items.single().correlationIdentity)
        assertTrue(list.hasMore)
        val changes = KnowledgeTopicJson.parseKnowledgeChanges("""{"ok":true,"contract_version":"perclip.knowledge-list.v2","changes":[{"revision":10,"public_clip_id":"pc_00000000000000000000000000000001","knowledge_base_id":"kb-a","knowledge_base_ids":["kb-b"],"operation":"upsert","source_operation":"move","reason":"test","changed_at":"now","item":$item}],"next_revision":10,"has_more":false,"current_revision":99}""")
        assertEquals(10, changes.nextRevision)
        assertEquals(99, changes.currentRevision)
        assertEquals("move", changes.changes.single().sourceOperation)
    }

    @Test fun httpUrlBuilderPreservesRepeatedIdsAndEncodesSpecialCharacters() {
        val url = KnowledgeBaseApi().buildKnowledgeUrl(
            "https://example.com", "/api/knowledge/clips",
            KnowledgeListQuery(listOf("kb a", "kb&b"), "中文 & 100%_", source = "We Chat"),
            cursor = "kl_+/=", limit = 50,
        )!!
        assertEquals(listOf("kb a", "kb&b"), url.queryParameterValues("knowledge_base_id"))
        assertEquals("中文 & 100%_", url.queryParameter("query"))
        assertEquals("kl_+/=", url.queryParameter("cursor"))
        assertFalse(url.toString().contains("中文"))
    }

    @Test fun filtersMapToFrozenV2ValuesAndUtcWindows() {
        val now = Instant.parse("2026-07-28T12:00:00Z")
        val query = knowledgeRemoteQuery(
            listOf("kb-a"), "needle", "Synthetic Files", ClipLibraryTypeFilter.File,
            KnowledgeAttachmentFilter.WithAttachment, KnowledgeTimeFilter.Last7Days, now,
        )
        assertEquals("file", query.sourceType)
        assertEquals("with", query.attachment)
        assertEquals("2026-07-21T12:00:00Z", query.capturedAfter)
        assertEquals("Synthetic Files", query.source)
    }

    @Test fun baseQueryClassificationMatchesFormalSearchAndFilterBoundary() {
        assertTrue(KnowledgeListQuery().baseQuery)
        assertTrue(KnowledgeListQuery(listOf("kb-a")).baseQuery)
        assertFalse(KnowledgeListQuery(text = "query").baseQuery)
        assertFalse(KnowledgeListQuery(source = "platform").baseQuery)
        assertFalse(KnowledgeListQuery(sourceType = "file").baseQuery)
        assertFalse(KnowledgeListQuery(attachment = "with").baseQuery)
        assertFalse(KnowledgeListQuery(capturedAfter = "2026-01-01T00:00:00Z").baseQuery)
        assertFalse(KnowledgeListQuery(capturedBefore = "2026-02-01T00:00:00Z").baseQuery)
    }

    @Test fun emptyStateRequiresAuthoritativeCleanSuccessfulZeroAndNoLocalTransitions() {
        fun empty(
            cacheReadComplete: Boolean = true,
            loading: Boolean = false,
            offline: Boolean = false,
            partial: Boolean = false,
            count: Int? = 0,
            remote: Int = 0,
            pending: Int = 0,
            failed: Int = 0,
            uploaded: Int = 0,
            dirty: Boolean = false,
        ) = KnowledgeEmptyStatePolicy.shouldShow(
            cacheReadComplete, loading, offline, partial, count, remote, pending, failed, uploaded, dirty,
        )

        assertTrue(empty())
        assertFalse(empty(cacheReadComplete = false))
        assertFalse(empty(loading = true))
        assertFalse(empty(offline = true))
        assertFalse(empty(partial = true))
        assertFalse(empty(count = null))
        assertFalse(empty(count = 1))
        assertFalse(empty(remote = 1))
        assertFalse(empty(pending = 1))
        assertFalse(empty(failed = 1))
        assertFalse(empty(uploaded = 1))
        assertFalse(empty(dirty = true))
    }

    private fun capability(v2: Boolean, quality: Boolean, contract: String = AppCapabilities.EXPECTED_KNOWLEDGE_LIST) =
        AppCapabilityResult(true, AppCapabilities(
            AppCapabilities.EXPECTED_CONTRACT, AppCapabilities.EXPECTED_SERVICE,
            AppFeatures(true, true, true, true, true, true, true, qualityReadModel = quality, knowledgeListV2 = v2),
            AppContracts(contract),
        ), message = "ok")
}
