package com.sudox.perclip.knowledge

import com.sudox.perclip.data.QueuedClipMetadata

object ClipSyncStatusLocalMetadataUpdater {
    fun apply(
        metadata: QueuedClipMetadata,
        sync: RagflowSyncStatusResponse?,
        enrichment: EnrichmentStatusResponse?,
    ): QueuedClipMetadata = metadata.copy(
        enrichmentStatus = enrichment?.status ?: metadata.enrichmentStatus,
        enrichmentSummary = enrichment?.summary ?: metadata.enrichmentSummary,
        enrichmentTags = enrichment?.tags ?: metadata.enrichmentTags,
        enrichmentLanguage = enrichment?.language ?: metadata.enrichmentLanguage,
        extractedText = enrichment?.extractedText ?: metadata.extractedText,
        ragflowSyncOperation = sync?.operation ?: metadata.ragflowSyncOperation,
        ragflowSyncStatus = sync?.status ?: metadata.ragflowSyncStatus,
        ragflowSyncDryRun = sync?.dryRun ?: metadata.ragflowSyncDryRun,
        ragflowSyncReason = sync?.reason ?: metadata.ragflowSyncReason,
        ragflowSyncTargetDatasetId = sync?.targetDatasetId ?: metadata.ragflowSyncTargetDatasetId,
        ragflowSyncDocumentId = sync?.documentId ?: metadata.ragflowSyncDocumentId,
        ragflowSyncPlanSummary = sync?.planSummary ?: metadata.ragflowSyncPlanSummary,
    )
}
