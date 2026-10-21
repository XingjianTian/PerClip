package com.sudox.perclip.data

import com.sudox.perclip.ClipKind
import com.sudox.perclip.upload.UploadStatus
import com.sudox.perclip.upload.UploadPart
import com.sudox.perclip.upload.UploadState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import org.json.JSONException
import org.json.JSONObject

class QueuedClipJsonTest {
    @Test
    fun roundTripsQueuedClipJson() {
        val clip = QueuedClip(
            id = "id-1",
            kind = ClipKind.Url,
            titleHint = "标题",
            text = "https://example.com",
            url = "https://example.com",
            mimeType = "text/plain",
            sourceApp = "browser",
            note = "note",
            items = listOf(
                QueuedClipItem(
                    cachedPath = "/tmp/a.pdf",
                    displayName = "a.pdf",
                    mimeType = "application/pdf",
                    sizeBytes = 12L,
                ),
            ),
            status = UploadStatus.Waiting,
            message = "等待后台同步",
            remotePath = "",
            createdAtEpochMs = 123L,
            statusUpdatedAtEpochMs = 456L,
            metadata = QueuedClipMetadata(
                tags = listOf("inbox", "read-later"),
                category = "article",
                summary = "摘要",
                extractedText = "extracted body",
                languageHint = "zh-CN",
                enrichmentStatus = "completed",
                enrichmentSummary = "处理摘要",
                enrichmentTags = listOf("ai", "note"),
                enrichmentLanguage = "zh-CN",
                publishStatus = "draft",
                reviewStatus = "approved",
                routingMode = "default_only",
                knowledgeBaseId = "kb_1",
                knowledgeBaseName = "Research",
                routingDecisionType = "manual",
                routingReason = "manual override: selected knowledge base \"Research\"",
                matchedRuleIds = listOf("rule-1", "rule-2"),
                manualOverride = true,
                previousKnowledgeBaseId = "kb_default",
                reindexStatus = "required",
                lineageId = "clip:1",
                remoteOriginalPath = "",
                remoteRagflowDocumentId = "doc-1",
                remoteArchiveStatus = "clip_to_ragflow",
                ragflowSyncOperation = "upload_document",
                ragflowSyncStatus = "planned",
                ragflowSyncDryRun = true,
                ragflowSyncReason = "dry-run only",
                ragflowSyncTargetDatasetId = "dataset-1",
                ragflowSyncDocumentId = "doc-1",
                ragflowSyncPlanSummary = "准备更新标题、摘要和标签",
                normalizedContractVersion = "perclip.clip.v1",
            ),
            uploadParts = listOf(
                UploadPart(
                    clientRequestId = "id-1:0:a.pdf",
                    titleHint = "a.pdf",
                    clientBatchId = "id-1",
                    parentClientRequestId = "id-1:",
                    partIndex = 0,
                    partCount = 2,
                    partRole = "file",
                    sourceIntent = "share",
                    state = UploadState.Uploaded,
                    message = "ok",
                ),
            ),
            capturedAtEpochMs = 120L,
            capturedTimezone = "Asia/Shanghai",
        )

        val decoded = QueuedClip.fromJson(clip.toJson())
        assertEquals("default_only", decoded.metadata.routingMode)

        assertEquals(clip.id, decoded.id)
        assertEquals(clip.kind, decoded.kind)
        assertEquals(clip.items.single().displayName, decoded.items.single().displayName)
        assertEquals(clip.createdAtEpochMs, decoded.createdAtEpochMs)
        assertEquals(clip.statusUpdatedAtEpochMs, decoded.statusUpdatedAtEpochMs)
        assertEquals(clip.metadata, decoded.metadata)
        assertEquals(clip.uploadParts, decoded.uploadParts)
        assertEquals(120L, decoded.capturedAtEpochMs)
        assertEquals("Asia/Shanghai", decoded.capturedTimezone)
    }

    @Test
    fun queueCodecRoundTripsClipList() {
        val clips = listOf(
            baseQueuedClip(
                id = "clip-1",
                status = UploadStatus.Waiting,
                statusUpdatedAtEpochMs = 456L,
            ),
        )

        val decoded = QueuedClipJsonCodec.decode(QueuedClipJsonCodec.encode(clips))

        assertEquals(clips, decoded)
    }

    @Test
    fun queueCodecTreatsBlankTextAsEmptyQueue() {
        assertEquals(emptyList<QueuedClip>(), QueuedClipJsonCodec.decode("  "))
    }

    @Test
    fun queueCodecRejectsCorruptJson() {
        assertThrows(JSONException::class.java) {
            QueuedClipJsonCodec.decode("[")
        }
    }

