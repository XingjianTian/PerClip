package com.sudox.perclip.knowledge

import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus

sealed interface KnowledgeLibraryScope {
    data object All : KnowledgeLibraryScope
    data class Specific(val knowledgeBaseId: String) : KnowledgeLibraryScope
    data object Unassigned : KnowledgeLibraryScope
}

enum class KnowledgeBaseRemoteListState {
    NOT_LOADED,
    LOADING,
    SUCCESS,
    FAILED,
}

object KnowledgeLibraryScopes {
    fun filter(records: List<UploadRecord>, scope: KnowledgeLibraryScope): List<UploadRecord> = when (scope) {
        KnowledgeLibraryScope.All -> records
        is KnowledgeLibraryScope.Specific -> records.filter { it.metadata.knowledgeBaseId == scope.knowledgeBaseId }
        KnowledgeLibraryScope.Unassigned -> records.filter {
            it.status != UploadStatus.Uploaded ||
                it.metadata.knowledgeBaseId.isBlank() ||
                it.metadata.routingDecisionType.isBlank()
        }
    }

    fun activeChoices(
        remote: List<KnowledgeBaseSummary>,
        records: List<UploadRecord>,
        remoteState: KnowledgeBaseRemoteListState = KnowledgeBaseRemoteListState.NOT_LOADED,
    ): List<KnowledgeBaseSummary> {
        val activeRemote = remote.filterNot { it.isArchived || it.deletedAt.isNotBlank() }
        if (remoteState == KnowledgeBaseRemoteListState.SUCCESS) {
            return activeRemote.sortedWith(
                compareByDescending<KnowledgeBaseSummary> { it.isDefault }.thenBy { it.displayName.lowercase() },
            )
        }
        val remoteIds = activeRemote.mapTo(mutableSetOf()) { it.id }
        val localOnly = records.asSequence()
            .map { it.metadata }
            .filter { it.knowledgeBaseId.isNotBlank() && it.knowledgeBaseId !in remoteIds }
            .distinctBy { it.knowledgeBaseId }
            .map { KnowledgeBaseSummary(id = it.knowledgeBaseId, name = it.knowledgeBaseName.ifBlank { "本地已知知识库" }) }
            .toList()
        return (activeRemote + localOnly).sortedWith(
            compareByDescending<KnowledgeBaseSummary> { it.isDefault }.thenBy { it.displayName.lowercase() },
        )
    }

    fun recentlySavedInScope(
        records: List<UploadRecord>,
        recentlySavedClipId: String?,
        scope: KnowledgeLibraryScope,
    ): UploadRecord? = filter(records, scope).firstOrNull { it.clip.id == recentlySavedClipId }

    fun resolveSelection(
        selected: KnowledgeLibraryScope,
        choices: List<KnowledgeBaseSummary>,
    ): KnowledgeLibraryScope {
        return if (selected is KnowledgeLibraryScope.Specific && choices.none { it.id == selected.knowledgeBaseId }) {
            KnowledgeLibraryScope.All
        } else {
            selected
        }
    }

    fun hasUnassigned(records: List<UploadRecord>): Boolean =
        filter(records, KnowledgeLibraryScope.Unassigned).isNotEmpty()

    fun emptyTitle(scope: KnowledgeLibraryScope): String =
        if (scope == KnowledgeLibraryScope.All) "还没有闪记" else "当前知识库还没有闪记"

    fun emptyBody(scope: KnowledgeLibraryScope): String =
        if (scope == KnowledgeLibraryScope.All) "从其它 App 分享内容到 PerClip 后，记录会出现在这里。"
        else "切换到“全部”或其它知识库查看内容。"
}
