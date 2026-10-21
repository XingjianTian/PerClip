package com.sudox.perclip.upload

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.data.ClipQueueStore
import com.sudox.perclip.data.QueuedClip
import java.io.File

class UploadWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val clipId = inputData.getString(KEY_CLIP_ID) ?: return Result.failure()
        val queueStore = ClipQueueStore(applicationContext)
        val settings = PerClipSettingsStore(applicationContext).load()
        val queuedClip = queueStore.find(clipId) ?: return Result.failure()
        val api = PersonalClipsApi()
        val clip = queuedClip.toSharedClip()
        val normalizedSettings = settings.normalized()

        if (!normalizedSettings.hasUploadConfig) {
            queueStore.updateStatus(
                clipId,
                UploadStatus.Waiting,
                UploadNetworkPolicy.CONFIG_MISSING_MESSAGE,
            )
            return Result.success()
        }

        val targetKnowledgeBaseId = UploadWorkerKnowledgeBaseTarget.fromQueuedClip(queuedClip)
        val plannedParts = if (queuedClip.uploadParts.isNotEmpty()) {
            queuedClip.uploadParts
        } else if (queuedClip.items.isEmpty()) {
            listOf(UploadPartPlanner.toUploadPart(UploadPartPlanner.forClip(clip)))
        } else {
            queuedClip.items.mapIndexed { index, item ->
                UploadPartPlanner.toUploadPart(
                    UploadPartPlanner.forItem(
                        clip = clip,
                        displayName = item.displayName,
                        mimeType = item.mimeType,
                        itemIndex = index,
                        totalItems = queuedClip.items.size,
                    ),
                )
            }
        }
        if (queuedClip.uploadParts.isEmpty()) {
            queueStore.replaceUploadParts(clipId, plannedParts)
        }
        val pendingParts = UploadPartPlanner.pendingParts(plannedParts)
        if (pendingParts.isEmpty()) {
            val status = UploadPartAggregate.status(plannedParts)
            queueStore.updateStatus(
                clipId,
                status,
                if (status == UploadStatus.Uploaded) "已保存，后台处理完成。" else "没有可重试的本地内容。",
            )
            if (status == UploadStatus.Uploaded) {
                CachedPayloadCleaner.deleteCachedPayloads(queuedClip, applicationContext.cacheDir)
                return Result.success()
            }
            return Result.failure()
        }

        queueStore.updateStatus(clipId, UploadStatus.Uploading, "正在后台同步")

        val attempted = mutableListOf<Pair<UploadPart, UploadResult>>()
        pendingParts.forEach { part ->
            queueStore.updateUploadPart(clipId, part.clientRequestId, UploadState.Uploading)
            val item = queuedClip.items.getOrNull(part.partIndex)
            val result = api.upload(
                settings = settings,
                clip = clip,
                note = queuedClip.note,
                item = item?.toSharedClipItem(),
                cachedFile = item?.let { File(it.cachedPath) },
                clientRequestId = part.clientRequestId,
                titleHint = part.titleHint,
                capture = UploadPartPlanner.toMetadata(part),
                targetKnowledgeBaseId = targetKnowledgeBaseId,
                routingMode = queuedClip.metadata.routingMode,
                capturedAtEpochMs = queuedClip.capturedAtEpochMs,
                capturedTimezone = queuedClip.capturedTimezone,
            )
            attempted += part to result
            if (result.ok) {
                queueStore.updateUploadPart(clipId, part.clientRequestId, UploadState.Uploaded)
            }
        }

        val failures = attempted.filter { !it.second.ok }
        val failureDisposition = if (failures.isNotEmpty()) {
            val disposition = UploadBatchFailurePolicy.evaluate(
                failures = failures,
                runAttemptCount = runAttemptCount,
                maxRetryAttempts = MAX_RETRY_ATTEMPTS,
            )
            disposition.parts.forEach { part ->
                queueStore.updateUploadPart(
                    clipId,
                    part.clientRequestId,
                    part.state,
                    part.message,
                )
            }
            disposition
        } else null

        val results = attempted.map { it.second }
        val remoteResult = results.firstOrNull {
            it.ragflowDocumentId.isNotBlank() || it.archiveStatus.isNotBlank()
        }
        val latest = queueStore.find(clipId) ?: return Result.failure()
        return when (UploadPartAggregate.status(latest.uploadParts)) {
            UploadStatus.Uploaded -> {
                queueStore.updateStatus(
                    id = clipId,
                    status = UploadStatus.Uploaded,
                    message = if (latest.uploadParts.size > 1) "已保存 ${latest.uploadParts.size} 个内容，后台处理完成。" else "已保存，后台处理完成。",
                    remoteRagflowDocumentId = remoteResult?.ragflowDocumentId.orEmpty(),
                    remoteArchiveStatus = remoteResult?.archiveStatus.orEmpty(),
                )
                CachedPayloadCleaner.deleteCachedPayloads(latest, applicationContext.cacheDir)
                Result.success()
            }
            UploadStatus.Waiting, UploadStatus.Uploading -> {
                queueStore.updateStatus(
                    clipId,
                    UploadStatus.Waiting,
                    failureDisposition?.message ?: "仍有内容等待后台同步。",
                )
                Result.retry()
            }
            UploadStatus.Failed -> {
                queueStore.updateStatus(
                    clipId,
                    UploadStatus.Failed,
                    failureDisposition?.message ?: UploadManualRetryPlanner.MISSING_PAYLOAD_MESSAGE,
                )
                Result.failure()
            }
        }
    }

    companion object {
        const val KEY_CLIP_ID = "clip_id"
        private const val MAX_RETRY_ATTEMPTS = 3
    }
}

internal object UploadWorkerKnowledgeBaseTarget {
    fun fromQueuedClip(queuedClip: QueuedClip): String = queuedClip.metadata.knowledgeBaseId.trim()
}
