package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClipItem

enum class ClipLibraryStatusFilter(val label: String) {
    All("全部"),
    Waiting("待处理"),
    Uploading("同步中"),
    Uploaded("已保存"),
    Failed("失败"),
    ;

    fun matches(record: UploadRecord): Boolean {
        return when (this) {
            All -> true
            Waiting -> record.status == UploadStatus.Waiting || record.status == UploadStatus.Uploading
            Uploading -> record.status == UploadStatus.Uploading
            Uploaded -> record.status == UploadStatus.Uploaded
            Failed -> record.status == UploadStatus.Failed
        }
    }
}

enum class ClipLibraryTypeFilter(val label: String) {
    All("全部"),
    Text("text"),
    Url("url"),
    Image("image"),
    File("file"),
    ScreenClip("screen_clip"),
    ;

    fun matches(record: UploadRecord): Boolean {
        return when (this) {
            All -> true
            Text -> record.clip.kind == ClipKind.Text
            Url -> record.clip.kind == ClipKind.Url
            Image -> record.clip.kind == ClipKind.Image
            File -> record.clip.kind == ClipKind.File || record.clip.kind == ClipKind.Multiple
            ScreenClip -> record.clip.kind == ClipKind.ScreenClip
        }
    }
}

data class ClipLibraryQuery(
    val text: String = "",
    val statusFilter: ClipLibraryStatusFilter = ClipLibraryStatusFilter.All,
    val typeFilter: ClipLibraryTypeFilter = ClipLibraryTypeFilter.All,
)

object ClipLibraryFilter {
    fun apply(records: List<UploadRecord>, query: ClipLibraryQuery): List<UploadRecord> {
        val normalizedSearch = query.text.trim().lowercase()
        return records.filter { record ->
            query.statusFilter.matches(record) &&
                query.typeFilter.matches(record) &&
                (normalizedSearch.isBlank() || searchableText(record).contains(normalizedSearch))
        }
    }

    private fun searchableText(record: UploadRecord): String {
        val clip = record.clip
        val metadata = record.metadata
        return buildList {
            add(clip.titleHint)
            add(clip.text)
            add(record.note)
            add(clip.url)
            add(clip.sourceApp)
            add(metadata.category)
            addAll(metadata.tags)
            add(metadata.enrichmentSummary)
            addAll(metadata.enrichmentTags)
            add(metadata.enrichmentLanguage)
            addAll(clip.items.flatMap { it.searchFields() })
        }.joinToString("\n").lowercase()
    }

    private fun SharedClipItem.searchFields(): List<String> {
        return listOf(displayName, mimeType)
    }
}
