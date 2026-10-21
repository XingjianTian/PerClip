package com.sudox.perclip.data

import android.content.Context
import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.SharedClipItem
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.CaptureTimezone
import com.sudox.perclip.upload.UploadPart
import com.sudox.perclip.upload.UploadState
import com.sudox.perclip.upload.UploadStatus
import java.io.File
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import org.json.JSONArray
import org.json.JSONObject

class ClipQueueStore(context: Context) {
    private val appContext = context.applicationContext
    private val queueFile = File(appContext.filesDir, "clip_queue.json")

    @Synchronized
    fun recent(limit: Int = RECENT_LIMIT): List<QueuedClip> {
        return readAll()
            .sortedByDescending { it.createdAtEpochMs }
            .take(limit)
    }

    @Synchronized
    fun all(): List<QueuedClip> = readAll()

    @Synchronized
    fun find(id: String): QueuedClip? = readAll().firstOrNull { it.id == id }

    @Synchronized
    fun upsert(clip: QueuedClip): List<QueuedClip> {
        val clips = readAll().filterNot { it.id == clip.id }.toMutableList()
        clips.add(clip)
        val retention = ClipQueueRetention.retainMostRecent(clips, RECENT_LIMIT)
        writeAll(retention.kept)
        return retention.dropped
    }

    @Synchronized
    fun updateStatus(
        id: String,
        status: UploadStatus,
        message: String,
        remotePath: String = "",
        remoteRagflowDocumentId: String = "",
        remoteArchiveStatus: String = "",
    ) {
        val now = System.currentTimeMillis()
        val updated = readAll().map { clip ->
            if (clip.id == id) {
                QueuedClipStatusUpdater.update(
                    clip = clip,
                    status = status,
                    message = message,
                    remotePath = remotePath,
                    remoteRagflowDocumentId = remoteRagflowDocumentId,
                    remoteArchiveStatus = remoteArchiveStatus,
                    nowEpochMs = now,
                )
            } else {
                clip
            }
        }
        writeAll(updated)
    }

    @Synchronized
    fun updateMetadata(id: String, transform: (QueuedClipMetadata) -> QueuedClipMetadata): QueuedClip? {
        var updatedClip: QueuedClip? = null
        val updated = readAll().map { clip ->
            if (clip.id == id) {
                clip.copy(metadata = transform(clip.metadata)).also { updatedClip = it }
            } else {
                clip
            }
        }
        if (updatedClip != null) {
            writeAll(updated)
        }
        return updatedClip
    }

    @Synchronized
    fun replaceUploadParts(id: String, parts: List<UploadPart>): QueuedClip? {
        var updatedClip: QueuedClip? = null
        val updated = readAll().map { clip ->
            if (clip.id == id) clip.copy(uploadParts = parts).also { updatedClip = it } else clip
        }
        if (updatedClip != null) writeAll(updated)
        return updatedClip
    }

    @Synchronized
    fun updateUploadPart(id: String, clientRequestId: String, state: UploadState, message: String = ""): QueuedClip? {
        var updatedClip: QueuedClip? = null
        val updated = readAll().map { clip ->
            if (clip.id != id) return@map clip
            clip.copy(
                uploadParts = clip.uploadParts.map { part ->
                    if (part.clientRequestId == clientRequestId) part.copy(state = state, message = message) else part
                },
            ).also { updatedClip = it }
        }
        if (updatedClip != null) writeAll(updated)
        return updatedClip
    }

    @Synchronized
    fun replaceAll(clips: List<QueuedClip>) {
        writeAll(ClipQueueRetention.retainMostRecent(clips, RECENT_LIMIT).kept)
    }

    @Synchronized
    fun recoverStaleUploading(staleAfterMs: Long = STALE_UPLOADING_AFTER_MS): List<QueuedClip> {
        val now = System.currentTimeMillis()
        val clips = readAll()
        val recovered = UploadQueueRecovery.recoverStaleUploading(
            clips = clips,
            nowEpochMs = now,
            staleAfterMs = staleAfterMs,
        )
        if (recovered != clips) {
            writeAll(recovered)
        }
        return recovered.filter { clip ->
            val original = clips.firstOrNull { it.id == clip.id }
            original?.status == UploadStatus.Uploading && clip.status == UploadStatus.Waiting
        }
    }