    @Test
    fun readsLegacyJsonWithMetadataDefaults() {
        val decoded = QueuedClip.fromJson(
            JSONObject()
                .put("id", "legacy")
                .put("kind", ClipKind.Text.name)
                .put("status", UploadStatus.Uploading.name)
                .put("createdAtEpochMs", 123L),
        )

        assertEquals(123L, decoded.statusUpdatedAtEpochMs)
        assertEquals(123L, decoded.capturedAtEpochMs)
        assertEquals("UTC", decoded.capturedTimezone)
        assertEquals(emptyList<String>(), decoded.metadata.tags)
        assertEquals("", decoded.metadata.category)
        assertEquals("", decoded.metadata.summary)
        assertEquals("", decoded.metadata.extractedText)
        assertEquals("", decoded.metadata.languageHint)
        assertEquals("", decoded.metadata.enrichmentStatus)
        assertEquals("", decoded.metadata.enrichmentSummary)
        assertEquals(emptyList<String>(), decoded.metadata.enrichmentTags)
        assertEquals("", decoded.metadata.enrichmentLanguage)
        assertEquals(QueuedClipMetadata.NOT_STARTED, decoded.metadata.publishStatus)
        assertEquals(QueuedClipMetadata.NOT_STARTED, decoded.metadata.reviewStatus)
        assertEquals("", decoded.metadata.remoteOriginalPath)
        assertEquals("", decoded.metadata.remoteRagflowDocumentId)
        assertEquals("", decoded.metadata.knowledgeBaseId)
        assertEquals("", decoded.metadata.knowledgeBaseName)
        assertEquals("", decoded.metadata.routingDecisionType)
        assertEquals("", decoded.metadata.routingReason)
        assertEquals(emptyList<String>(), decoded.metadata.matchedRuleIds)
        org.junit.Assert.assertFalse(decoded.metadata.manualOverride)
        assertEquals("", decoded.metadata.previousKnowledgeBaseId)
        assertEquals("", decoded.metadata.reindexStatus)
        assertEquals("", decoded.metadata.lineageId)
        assertEquals("", decoded.metadata.ragflowSyncOperation)
        assertEquals("", decoded.metadata.ragflowSyncStatus)
        org.junit.Assert.assertFalse(decoded.metadata.ragflowSyncDryRun)
        assertEquals("", decoded.metadata.ragflowSyncReason)
        assertEquals("", decoded.metadata.ragflowSyncTargetDatasetId)
        assertEquals("", decoded.metadata.ragflowSyncDocumentId)
        assertEquals("", decoded.metadata.ragflowSyncPlanSummary)
        assertEquals("", decoded.metadata.normalizedContractVersion)
        assertEquals(emptyList<UploadPart>(), decoded.uploadParts)
    }

    @Test
    fun ignoresUnknownQueueJsonFields() {
        val decoded = QueuedClip.fromJson(
            JSONObject()
                .put("id", "unknown-fields")
                .put("kind", ClipKind.Text.name)
                .put("titleHint", "title")
                .put("status", UploadStatus.Waiting.name)
                .put("createdAtEpochMs", 123L)
                .put("futureTopLevel", "ignored")
                .put(
                    "metadata",
                    JSONObject()
                        .put("tags", org.json.JSONArray().put("a").put("b"))
                        .put("category", "note")
                        .put("knowledgeBaseName", "Personal")
                        .put("futureMetadataField", "ignored"),
                ),
        )

        assertEquals("unknown-fields", decoded.id)
        assertEquals(listOf("a", "b"), decoded.metadata.tags)
        assertEquals("note", decoded.metadata.category)
        assertEquals("Personal", decoded.metadata.knowledgeBaseName)
    }

    @Test
    fun statusUpdateDropsRemotePathButKeepsNonPathStatus() {
        val updated = QueuedClipStatusUpdater.update(
            clip = baseQueuedClip(
                id = "uploaded",
                status = UploadStatus.Uploading,
                statusUpdatedAtEpochMs = 1L,
            ),
            status = UploadStatus.Uploaded,
            message = "已保存，后台处理完成。",
            remotePath = "/personalclips/uploaded.md",
            remoteRagflowDocumentId = "doc-uploaded",
            remoteArchiveStatus = "clip_to_ragflow",
            nowEpochMs = 2L,
        )

        assertEquals(UploadStatus.Uploaded, updated.status)
        assertEquals("", updated.remotePath)
        assertEquals("", updated.metadata.remoteOriginalPath)
        assertEquals("doc-uploaded", updated.metadata.remoteRagflowDocumentId)
        assertEquals("clip_to_ragflow", updated.metadata.remoteArchiveStatus)
        assertEquals(2L, updated.statusUpdatedAtEpochMs)
    }

