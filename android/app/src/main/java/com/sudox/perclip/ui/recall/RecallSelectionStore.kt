package com.sudox.perclip.ui.recall

import android.content.Context

internal data class RecallSelection(
    val activeTopicId: String = "",
    val scope: RecallScope = RecallScope.ALL_TOPICS,
    val knowledgeBaseId: String = "",
)

internal object RecallSelectionStore {
    private const val FILE_NAME = "perclip_recall_selection"
    private const val ACTIVE_TOPIC_ID = "active_topic_id"
    private const val SCOPE = "scope"
    private const val KNOWLEDGE_BASE_ID = "knowledge_base_id"

    fun load(context: Context): RecallSelection {
        val values = context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
        val scope = runCatching {
            RecallScope.valueOf(values.getString(SCOPE, null).orEmpty())
        }.getOrDefault(RecallScope.ALL_TOPICS)
        return RecallSelection(
            activeTopicId = values.getString(ACTIVE_TOPIC_ID, "").orEmpty(),
            scope = scope,
            knowledgeBaseId = values.getString(KNOWLEDGE_BASE_ID, "").orEmpty(),
        )
    }

    fun save(context: Context, presentation: RecallPresentationState) {
        context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(ACTIVE_TOPIC_ID, presentation.activeTopicId)
            .putString(SCOPE, presentation.scope.name)
            .putString(KNOWLEDGE_BASE_ID, presentation.knowledgeBaseId)
            .apply()
    }
}
