package com.sudox.perclip.knowledge

private val PUBLIC_CLIP_ID = Regex("pc_[0-9a-f]{32}")

data class TopicLabel(
    val id: String,
    val displayName: String,
)

data class ClipTopicAssignment(
    val primary: TopicLabel = TopicLabel("unclassified", "待归类"),
    val secondary: List<TopicLabel> = emptyList(),
    val entities: List<String> = emptyList(),
    val keywords: List<String> = emptyList(),
    val unclassified: Boolean = true,
    val manualOverride: Boolean = false,
    val topicDisabled: Boolean = false,
) {
    /** Knowledge cards deliberately show no more than two topic chips. */
    val cardTopics: List<TopicLabel>
        get() = (listOf(primary) + secondary).distinctBy(TopicLabel::id).take(2)

    val statusLabel: String
        get() = if (topicDisabled) "该主题已停用" else ""

    /** A disabled historical assignment remains visible but is correction-only. */
    val correctionOnly: Boolean
        get() = topicDisabled
}

data class KnowledgeTopicClip(
    val clipId: String,
    val title: String,
    val summary: String = "",
    val source: String = "",
    val capturedAt: String = "",
    val originalText: String = "",
    val textPreview: String = "",
    val safeDisplayUrl: String = "",
    val tags: List<String> = emptyList(),
    val topicAssignment: ClipTopicAssignment = ClipTopicAssignment(),
) {
    init {
        require(PUBLIC_CLIP_ID.matches(clipId)) { "clip identity must be public" }
    }
}

data class KnowledgeTopicPage(
    val knowledgeBaseId: String,
    val knowledgeBaseName: String,
    val items: List<KnowledgeTopicClip>,
    val nextCursor: String = "",
)

data class KnowledgeTopicDetail(
    val clip: KnowledgeTopicClip,
)

data class TopicRegistry(
    val topics: List<TopicLabel>,
) {
    val selectableTopics: List<TopicLabel>
        get() = topics.filterNot { it.id == "unclassified" }
}
