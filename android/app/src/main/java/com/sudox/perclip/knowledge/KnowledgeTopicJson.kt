package com.sudox.perclip.knowledge

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

object KnowledgeTopicJson {
    const val QUALITY_CONTRACT = "perclip.quality-read.v1"
    const val TOPIC_CONTRACT = "perclip.topic-assignment.v1"
    const val KNOWLEDGE_LIST_CONTRACT = "perclip.knowledge-list.v2"

    fun parseKnowledgeList(bodyText: String): KnowledgeListPage {
        val root = knowledgeRoot(bodyText)
        val summary = parseKnowledgeSummaryObject(root.getJSONObject("summary"))
        return KnowledgeListPage(
            scopeKnowledgeBaseIds = root.getJSONObject("scope").optJSONArray("knowledge_base_ids").strings(),
            summary = summary,
            items = root.optJSONArray("items").objects(::parseKnowledgeListItem),
            nextCursor = root.optNullableString("next_cursor"),
            hasMore = root.optBoolean("has_more", false),
        )
    }

    fun parseKnowledgeSummary(bodyText: String): KnowledgeListSummary =
        parseKnowledgeSummaryObject(knowledgeRoot(bodyText).getJSONObject("summary"))

    fun parseKnowledgeChanges(bodyText: String): KnowledgeChangePage {
        val root = knowledgeRoot(bodyText)
        return KnowledgeChangePage(
            changes = root.optJSONArray("changes").objects { value ->
                KnowledgeChange(
                    revision = value.getLong("revision"),
                    publicClipId = value.getString("public_clip_id"),
                    knowledgeBaseId = value.optString("knowledge_base_id"),
                    knowledgeBaseIds = value.optJSONArray("knowledge_base_ids").strings(),
                    operation = value.getString("operation"),
                    sourceOperation = value.optString("source_operation"),
                    reason = value.optString("reason"),
                    changedAt = value.optString("changed_at"),
                    item = value.optJSONObject("item")?.let(::parseKnowledgeListItem),
                )
            },
            nextRevision = root.getLong("next_revision"),
            hasMore = root.optBoolean("has_more", false),
            currentRevision = root.getLong("current_revision"),
        )
    }

    fun parsePage(bodyText: String): KnowledgeTopicPage {
        val root = JSONObject(bodyText)
        requireOk(root)
        if (root.getString("contract_version") != QUALITY_CONTRACT) {
            throw JSONException("unsupported quality contract")
        }
        val knowledgeBase = root.getJSONObject("knowledge_base")
        return KnowledgeTopicPage(
            knowledgeBaseId = knowledgeBase.getString("id"),
            knowledgeBaseName = knowledgeBase.optString("name"),
            items = root.optJSONArray("items").objects(::parseCompact),
            nextCursor = if (root.isNull("next_cursor")) "" else root.optString("next_cursor"),
        )
    }

    fun parseDetail(bodyText: String): KnowledgeTopicDetail {
        val root = JSONObject(bodyText)
        requireOk(root)
        val quality = root.getJSONObject("quality_read")
        if (quality.getString("contract_version") != QUALITY_CONTRACT) {
            throw JSONException("unsupported quality contract")
        }
        val content = quality.getJSONObject("active_content")
        return KnowledgeTopicDetail(
            KnowledgeTopicClip(
                clipId = quality.getString("clip_id"),
                title = content.optString("title").ifBlank { "未命名记忆" },
                summary = content.optString("summary"),
                source = content.optString("source"),
                capturedAt = content.optString("captured_at"),
                originalText = content.optString("original_text"),
                textPreview = content.optString("text_preview"),
                safeDisplayUrl = content.optString("safe_display_url"),
                tags = content.optJSONArray("tags").strings().filter(::isUserFacingKeyword),
                topicAssignment = parseAssignment(quality.getJSONObject("topic_assignment")),
            ),
        )
    }

    fun parseRegistry(bodyText: String): TopicRegistry {
        val root = JSONObject(bodyText)
        requireOk(root)
        val registry = root.getJSONObject("registry")
        val topics = registry.optJSONArray("topics").objects { value ->
            if (!value.optBoolean("enabled", true)) return@objects null
            TopicLabel(value.getString("topic_id"), value.getString("display_name"))
        }
        return TopicRegistry(topics.filterNotNull())
    }

