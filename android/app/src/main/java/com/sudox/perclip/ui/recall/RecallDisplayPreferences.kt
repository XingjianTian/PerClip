package com.sudox.perclip.ui.recall

import android.content.Context

internal data class RecallDisplayPreferences(
    val visibleTopicCount: Int = 5,
    val visibleMemoryLabels: Int = 5,
    val hiddenTopicIds: Set<String> = emptySet(),
)

internal object RecallDisplayPreferenceStore {
    private const val FILE_NAME = "perclip_recall_display"
    private const val TOPIC_COUNT = "visible_topic_count"
    private const val MEMORY_COUNT = "visible_memory_count"
    private const val HIDDEN_TOPICS = "hidden_topic_ids"

    fun load(context: Context): RecallDisplayPreferences {
        val values = context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
        return RecallDisplayPreferences(
            visibleTopicCount = values.getInt(TOPIC_COUNT, 5).coerceIn(1, 5),
            visibleMemoryLabels = values.getInt(MEMORY_COUNT, 5).coerceIn(1, 5),
            hiddenTopicIds = values.getStringSet(HIDDEN_TOPICS, emptySet()).orEmpty().toSet(),
        )
    }

    fun save(context: Context, presentation: RecallPresentationState) {
        context.getSharedPreferences(FILE_NAME, Context.MODE_PRIVATE)
            .edit()
            .putInt(TOPIC_COUNT, presentation.visibleTopicCount.coerceIn(1, 5))
            .putInt(MEMORY_COUNT, presentation.visibleMemoryLabels.coerceIn(1, 5))
            .putStringSet(HIDDEN_TOPICS, presentation.hiddenTopicIds)
            .apply()
    }
}
