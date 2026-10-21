package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.data.QueuedClipMetadata
import org.junit.Assert.assertEquals
import org.junit.Test

class ClipLibraryFilterTest {
    @Test
    fun blankSearchReturnsFullList() {
        val records = listOf(record(id = "a"), record(id = "b"))

        assertEquals(records, ClipLibraryFilter.apply(records, ClipLibraryQuery(text = " ")))
    }

    @Test
    fun searchesByTitle() {
        val records = listOf(record(id = "match", title = "项目方案"), record(id = "other", title = "Other"))

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "方案")).ids())
    }

    @Test
    fun searchesByBodyText() {
        val records = listOf(record(id = "match", text = "正文里有重点"), record(id = "other"))

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "重点")).ids())
    }

    @Test
    fun searchesByUrl() {
        val records = listOf(record(id = "match", url = "https://example.com/read"), record(id = "other"))

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "example.com")).ids())
    }

    @Test
    fun searchesByNote() {
        val records = listOf(record(id = "match", note = "复习材料"), record(id = "other"))

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "复习")).ids())
    }

    @Test
    fun searchesBySourceApp() {
        val records = listOf(record(id = "match", sourceApp = "Chrome"), record(id = "other"))

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "chrome")).ids())
    }

    @Test
    fun searchesByTag() {
        val records = listOf(
            record(id = "match", metadata = QueuedClipMetadata(tags = listOf("research"))),
            record(id = "other"),
        )

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "research")).ids())
    }

    @Test
    fun searchesByCategory() {
        val records = listOf(
            record(id = "match", metadata = QueuedClipMetadata(category = "论文")),
            record(id = "other"),
        )

        assertEquals(listOf("match"), ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "论文")).ids())
    }

    @Test
    fun filtersByUploadStatus() {
        val records = listOf(
            record(id = "waiting", status = UploadStatus.Waiting),
            record(id = "uploaded", status = UploadStatus.Uploaded),
            record(id = "failed", status = UploadStatus.Failed),
        )

        assertEquals(
            listOf("uploaded"),
            ClipLibraryFilter.apply(
                records,
                ClipLibraryQuery(statusFilter = ClipLibraryStatusFilter.Uploaded),
            ).ids(),
        )
    }

    @Test
    fun filtersByContentType() {
        val records = listOf(
            record(id = "text", kind = ClipKind.Text),
            record(id = "url", kind = ClipKind.Url),
            record(id = "file", kind = ClipKind.File),
            record(id = "screen", kind = ClipKind.ScreenClip),
        )

        assertEquals(
            listOf("screen"),
            ClipLibraryFilter.apply(
                records,
                ClipLibraryQuery(typeFilter = ClipLibraryTypeFilter.ScreenClip),
            ).ids(),
        )
    }

    @Test
    fun oldEmptyMetadataDoesNotBreakFiltering() {
        val records = listOf(record(id = "legacy"))

        assertEquals(
            listOf("legacy"),
            ClipLibraryFilter.apply(records, ClipLibraryQuery(text = "", typeFilter = ClipLibraryTypeFilter.Text)).ids(),
        )
    }

    private fun List<UploadRecord>.ids(): List<String> = map { it.clip.id }

    private fun record(
        id: String,
        kind: ClipKind = ClipKind.Text,
        title: String = id,
        text: String = "",
        url: String = "",
        sourceApp: String = "",
        note: String = "",
        status: UploadStatus = UploadStatus.Waiting,
        metadata: QueuedClipMetadata = QueuedClipMetadata(),
    ): UploadRecord {
        return UploadRecord(
            clip = SharedClip(
                id = id,
                kind = kind,
                titleHint = title,
                text = text,
                url = url,
                sourceApp = sourceApp,
            ),
            status = status,
            message = status.name,
            note = note,
            metadata = metadata,
        )
    }
}
