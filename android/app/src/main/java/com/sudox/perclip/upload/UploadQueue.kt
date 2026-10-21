package com.sudox.perclip.upload

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.sudox.perclip.SharedClip
import com.sudox.perclip.config.PerClipSettingsStore
import com.sudox.perclip.data.ClipQueueStore
import com.sudox.perclip.data.QueuedClip
import com.sudox.perclip.data.QueuedClipItem
import com.sudox.perclip.data.QueuedClipMetadata
import java.io.File
import java.time.ZoneId
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.TimeUnit

class UploadQueue(context: Context) {
    private val appContext = context.applicationContext
    private val queueStore = ClipQueueStore(appContext)
    private val cache = ClipPayloadCache(appContext)
    private val workManager = WorkManager.getInstance(appContext)
    private val settingsStore = PerClipSettingsStore(appContext)

    init {
        val firstQueueInProcess = processRecoveryClaim.compareAndSet(false, true)
        queueStore.recoverStaleUploading(
            staleAfterMs = UploadProcessRecoveryPolicy.staleAfterMs(firstQueueInProcess),
        ).forEach { enqueueWork(it) }
    }

    fun enqueue(
        clip: SharedClip,
        note: String,
        metadata: QueuedClipMetadata = QueuedClipMetadata(),
    ): QueuedClip {
        val now = System.currentTimeMillis()
        val capturedTimezone = CaptureTimezone.normalize(ZoneId.systemDefault().id)
        if (clip.items.size > 100) {
            val failedClip = UploadQueueEnqueueFailure.failedTooManyItemsClip(clip, note, now, metadata)
            cleanupPrunedClips(queueStore.upsert(failedClip))
            return failedClip
        }
        val plannedParts = planParts(clip)
        val cachedPaths = clip.items.mapIndexed { index, item ->
            val prefix = CachedPayloadFiles.captureRequestPrefix(clip.id, index)
            runCatching { cache.copyToCache(item, prefix).absolutePath }.getOrDefault("")
        }
        val queuedItems = clip.items.mapIndexed { index, item ->
            QueuedClipItem(
                cachedPath = cachedPaths[index],
                displayName = item.displayName,
                mimeType = item.mimeType,
                sizeBytes = item.sizeBytes,
            )
        }
        val uploadParts = if (clip.items.isEmpty()) {
            plannedParts
        } else {
            UploadEnqueuePartPlanner.applyCacheResults(plannedParts, cachedPaths)
        }
        val aggregateStatus = UploadPartAggregate.status(uploadParts)
        val waitingClip = QueuedClip(
            id = clip.id,
            kind = clip.kind,
            titleHint = clip.titleHint,
            text = clip.text,
            url = clip.url,
            mimeType = clip.mimeType,
            sourceApp = clip.sourceApp,
            note = ClipNoteSanitizer.normalize(note),
            items = queuedItems,
            status = aggregateStatus,
            message = if (aggregateStatus == UploadStatus.Failed) UploadQueueEnqueueFailure.CACHE_READ_FAILED_MESSAGE else "",
            remotePath = "",
            createdAtEpochMs = now,
            statusUpdatedAtEpochMs = now,
            metadata = metadata,
            uploadParts = uploadParts,
            capturedAtEpochMs = now,
            capturedTimezone = capturedTimezone,
        )
        val settings = settingsStore.load().normalized()
        val queuedClip = waitingClip.copy(
            message = if (aggregateStatus == UploadStatus.Waiting) {
                UploadNetworkPolicy.describeWaitingState(
                    clip = waitingClip,
                    wifiOnlyLargeFiles = settings.wifiOnlyLargeFiles,
                    uploadConfigured = settings.hasUploadConfig,
                )
            } else {
                waitingClip.message
            },
        )
        cleanupPrunedClips(queueStore.upsert(queuedClip))
        if (settings.hasUploadConfig && queuedClip.uploadParts.any { it.state == UploadState.Waiting }) {
            enqueueWork(queuedClip)
        }
        return queuedClip
    }

