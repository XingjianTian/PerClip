package com.sudox.perclip.knowledge

import com.sudox.perclip.data.QueuedClipMetadata
import org.junit.Assert.assertEquals
import org.junit.Test

class ClipSyncStatusLocalMetadataUpdaterTest {
    @Test
    fun `parses and applies read-only sync fields`() {
        val sync = KnowledgeBaseJson.parseRagflowSyncStatus(
            """{"ok":true,"sync":{"operation":"update_meta_fields","status":"completed","dry_run":false,"reason":"done","ragflow_dataset_id":"dataset","ragflow_document_id":"document","plan":{"summary":"summary"}}}""",
        )
        val enrichment = KnowledgeBaseJson.parseEnrichmentStatus(
            """{"ok":true,"enrichment":{"status":"completed","summary":"summary","tags":["tag"],"language":"en","extracted_text":"text"}}""",
        )

        val metadata = ClipSyncStatusLocalMetadataUpdater.apply(QueuedClipMetadata(), sync, enrichment)

        assertEquals("completed", metadata.ragflowSyncStatus)
        assertEquals("document", metadata.ragflowSyncDocumentId)
        assertEquals("text", metadata.extractedText)
    }

    @Test
    fun `missing remote values preserve existing metadata`() {
        val metadata = ClipSyncStatusLocalMetadataUpdater.apply(
            QueuedClipMetadata(ragflowSyncStatus = "planned", enrichmentSummary = "local"),
            null,
            null,
        )

        assertEquals("planned", metadata.ragflowSyncStatus)
        assertEquals("local", metadata.enrichmentSummary)
    }
}