    fun parseAssignmentMutation(bodyText: String): ClipTopicAssignment {
        val root = JSONObject(bodyText)
        requireOk(root)
        return parseAssignment(root.getJSONObject("topic_assignment"))
    }

    fun assignmentBody(topicId: String): String = JSONObject().put("topic_id", topicId).toString()

    private fun parseCompact(value: JSONObject): KnowledgeTopicClip = KnowledgeTopicClip(
        clipId = value.getString("clip_id"),
        title = value.optString("title").ifBlank { "未命名记忆" },
        summary = value.optString("summary"),
        source = value.optString("source"),
        capturedAt = value.optString("captured_at"),
        topicAssignment = parseAssignment(value.getJSONObject("topic_assignment")),
    )

    private fun parseKnowledgeListItem(value: JSONObject): KnowledgeListItem {
        val memberships = value.optJSONArray("knowledge_base_ids").strings()
        return KnowledgeListItem(
            clip = KnowledgeTopicClip(
                clipId = value.getString("public_clip_id"),
                title = value.optString("title").ifBlank { "未命名记忆" },
                summary = value.optString("summary"),
                source = value.optString("source"),
                capturedAt = value.optString("captured_at"),
                safeDisplayUrl = value.optString("safe_display_url"),
                topicAssignment = value.optJSONObject("topic_assignment")?.let(::parseAssignment)
                    ?: ClipTopicAssignment(),
            ),
            knowledgeBaseIds = memberships,
            knowledgeBaseId = value.optString("knowledge_base_id").ifBlank { memberships.firstOrNull().orEmpty() },
            knowledgeBaseName = value.optString("knowledge_base_name"),
            sourceType = value.optString("source_type"),
            hasAttachment = value.optBoolean("has_attachment", false),
            itemRevision = value.getLong("item_revision"),
            updatedAt = value.optString("updated_at"),
            correlationIdentity = value.optString("correlation_identity"),
        )
    }

    private fun knowledgeRoot(bodyText: String): JSONObject = JSONObject(bodyText).also { root ->
        requireOk(root)
        if (root.getString("contract_version") != KNOWLEDGE_LIST_CONTRACT) {
            throw JSONException("unsupported knowledge list contract")
        }
    }

    private fun parseKnowledgeSummaryObject(value: JSONObject) = KnowledgeListSummary(
        totalCount = value.getInt("total_count"),
        matchingCount = value.getInt("matching_count"),
        revision = value.getLong("revision"),
        generatedAt = value.optString("generated_at"),
    )

    private fun parseAssignment(value: JSONObject): ClipTopicAssignment {
        if (value.getString("contract_version") != TOPIC_CONTRACT) {
            throw JSONException("unsupported topic assignment contract")
        }
        val primary = value.getJSONObject("primary")
        return ClipTopicAssignment(
            primary = TopicLabel(primary.getString("topic_id"), primary.getString("display_name")),
            secondary = value.optJSONArray("secondary").objects { topic ->
                TopicLabel(topic.getString("topic_id"), topic.getString("display_name"))
            },
            entities = value.optJSONArray("entities").strings(),
            keywords = value.optJSONArray("keywords").strings().filter(::isUserFacingKeyword),
            unclassified = value.optBoolean("unclassified", false),
            manualOverride = value.optBoolean("manual_override", false),
            topicDisabled = value.optBoolean("topic_disabled", false),
        )
    }

    private fun requireOk(value: JSONObject) {
        if (value.opt("ok") !is Boolean || !value.getBoolean("ok")) throw JSONException("ok must be true")
    }

    private fun <T> JSONArray?.objects(transform: (JSONObject) -> T): List<T> {
        if (this == null) return emptyList()
        return buildList { for (index in 0 until length()) add(transform(getJSONObject(index))) }
    }

    private fun JSONArray?.strings(): List<String> {
        if (this == null) return emptyList()
        return buildList {
            for (index in 0 until length()) optString(index).takeIf(String::isNotBlank)?.let(::add)
        }
    }

    private fun JSONObject.optNullableString(key: String): String =
        if (!has(key) || isNull(key)) "" else optString(key)

    private fun isUserFacingKeyword(value: String): Boolean {
        val normalized = value.trim().lowercase()
        return normalized !in setOf("text", "knowledge-base", "personalclips", "个人收藏") &&
            !normalized.matches(Regex("""stage\d+"""))
    }
}
