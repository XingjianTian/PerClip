package com.sudox.perclip.knowledge

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeLibraryScopeTest {
    @Test
    fun filtersAllSpecificAndUnassigned() {
        val routed = record("routed", UploadStatus.Uploaded, "kb-1", "rule")
        val noRoute = record("no-route", UploadStatus.Uploaded, "kb-1", "")
        val waiting = record("waiting", UploadStatus.Waiting, "kb-1", "rule")
        val empty = record("empty", UploadStatus.Uploaded, "", "")
        val records = listOf(routed, noRoute, waiting, empty)

        assertEquals(4, KnowledgeLibraryScopes.filter(records, KnowledgeLibraryScope.All).size)
        assertEquals(3, KnowledgeLibraryScopes.filter(records, KnowledgeLibraryScope.Specific("kb-1")).size)
        assertEquals(listOf("no-route", "waiting", "empty"), KnowledgeLibraryScopes.filter(records, KnowledgeLibraryScope.Unassigned).map { it.clip.id })
    }

    @Test
    fun sortsDefaultFirstAndKeepsLocallyKnownLibraries() {
        val remote = listOf(
            KnowledgeBaseSummary("b", "工作"),
            KnowledgeBaseSummary("a", "默认", isDefault = true),
            KnowledgeBaseSummary("archived", "归档", isArchived = true),
        )
        val choices = KnowledgeLibraryScopes.activeChoices(remote, listOf(record("x", UploadStatus.Uploaded, "local", "rule", "本地库")))

        assertEquals(listOf("a", "b", "local"), choices.map { it.id })
        assertEquals("本地库", choices.last().name)
    }

    @Test
    fun removedArchivedOrDeletedSelectionFallsBackToAll() {
        val selected = KnowledgeLibraryScope.Specific("gone")
        assertSame(KnowledgeLibraryScope.All, KnowledgeLibraryScopes.resolveSelection(selected, emptyList()))
        assertTrue(KnowledgeLibraryScopes.resolveSelection(selected, listOf(KnowledgeBaseSummary("gone", "仍在"))) is KnowledgeLibraryScope.Specific)
    }

    @Test
    fun successfulRemoteListNeverResurrectsArchivedDeletedOrMissingLocalIds() {
        val remote = listOf(
            KnowledgeBaseSummary("active", "活跃"),
            KnowledgeBaseSummary("archived", "归档", isArchived = true),
            KnowledgeBaseSummary("deleted", "删除", deletedAt = "now"),
        )
        val records = listOf(
            record("a", UploadStatus.Uploaded, "archived", "rule"),
            record("d", UploadStatus.Uploaded, "deleted", "rule"),
            record("m", UploadStatus.Uploaded, "missing", "rule"),
        )
        assertEquals(
            listOf("active"),
            KnowledgeLibraryScopes.activeChoices(remote, records, KnowledgeBaseRemoteListState.SUCCESS).map { it.id },
        )
    }

    @Test
    fun failedRemoteListKeepsReadOnlyLocalFallbackAndScopedBanner() {
        val local = record("saved", UploadStatus.Waiting, "local", "rule", "本地库")
        assertEquals(
            listOf("local"),
            KnowledgeLibraryScopes.activeChoices(emptyList(), listOf(local), KnowledgeBaseRemoteListState.FAILED).map { it.id },
        )
        assertEquals(local, KnowledgeLibraryScopes.recentlySavedInScope(listOf(local), "saved", KnowledgeLibraryScope.Specific("local")))
        assertEquals(null, KnowledgeLibraryScopes.recentlySavedInScope(listOf(local), "saved", KnowledgeLibraryScope.Specific("other")))
    }

    @Test fun scopedEmptyStateDiffersFromGlobalEmptyState() {
        assertEquals("还没有闪记", KnowledgeLibraryScopes.emptyTitle(KnowledgeLibraryScope.All))
        assertEquals("当前知识库还没有闪记", KnowledgeLibraryScopes.emptyTitle(KnowledgeLibraryScope.Specific("kb")))
        assertTrue(KnowledgeLibraryScopes.emptyBody(KnowledgeLibraryScope.Unassigned).contains("全部"))
    }

    private fun record(
        id: String,
        status: UploadStatus,
        knowledgeBaseId: String,
        routingDecisionType: String,
        knowledgeBaseName: String = "库",
    ) = UploadRecord(
        clip = SharedClip(id = id, kind = ClipKind.Text, titleHint = id, text = id),
        status = status,
        message = "",
        metadata = QueuedClipMetadata(
            knowledgeBaseId = knowledgeBaseId,
            knowledgeBaseName = knowledgeBaseName,
            routingDecisionType = routingDecisionType,
        ),
    )
}