    @Test
    fun legacyQueuePathsAreDroppedAndNeverReencoded() {
        val decoded = QueuedClip.fromJson(
            JSONObject()
                .put("id", "legacy-path")
                .put("kind", ClipKind.Text.name)
                .put("status", UploadStatus.Uploaded.name)
                .put("createdAtEpochMs", 123L)
                .put("remotePath", "/Volumes/private/archive.md")
                .put("metadata", JSONObject().put("remoteOriginalPath", "/srv/private/archive.md")),
        )

        assertEquals("", decoded.remotePath)
        assertEquals("", decoded.metadata.remoteOriginalPath)
        val reencoded = decoded.toJson().toString()
        org.junit.Assert.assertFalse(reencoded.contains("/Volumes/private"))
        org.junit.Assert.assertFalse(reencoded.contains("/srv/private"))
    }

    @Test
    fun queuedClipJsonDoesNotPersistKnownSecrets() {
        val secretValues = listOf(
            "mobile-token-secret",
            "change-me-server-side-ragflow-key",
            "change-me-baidu-api-key",
            "change-me-baidu-secret-key",
            "nas-password",
            "ssh-password",
            "cloud-secret",
            "social-secret",
        )
        val encoded = QueuedClipJsonCodec.encode(
            listOf(
                baseQueuedClip(
                    id = "secret-check",
                    status = UploadStatus.Waiting,
                    statusUpdatedAtEpochMs = 1L,
                ),
            ),
        )

        secretValues.forEach { secret ->
            org.junit.Assert.assertFalse(encoded.contains(secret))
        }
    }

    @Test
    fun recoversOnlyStaleUploadingClips() {
        val freshUploading = baseQueuedClip(
            id = "fresh",
            status = UploadStatus.Uploading,
            statusUpdatedAtEpochMs = 950L,
        )
        val staleUploading = baseQueuedClip(
            id = "stale",
            status = UploadStatus.Uploading,
            statusUpdatedAtEpochMs = 500L,
        )
        val failed = baseQueuedClip(
            id = "failed",
            status = UploadStatus.Failed,
            statusUpdatedAtEpochMs = 100L,
        )

        val recovered = UploadQueueRecovery.recoverStaleUploading(
            clips = listOf(freshUploading, staleUploading, failed),
            nowEpochMs = 1000L,
            staleAfterMs = 300L,
        )

        assertEquals(UploadStatus.Uploading, recovered[0].status)
        assertEquals(UploadStatus.Waiting, recovered[1].status)
        assertEquals(UploadQueueRecovery.RECOVERED_UPLOAD_MESSAGE, recovered[1].message)
        assertEquals(1000L, recovered[1].statusUpdatedAtEpochMs)
        assertEquals(UploadStatus.Failed, recovered[2].status)
    }

    @Test
    fun processRestartRecoversUploadingImmediately() {
        val interrupted = baseQueuedClip(
            id = "interrupted",
            status = UploadStatus.Uploading,
            statusUpdatedAtEpochMs = 1000L,
        ).copy(
            uploadParts = listOf(
                com.sudox.perclip.upload.UploadPart(
                    clientRequestId = "interrupted:0:text",
                    titleHint = "Interrupted",
                    clientBatchId = "interrupted",
                    parentClientRequestId = "interrupted:",
                    partIndex = 0,
                    partCount = 1,
                    partRole = "text",
                    sourceIntent = "share",
                    state = com.sudox.perclip.upload.UploadState.Uploading,
                ),
            ),
        )

        val recovered = UploadQueueRecovery.recoverStaleUploading(
            clips = listOf(interrupted),
            nowEpochMs = 1001L,
            staleAfterMs = 0L,
        ).single()

        assertEquals(UploadStatus.Waiting, recovered.status)
        assertEquals(com.sudox.perclip.upload.UploadState.Waiting, recovered.uploadParts.single().state)
        assertEquals(UploadQueueRecovery.RECOVERED_UPLOAD_MESSAGE, recovered.message)
    }

    @Test
    fun retentionKeepsMostRecentClipsAndReturnsDroppedClips() {
        val clips = (1L..52L).map { index ->
            baseQueuedClip(
                id = "clip-$index",
                status = UploadStatus.Uploaded,
                createdAtEpochMs = index,
                statusUpdatedAtEpochMs = index,
            )
        }

        val retention = ClipQueueRetention.retainMostRecent(clips, limit = 50)

        assertEquals(50, retention.kept.size)
        assertEquals("clip-52", retention.kept.first().id)
        assertEquals("clip-3", retention.kept.last().id)
        assertEquals(listOf("clip-2", "clip-1"), retention.dropped.map { it.id })
    }

    private fun baseQueuedClip(
        id: String,
        status: UploadStatus,
        statusUpdatedAtEpochMs: Long,
        createdAtEpochMs: Long = 1L,
    ): QueuedClip {
        return QueuedClip(
            id = id,
            kind = ClipKind.Text,
            titleHint = "标题",
            text = "hello",
            url = "",
            mimeType = "text/plain",
            sourceApp = "",
            note = "",
            items = emptyList(),
            status = status,
            message = status.name,
            remotePath = "",
            createdAtEpochMs = createdAtEpochMs,
            statusUpdatedAtEpochMs = statusUpdatedAtEpochMs,
        )
    }
}
