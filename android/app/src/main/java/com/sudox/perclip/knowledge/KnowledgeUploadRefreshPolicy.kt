package com.sudox.perclip.knowledge

object KnowledgeUploadRefreshPolicy {
    fun shouldRefresh(
        completionRevision: Int,
        handledRevision: Int,
        mode: KnowledgeReadMode,
        scope: KnowledgeLibraryScope,
    ): Boolean = completionRevision > handledRevision &&
        mode == KnowledgeReadMode.V2_LOCAL_FIRST &&
        scope != KnowledgeLibraryScope.Unassigned

    fun handledRevision(completionRevision: Int, handledRevision: Int): Int =
        maxOf(completionRevision, handledRevision)
}
