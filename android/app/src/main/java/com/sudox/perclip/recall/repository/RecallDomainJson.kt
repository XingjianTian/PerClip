package com.sudox.perclip.recall.repository

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** Parser and request bodies for the UI-independent Recall endpoints. */
object RecallDomainJson {
    fun parseDomain(body: String): RecallDomainSnapshot {
        val root = JSONObject(body).requireOk(); val window = root.optJSONObject("window") ?: JSONObject()
        return RecallDomainSnapshot(
            windowDays = window.optInt("days", 30), windowStart = window.optString("start"), windowEnd = window.optString("end"),
            snapshotKey = root.optString("snapshot_key"), topics = root.optJSONArray("topics").objects(::topic),
            memories = root.optJSONArray("memories").objects(::memory), relations = root.optJSONArray("relations").objects(::relation),
            presentationDefaults = defaults(root.optJSONObject("presentation_defaults")),
            canonicalSnapshotKey = root.optString("canonical_snapshot_key"),
        )
    }
    fun parseResurface(body: String): RecallResurfacePage {
        val root = JSONObject(body).requireOk()
        val window = root.optJSONObject("window") ?: JSONObject()
        return RecallResurfacePage(
            snapshotKey = root.optString("snapshot_key"),
            cursor = root.optString("cursor"),
            nextCursor = root.optString("next_cursor"),
            items = root.optJSONArray("items").objects(::resurfaceItem),
            windowDays = window.optInt("days"),
            windowStart = window.optString("start"),
            windowEnd = window.optString("end"),
        )
    }
    fun parseInteraction(body: String): RecallInteractionResult {
        val root = JSONObject(body).requireOk(); val interaction = root.optJSONObject("interaction")
        val target = root.optJSONObject("target") ?: interaction?.optJSONObject("target")
        return RecallInteractionResult(
            accepted = root.optBoolean("accepted", true),
            eventId = root.optString("event_id").ifBlank { interaction?.optString("id").orEmpty() },
            replayed = root.optBoolean("replayed", root.optBoolean("replay", false)),
            target = RecallInteractionTarget(target?.optString("node_id").orEmpty(), target?.optString("topic_id").orEmpty(), target?.optString("clip_id").orEmpty()),
        )
    }
    fun parseSuppressions(body: String): RecallSuppressionPage {
        val root = JSONObject(body).requireOk()
        val items = root.optJSONArray("items").objects { value ->
            val clipId = value.optString("clip_id")
            if (!clipId.matches(Regex("pc_[0-9a-f]{32}"))) {
                throw JSONException("suppression identity must be public")
            }
            RecallSuppressedItem(
                clipId = clipId,
                title = value.optString("title").ifBlank { "未命名记忆" },
                summary = value.optString("summary"),
                suppressedAt = value.optString("suppressed_at"),
            )
        }
        return RecallSuppressionPage(
            items = items,
            cursor = root.optString("cursor"),
            previousCursor = root.optString("previous_cursor"),
            nextCursor = root.optString("next_cursor"),
            limit = root.optInt("limit", 50).coerceIn(1, 100),
        )
    }
    fun parsePreferences(body: String): RecallPreferences {
        val root = JSONObject(body).requireOk(); val value = root.optJSONObject("preferences") ?: root
        return RecallPreferences(value.optInt("visible_label_count", 3), value.optInt("label_rotation_seconds", 8), value.optInt("default_days", 30), value.optJSONArray("preferred_topic_ids").strings(), value.optJSONArray("muted_topic_ids").strings(), value.optBoolean("include_memory_labels", true))
    }
    fun interactionBody(value: RecallInteractionRequest): String = JSONObject().apply {
        put("client_event_id", value.clientEventId); put("surface", value.surface); put("action", value.action); put("node_id", value.nodeId); put("topic_id", value.topicId); put("clip_id", value.clipId); put("session_id", value.sessionId)
        if (value.occurredAt.isNotBlank()) put("occurred_at", value.occurredAt)
        put("metadata", metadataBody(value.metadata))
    }.toString()
    fun preferencesPatchBody(value: RecallPreferencesPatch): String = JSONObject().apply {
        value.visibleLabelCount?.let { put("visible_label_count", it) }; value.labelRotationSeconds?.let { put("label_rotation_seconds", it) }; value.defaultDays?.let { put("default_days", it) }
        value.preferredTopicIds?.let { put("preferred_topic_ids", JSONArray(it)) }; value.mutedTopicIds?.let { put("muted_topic_ids", JSONArray(it)) }; value.includeMemoryLabels?.let { put("include_memory_labels", it) }
    }.toString()
    private fun topic(v: JSONObject) = RecallDomainTopic(
        id = v.optString("id"), label = v.optString("label"), shortLabel = v.optString("short_label"), clipCount = v.optInt("clip_count"),
        weight = v.optDouble("weight"), sizeWeight = v.optDouble("size_weight"), colorSlot = v.optInt("color_slot"), iconSlot = v.optString("icon_slot", "topic"),
        labelPriority = v.optDouble("label_priority"), rotationSeed = v.optInt("rotation_seed"), lastActivityAt = v.optString("last_activity_at"), newInWindow = v.optBoolean("new_in_window", false),
        viewedCount = v.optInt("viewed_count"), deferredCount = v.optInt("deferred_count"), openedOriginalCount = v.optInt("opened_original_count"), lastRecalledAt = v.optString("last_recalled_at"),
    )
    private fun memory(v: JSONObject) = RecallDomainMemory(
        id = v.optString("id"), clipId = v.optString("clip_id"), clientRequestId = v.optString("client_request_id"), primaryTopicId = v.optString("primary_topic_id"), topicIds = v.optJSONArray("topic_ids").strings(),
        label = v.optString("label"), shortLabel = v.optString("short_label"), summary = v.optString("summary"), safeExcerpt = v.optString("safe_excerpt"), sourceType = v.optString("source_type"),
        sourceLabel = v.optString("source_label"), knowledgeBaseName = v.optString("knowledge_base_name"), tags = v.optJSONArray("tags").strings(), capturedAt = v.optString("captured_at"),
        recallCount = v.optInt("recall_count"), lastRecalledAt = v.optString("last_recalled_at"), weight = v.optDouble("weight"), sizeWeight = v.optDouble("size_weight"),
        colorSlot = v.optInt("color_slot"), iconSlot = v.optString("icon_slot", "note"), labelPriority = v.optDouble("label_priority"), rotationSeed = v.optInt("rotation_seed"),
        viewCount = v.optInt("view_count"), deferCount = v.optInt("defer_count"), openedOriginalCount = v.optInt("opened_original_count"),
        lastViewedAt = v.optString("last_viewed_at"), lastDeferredAt = v.optString("last_deferred_at"),
    )
    private fun relation(v: JSONObject) = RecallDomainRelation(v.optString("source"), v.optString("target"), v.optString("type"), v.optDouble("weight"))
    private fun metadataBody(value: RecallInteractionMetadata) = JSONObject().apply {
        value.visibleLabelCount?.let { put("visible_label_count", it) }
        value.rotationIndex?.let { put("rotation_index", it) }
        value.dwellMs?.let { put("dwell_ms", it) }
        value.position?.let { put("position", it) }
        value.source?.let { put("source", it) }
    }
    private fun defaults(v: JSONObject?) = RecallDomainPresentationDefaults(
        visibleLabelCount = v?.optInt("visible_label_count", 3) ?: 3,
        labelRotationSeconds = v?.optInt("label_rotation_seconds", 8) ?: 8,
        defaultDays = v?.optInt("default_days", 30) ?: 30,
        includeMemoryLabels = v?.optBoolean("include_memory_labels", true) ?: true,
        clientOwnsLayout = v?.optBoolean("client_owns_layout", true) ?: true,
        clientOwnsAnimation = v?.optBoolean("client_owns_animation", true) ?: true,
    )
    private fun resurfaceItem(v: JSONObject) = RecallResurfaceItem(v.optString("clip_id"), v.optString("client_request_id"), v.optString("topic_id"), v.optString("topic_label"), v.optString("title"), v.optString("summary"), v.optString("safe_excerpt"), v.optString("source_type"), v.optString("source_label"), v.optString("knowledge_base_name"), v.optJSONArray("tags").strings(), v.optString("captured_at"), v.optString("last_viewed_at"), v.optInt("view_count"), v.optInt("defer_count"), v.optDouble("score"), v.optJSONArray("reason_codes").strings())
    private fun JSONArray?.strings() = if (this == null) emptyList() else buildList { for (i in 0 until length()) optString(i).takeIf(String::isNotBlank)?.let(::add) }
    private fun <T> JSONArray?.objects(transform: (JSONObject) -> T) = if (this == null) emptyList() else buildList { for (i in 0 until length()) optJSONObject(i)?.let { add(transform(it)) } }
    private fun JSONObject.requireOk(): JSONObject { if (opt("ok") !is Boolean || !optBoolean("ok")) throw JSONException("ok must be true"); return this }
}