    @Synchronized
    fun remove(id: String): QueuedClip? {
        val clips = readAll()
        val removed = clips.firstOrNull { it.id == id }
        if (removed != null) {
            writeAll(clips.filterNot { it.id == id })
        }
        return removed
    }

    private fun readAll(): List<QueuedClip> {
        if (!queueFile.exists()) return emptyList()
        val text = queueFile.readText(charset = Charsets.UTF_8).ifBlank { "[]" }
        return runCatching { QueuedClipJsonCodec.decode(text) }
            .getOrElse {
                quarantineCorruptQueueFile()
                emptyList()
            }
    }

    private fun writeAll(clips: List<QueuedClip>) {
        queueFile.parentFile?.mkdirs()
        val tempFile = File(queueFile.parentFile, "${queueFile.name}.tmp")
        tempFile.writeText(QueuedClipJsonCodec.encode(clips), charset = Charsets.UTF_8)
        try {
            Files.move(
                tempFile.toPath(),
                queueFile.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
                StandardCopyOption.ATOMIC_MOVE,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(
                tempFile.toPath(),
                queueFile.toPath(),
                StandardCopyOption.REPLACE_EXISTING,
            )
        }
    }

    private fun quarantineCorruptQueueFile() {
        val corruptFile = File(
            queueFile.parentFile,
            "${queueFile.name}.corrupt.${System.currentTimeMillis()}",
        )
        if (!queueFile.renameTo(corruptFile)) {
            queueFile.delete()
        }
    }

    companion object {
        const val RECENT_LIMIT = 50
        const val STALE_UPLOADING_AFTER_MS = 5 * 60 * 1000L
    }
}

object QueuedClipJsonCodec {
    fun decode(text: String): List<QueuedClip> {
        val array = JSONArray(text.ifBlank { "[]" })
        return buildList {
            for (index in 0 until array.length()) {
                add(QueuedClip.fromJson(array.getJSONObject(index)))
            }
        }
    }

    fun encode(clips: List<QueuedClip>): String {
        val array = JSONArray()
        clips.forEach { array.put(it.toJson()) }
        return array.toString()
    }
}

data class ClipQueueRetentionResult(
    val kept: List<QueuedClip>,
    val dropped: List<QueuedClip>,
)

object ClipQueueRetention {
    fun retainMostRecent(clips: List<QueuedClip>, limit: Int): ClipQueueRetentionResult {
        val sorted = clips.sortedByDescending { it.createdAtEpochMs }
        return ClipQueueRetentionResult(
            kept = sorted.take(limit),
            dropped = sorted.drop(limit),
        )
    }
}

object UploadQueueRecovery {
    const val RECOVERED_UPLOAD_MESSAGE = "上次后台同步中断，等待重新同步。"