    fun retry(id: String) {
        val clip = queueStore.find(id) ?: return
        if (!UploadRetryEligibility.canRetry(clip)) return
        val withParts = if (clip.uploadParts.isEmpty()) clip.copy(uploadParts = planParts(clip.toSharedClip())) else clip
        val prepared = UploadManualRetryPlanner.prepare(withParts) { item -> File(item.cachedPath).isFile }
        cleanupPrunedClips(queueStore.upsert(prepared))
        if (prepared.uploadParts.none { it.state == UploadState.Waiting }) return
        val settings = settingsStore.load().normalized()
        val message = UploadNetworkPolicy.describeWaitingState(
            clip = prepared,
            wifiOnlyLargeFiles = settings.wifiOnlyLargeFiles,
            uploadConfigured = settings.hasUploadConfig,
        )
        queueStore.updateStatus(id, UploadStatus.Waiting, message)
        if (settings.hasUploadConfig) {
            enqueueWork(prepared)
        }
    }

    fun recent(): List<UploadRecord> = queueStore.recent().map { it.toUploadRecord() }

    fun updateMetadata(id: String, transform: (QueuedClipMetadata) -> QueuedClipMetadata): UploadRecord? {
        return queueStore.updateMetadata(id, transform)?.toUploadRecord()
    }

    fun refreshWaitingNetworkPolicy(): List<UploadRecord> {
        return refreshWaitingNetworkPolicyWithResult().records
    }

    fun refreshWaitingNetworkPolicyWithResult(): UploadQueueRefreshOutcome {
        val currentClips = queueStore.all()
        val settings = settingsStore.load().normalized()
        val refreshedClips = UploadQueueRefresh.refreshWaitingMessages(
            clips = currentClips,
            wifiOnlyLargeFiles = settings.wifiOnlyLargeFiles,
            uploadConfigured = settings.hasUploadConfig,
            nowEpochMs = System.currentTimeMillis(),
        )
        if (refreshedClips != currentClips) {
            queueStore.replaceAll(refreshedClips)
        }
        val waitingClipsToRequeue = UploadQueueRefresh.waitingClipsToRequeue(
            clips = refreshedClips,
            uploadConfigured = settings.hasUploadConfig,
        )
        waitingClipsToRequeue.forEach { clip ->
            enqueueWork(clip)
        }
        return UploadQueueRefreshOutcome(
            records = recent(),
            requeuedCount = waitingClipsToRequeue.size,
        )
    }

    fun delete(id: String) {
        workManager.cancelUniqueWork("upload-$id")
        val removed = queueStore.remove(id) ?: return
        CachedPayloadCleaner.deleteCachedPayloads(removed, appContext.cacheDir)
    }

    private fun enqueueWork(clip: QueuedClip) {
        val networkType = UploadNetworkPolicy.requiredNetworkType(
            clip = clip,
            wifiOnlyLargeFiles = settingsStore.load().wifiOnlyLargeFiles,
        )
        val request = OneTimeWorkRequestBuilder<UploadWorker>()
            .setInputData(Data.Builder().putString(UploadWorker.KEY_CLIP_ID, clip.id).build())
            .setConstraints(Constraints(requiredNetworkType = networkType))
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        workManager.enqueueUniqueWork("upload-${clip.id}", ExistingWorkPolicy.REPLACE, request)
    }

    private fun planParts(clip: SharedClip): List<UploadPart> {
        if (clip.items.isEmpty()) {
            return listOf(UploadPartPlanner.toUploadPart(UploadPartPlanner.forClip(clip)))
        }
        return clip.items.mapIndexed { index, item ->
            UploadPartPlanner.toUploadPart(
                UploadPartPlanner.forItem(
                    clip = clip,
                    displayName = item.displayName,
                    mimeType = item.mimeType,
                    itemIndex = index,
                    totalItems = clip.items.size,
                ),
            )
        }
    }

    private fun cleanupPrunedClips(clips: List<QueuedClip>) {
        clips.forEach { clip ->
            workManager.cancelUniqueWork("upload-${clip.id}")
            CachedPayloadCleaner.deleteCachedPayloads(clip, appContext.cacheDir)
        }
    }

    companion object {
        private val processRecoveryClaim = AtomicBoolean(false)
    }
}

object UploadProcessRecoveryPolicy {
    fun staleAfterMs(firstQueueInProcess: Boolean): Long {
        return if (firstQueueInProcess) 0L else ClipQueueStore.STALE_UPLOADING_AFTER_MS
    }
}

data class UploadQueueRefreshOutcome(
    val records: List<UploadRecord>,
    val requeuedCount: Int,
)