    fun recoverStaleUploading(
        clips: List<QueuedClip>,
        nowEpochMs: Long,
        staleAfterMs: Long,
    ): List<QueuedClip> {
        return clips.map { clip ->
            if (clip.status == UploadStatus.Uploading && nowEpochMs - clip.statusUpdatedAtEpochMs >= staleAfterMs) {
                clip.copy(
                    status = UploadStatus.Waiting,
                    message = RECOVERED_UPLOAD_MESSAGE,
                    statusUpdatedAtEpochMs = nowEpochMs,
                    uploadParts = clip.uploadParts.map { part ->
                        if (part.state == UploadState.Uploading) part.copy(state = UploadState.Waiting) else part
                    },
                )
            } else {
                clip
            }
        }
    }
}

object QueuedClipStatusUpdater {
    fun update(
        clip: QueuedClip,
        status: UploadStatus,
        message: String,
        remotePath: String = "",
        remoteRagflowDocumentId: String = "",
        remoteArchiveStatus: String = "",
        nowEpochMs: Long,
    ): QueuedClip {
        return clip.copy(
            status = status,
            message = message,
            remotePath = "",
            metadata = clip.metadata.withUploadRemoteFields(
                originalPath = "",
                ragflowDocumentId = remoteRagflowDocumentId,
                archiveStatus = remoteArchiveStatus,
            ),
            statusUpdatedAtEpochMs = nowEpochMs,
        )
    }
}

data class QueuedClip(
    val id: String,
    val kind: ClipKind,
    val titleHint: String,
    val text: String,
    val url: String,
    val mimeType: String,
    val sourceApp: String,
    val note: String,
    val items: List<QueuedClipItem>,
    val status: UploadStatus,
    val message: String,
    val remotePath: String,
    val createdAtEpochMs: Long,
    val statusUpdatedAtEpochMs: Long = createdAtEpochMs,
    val metadata: QueuedClipMetadata = QueuedClipMetadata(),
    val uploadParts: List<UploadPart> = emptyList(),
    val capturedAtEpochMs: Long = createdAtEpochMs,
    val capturedTimezone: String = "UTC",
) {
    fun toSharedClip(): SharedClip {
        return SharedClip(
            id = id,
            kind = kind,
            titleHint = titleHint,
            text = text,
            url = url,
            items = items.map { it.toSharedClipItem() },
            mimeType = mimeType,
            sourceApp = sourceApp,
        )
    }

    fun toUploadRecord(): UploadRecord {
        return UploadRecord(
            clip = toSharedClip(),
            status = status,
            message = message,
            remotePath = remotePath,
            createdAtEpochMs = createdAtEpochMs,
            note = note,
            metadata = metadata,
            uploadParts = uploadParts,
        )
    }

    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("kind", kind.name)
        .put("titleHint", titleHint)
        .put("text", text)
        .put("url", url)
        .put("mimeType", mimeType)
        .put("sourceApp", sourceApp)
        .put("note", note)
        .put("status", status.name)
        .put("message", message)
        .put("remotePath", "")
        .put("createdAtEpochMs", createdAtEpochMs)
        .put("capturedAtEpochMs", capturedAtEpochMs)
        .put("capturedTimezone", CaptureTimezone.normalize(capturedTimezone))
        .put("statusUpdatedAtEpochMs", statusUpdatedAtEpochMs)
        .put("metadata", metadata.toJson())
        .put("uploadParts", JSONArray().also { array -> uploadParts.forEach { array.put(it.toJson()) } })
        .put("items", JSONArray().also { array -> items.forEach { array.put(it.toJson()) } })

    companion object {
        fun fromJson(json: JSONObject): QueuedClip {
            val itemsArray = json.optJSONArray("items") ?: JSONArray()
            val items = buildList {
                for (index in 0 until itemsArray.length()) {
                    add(QueuedClipItem.fromJson(itemsArray.getJSONObject(index)))
                }
            }
            val partsArray = json.optJSONArray("uploadParts") ?: JSONArray()
            val uploadParts = buildList {
                for (index in 0 until partsArray.length()) {
                    add(partsArray.getJSONObject(index).toUploadPart())
                }
            }
            return QueuedClip(
                id = json.optString("id"),
                kind = runCatching { ClipKind.valueOf(json.optString("kind")) }.getOrDefault(ClipKind.Unknown),
                titleHint = json.optString("titleHint"),
                text = json.optString("text"),
                url = json.optString("url"),
                mimeType = json.optString("mimeType"),
                sourceApp = json.optString("sourceApp"),
                note = json.optString("note"),
                items = items,
                status = runCatching { UploadStatus.valueOf(json.optString("status")) }.getOrDefault(UploadStatus.Waiting),
                message = json.optString("message"),
                remotePath = "",
                createdAtEpochMs = json.optLong("createdAtEpochMs"),
                capturedAtEpochMs = json.optLong("capturedAtEpochMs", json.optLong("createdAtEpochMs")),
                capturedTimezone = CaptureTimezone.normalize(json.optString("capturedTimezone").ifBlank { "UTC" }),
                statusUpdatedAtEpochMs = json.optLong(
                    "statusUpdatedAtEpochMs",
                    json.optLong("createdAtEpochMs"),
                ),
                metadata = QueuedClipMetadata.fromJson(json.optJSONObject("metadata")),
                uploadParts = uploadParts,
            )
        }
    }
}

private fun UploadPart.toJson(): JSONObject = JSONObject()
    .put("clientRequestId", clientRequestId)
    .put("titleHint", titleHint)
    .put("clientBatchId", clientBatchId)
    .put("parentClientRequestId", parentClientRequestId)
    .put("partIndex", partIndex)
    .put("partCount", partCount)
    .put("partRole", partRole)
    .put("sourceIntent", sourceIntent)
    .put("state", state.name)
    .put("message", message)

private fun JSONObject.toUploadPart(): UploadPart = UploadPart(
    clientRequestId = optString("clientRequestId"),
    titleHint = optString("titleHint"),
    clientBatchId = optString("clientBatchId"),
    parentClientRequestId = optString("parentClientRequestId"),
    partIndex = optInt("partIndex"),
    partCount = optInt("partCount", 1).coerceAtLeast(1),
    partRole = optString("partRole").ifBlank { "single" },
    sourceIntent = optString("sourceIntent").ifBlank { "unknown" },
    state = runCatching { UploadState.valueOf(optString("state")) }.getOrDefault(UploadState.Waiting),
    message = optString("message"),
)

data class QueuedClipMetadata(
    val tags: List<String> = emptyList(),
    val category: String = "",
    val summary: String = "",
    val extractedText: String = "",
    val languageHint: String = "",
    val enrichmentStatus: String = "",
    val enrichmentSummary: String = "",
    val enrichmentTags: List<String> = emptyList(),
    val enrichmentLanguage: String = "",
    val publishStatus: String = NOT_STARTED,
    val reviewStatus: String = NOT_STARTED,
    val routingMode: String = "",
    val knowledgeBaseId: String = "",
    val knowledgeBaseName: String = "",
    val routingDecisionType: String = "",
    val routingReason: String = "",
    val matchedRuleIds: List<String> = emptyList(),
    val manualOverride: Boolean = false,
    val previousKnowledgeBaseId: String = "",
    val reindexStatus: String = "",
    val lineageId: String = "",
    val remoteOriginalPath: String = "",
    val remoteRagflowDocumentId: String = "",
    val remoteArchiveStatus: String = "",
    val ragflowSyncOperation: String = "",
    val ragflowSyncStatus: String = "",
    val ragflowSyncDryRun: Boolean = false,
    val ragflowSyncReason: String = "",
    val ragflowSyncTargetDatasetId: String = "",
    val ragflowSyncDocumentId: String = "",
    val ragflowSyncPlanSummary: String = "",
    val normalizedContractVersion: String = "",
) {
    fun withUploadRemoteFields(
        originalPath: String,
        ragflowDocumentId: String,
        archiveStatus: String,
    ): QueuedClipMetadata {
        return copy(
            remoteOriginalPath = "",
            remoteRagflowDocumentId = ragflowDocumentId.ifBlank { remoteRagflowDocumentId },
            remoteArchiveStatus = archiveStatus.ifBlank { remoteArchiveStatus },
        )
    }

    fun toJson(): JSONObject = JSONObject()
        .put("tags", JSONArray().also { array -> tags.forEach { array.put(it) } })
        .put("category", category)
        .put("summary", summary)
        .put("extractedText", extractedText)
        .put("languageHint", languageHint)
        .put("enrichmentStatus", enrichmentStatus)
        .put("enrichmentSummary", enrichmentSummary)
        .put("enrichmentTags", JSONArray().also { array -> enrichmentTags.forEach { array.put(it) } })
        .put("enrichmentLanguage", enrichmentLanguage)
        .put("publishStatus", publishStatus)
        .put("reviewStatus", reviewStatus)
        .put("routingMode", routingMode)
        .put("knowledgeBaseId", knowledgeBaseId)
        .put("knowledgeBaseName", knowledgeBaseName)
        .put("routingDecisionType", routingDecisionType)
        .put("routingReason", routingReason)
        .put("matchedRuleIds", JSONArray().also { array -> matchedRuleIds.forEach { array.put(it) } })
        .put("manualOverride", manualOverride)
        .put("previousKnowledgeBaseId", previousKnowledgeBaseId)
        .put("reindexStatus", reindexStatus)
        .put("lineageId", lineageId)
        .put("remoteOriginalPath", "")
        .put("remoteRagflowDocumentId", remoteRagflowDocumentId)
        .put("remoteArchiveStatus", remoteArchiveStatus)
        .put("ragflowSyncOperation", ragflowSyncOperation)
        .put("ragflowSyncStatus", ragflowSyncStatus)
        .put("ragflowSyncDryRun", ragflowSyncDryRun)
        .put("ragflowSyncReason", ragflowSyncReason)
        .put("ragflowSyncTargetDatasetId", ragflowSyncTargetDatasetId)
        .put("ragflowSyncDocumentId", ragflowSyncDocumentId)
        .put("ragflowSyncPlanSummary", ragflowSyncPlanSummary)
        .put("normalizedContractVersion", normalizedContractVersion)

    companion object {
        const val NOT_STARTED = "not_started"

        fun fromJson(json: JSONObject?): QueuedClipMetadata {
            if (json == null) return QueuedClipMetadata()
            return QueuedClipMetadata(
                tags = json.optStringArray("tags"),
                category = json.optString("category"),
                summary = json.optString("summary"),
                extractedText = json.optString("extractedText"),
                languageHint = json.optString("languageHint"),
                enrichmentStatus = json.optString("enrichmentStatus"),
                enrichmentSummary = json.optString("enrichmentSummary").ifBlank { json.optString("summary") },
                enrichmentTags = json.optStringArray("enrichmentTags").ifEmpty { json.optStringArray("tags") },
                enrichmentLanguage = json.optString("enrichmentLanguage").ifBlank { json.optString("languageHint") },
                publishStatus = json.optString("publishStatus").ifBlank { NOT_STARTED },
                reviewStatus = json.optString("reviewStatus").ifBlank { NOT_STARTED },
                routingMode = json.optString("routingMode"),
                knowledgeBaseId = json.optString("knowledgeBaseId"),
                knowledgeBaseName = json.optString("knowledgeBaseName"),
                routingDecisionType = json.optString("routingDecisionType"),
                routingReason = json.optString("routingReason"),
                matchedRuleIds = json.optStringArray("matchedRuleIds"),
                manualOverride = json.optBoolean("manualOverride", false),
                previousKnowledgeBaseId = json.optString("previousKnowledgeBaseId"),
                reindexStatus = json.optString("reindexStatus"),
                lineageId = json.optString("lineageId"),
                remoteOriginalPath = "",
                remoteRagflowDocumentId = json.optString("remoteRagflowDocumentId"),
                remoteArchiveStatus = json.optString("remoteArchiveStatus"),
                ragflowSyncOperation = json.optString("ragflowSyncOperation"),
                ragflowSyncStatus = json.optString("ragflowSyncStatus"),
                ragflowSyncDryRun = json.optBoolean("ragflowSyncDryRun", false),
                ragflowSyncReason = json.optString("ragflowSyncReason"),
                ragflowSyncTargetDatasetId = json.optString("ragflowSyncTargetDatasetId"),
                ragflowSyncDocumentId = json.optString("ragflowSyncDocumentId"),
                ragflowSyncPlanSummary = json.optString("ragflowSyncPlanSummary"),
                normalizedContractVersion = json.optString("normalizedContractVersion"),
            )
        }

        private fun JSONObject.optStringArray(name: String): List<String> {
            val array = optJSONArray(name) ?: return emptyList()
            return buildList {
                for (index in 0 until array.length()) {
                    val value = array.optString(index)
                    if (value.isNotBlank()) {
                        add(value)
                    }
                }
            }
        }
    }
}

data class QueuedClipItem(
    val cachedPath: String,
    val displayName: String,
    val mimeType: String,
    val sizeBytes: Long?,
) {
    fun toSharedClipItem(): SharedClipItem {
        return SharedClipItem(
            uri = android.net.Uri.fromFile(File(cachedPath)),
            displayName = displayName,
            mimeType = mimeType,
            sizeBytes = sizeBytes,
        )
    }

    fun toJson(): JSONObject = JSONObject()
        .put("cachedPath", cachedPath)
        .put("displayName", displayName)
        .put("mimeType", mimeType)
        .put("sizeBytes", sizeBytes ?: JSONObject.NULL)

    companion object {
        fun fromJson(json: JSONObject): QueuedClipItem {
            return QueuedClipItem(
                cachedPath = json.optString("cachedPath"),
                displayName = json.optString("displayName"),
                mimeType = json.optString("mimeType"),
                sizeBytes = if (json.isNull("sizeBytes")) null else json.optLong("sizeBytes"),
            )
        }
    }
}
