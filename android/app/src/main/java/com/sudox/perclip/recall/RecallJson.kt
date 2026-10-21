package com.sudox.perclip.recall

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/** Defensive parser for the versioned Recall HTTP contract. Optional response fields always fall back safely. */
object RecallJson {
    fun parseOverview(bodyText: String): RecallOverview { val root = JSONObject(bodyText).requireOk(); return root.let { RecallOverview(window(it.optJSONObject("window") ?: it), parseMetrics(it.optJSONObject("metrics")), parseGraph(it.optJSONObject("graph")), it.optJSONArray("highlights").toHighlights()) } }
    fun parseTopic(bodyText: String): RecallTopicDetail { val root = JSONObject(bodyText).requireOk(); return RecallTopicDetail(window(root.optJSONObject("window") ?: root), parseTopic(root.optJSONObject("topic") ?: JSONObject()), parseTopicMetrics(root.optJSONObject("metrics")), parseGraph(root.optJSONObject("graph")), root.optJSONArray("items").toTopicClips()) }
    fun parseSession(bodyText: String): RecallSessionResponse { val root = JSONObject(bodyText).requireOk(); val items = root.optJSONArray("items").toSessionItems(); return RecallSessionResponse(parseSession(root.optJSONObject("session") ?: JSONObject()), items, root.optJSONObject("current_item")?.let(::parseSessionItem), parseProgress(root.optJSONObject("progress"), items)) }
    fun parseEvent(bodyText: String): RecallEventResponse { val root = JSONObject(bodyText).requireOk(); val item = parseSessionItem(root.optJSONObject("item") ?: JSONObject()); return RecallEventResponse(parseSession(root.optJSONObject("session") ?: JSONObject()), item, root.optJSONObject("current_item")?.let(::parseSessionItem), parseProgress(root.optJSONObject("progress")), root.optString("reveal_text")) }
    fun parseWeeklyReview(bodyText: String): RecallWeeklyReview { val root = JSONObject(bodyText).requireOk(); return RecallWeeklyReview(window(root.optJSONObject("window") ?: root), parseWeeklySummary(root.optJSONObject("summary")), root.optJSONArray("top_topics").toWeeklyTopics(), root.optJSONArray("most_recalled").toWeeklyItems(), root.optJSONArray("suggested_items").toWeeklyItems()) }
    fun parseClip(bodyText: String): RecallClip { val root = JSONObject(bodyText).requireOk(); val clip = root.optJSONObject("clip") ?: root; return RecallClip(clip.optString("clip_id"), clip.optString("client_request_id"), clip.optString("title"), clip.optString("summary"), clip.optString("safe_text"), clip.optString("url"), clip.optString("filename"), clip.optString("source_type"), clip.optString("source_label"), clip.optString("knowledge_base_name"), clip.optJSONArray("tags").toStrings(), clip.optString("captured_at")) }
    fun createSessionBody(request: RecallSessionRequest): String = JSONObject().put("days", request.days.coerceIn(1, 30)).put("limit", request.limit.coerceIn(1, 20)).put("topic_id", request.topicId).toString()
    fun createEventBody(request: RecallEventRequest): String = JSONObject().put("action", request.action.wireValue).put("client_action_id", request.clientActionId).toString()
    private fun window(json: JSONObject) = RecallWindow(
        json.optInt("days", 7),
        json.optString("start", json.optString("window_start", json.optString("range_start"))),
        json.optString("end", json.optString("window_end", json.optString("range_end"))),
    )
    private fun parseMetrics(json: JSONObject?) = RecallMetrics(json?.optInt("eligible_clip_count", 0) ?: 0, json?.optInt("recall_count", 0) ?: 0, json?.optInt("new_topic_count", 0) ?: 0, json?.optDouble("reviewed_ratio", 0.0) ?: 0.0)
    private fun parseTopicMetrics(json: JSONObject?) = RecallTopicMetrics(json?.optInt("clip_count", 0) ?: 0, json?.optInt("recall_count", 0) ?: 0, json?.optInt("unrecalled_count", 0) ?: 0)
    private fun parseGraph(json: JSONObject?) = RecallGraph(json?.optJSONArray("nodes").toNodes(), json?.optJSONArray("edges").toEdges())
    private fun parseTopic(json: JSONObject) = RecallTopic(json.optString("topic_id", json.optString("id")), json.optString("label"), json.optInt("weight", 0), json.optInt("color_slot", 0))
    private fun parseSession(json: JSONObject): RecallSession {
        val nestedWindow = json.optJSONObject("window")
        return RecallSession(
            id = json.optString("id"),
            kind = json.optString("kind", "general"),
            status = json.optString("status"),
            topicId = json.optString("topic_id"),
            window = window(nestedWindow ?: json),
            createdAt = json.optString("created_at"),
            completedAt = json.optString("completed_at"),
            totalItems = json.optInt("total_items", 0),
            currentPosition = json.optInt("current_position", 0),
            snapshotKey = json.optString("snapshot_key"),
        )
    }
    private fun parseProgress(json: JSONObject?, items: List<RecallSessionItem> = emptyList()) = RecallProgress(json?.optInt("completed", items.count { it.status != "pending" }) ?: items.count { it.status != "pending" }, json?.optInt("total", items.size) ?: items.size, json?.optInt("current_position", 0) ?: 0)
    private fun parseSessionItem(json: JSONObject) = RecallSessionItem(json.optString("id").ifBlank { json.optString("item_id").ifBlank { json.optString("clip_id") } }, json.optString("clip_id"), json.optString("client_request_id"), json.optString("topic_id"), json.optInt("position", 0), json.optString("title"), json.optString("cue", json.optString("prompt")), json.optString("reveal_text"), json.optString("summary"), json.optJSONArray("tags").toStrings(), json.optString("source_type"), json.optString("source_label", json.optString("source_app", json.optString("source"))), json.optString("knowledge_base_name"), json.optString("captured_at"), json.optInt("recall_count_before", 0), json.optDouble("score", 0.0), json.optString("status", json.optString("state", "pending")))
    private fun JSONArray?.toNodes() = objects { RecallGraphNode(it.optString("id"), it.optString("type"), it.optString("label"), it.optInt("weight", 0), it.optInt("color_slot", 0), it.optString("topic_id"), it.optString("clip_id")) }
    private fun JSONArray?.toEdges() = objects { RecallGraphEdge(it.optString("source"), it.optString("target"), it.optString("type"), it.optInt("weight", 0)) }
    private fun JSONArray?.toHighlights() = objects { RecallHighlight(it.optString("type"), it.optString("title"), it.optString("subtitle"), it.optString("topic_id"), it.optString("clip_id"), it.optString("client_request_id"), it.optString("occurred_at")) }
    private fun JSONArray?.toTopicClips() = objects { RecallTopicClip(it.optString("clip_id"), it.optString("client_request_id"), it.optString("title"), it.optString("summary"), it.optJSONArray("tags").toStrings(), it.optString("source_type"), it.optString("source_label"), it.optString("knowledge_base_name"), it.optString("captured_at"), it.optInt("recall_count", 0), it.optBoolean("recalled_in_window", false), it.optDouble("score", 0.0)) }
    private fun JSONArray?.toSessionItems() = objects(::parseSessionItem)
    private fun JSONArray?.toWeeklyTopics() = objects { RecallWeeklyTopic(it.optString("topic_id", it.optString("id")), it.optString("label"), it.optInt("clip_count", 0), it.optInt("recall_count", 0), it.optInt("weight", 0)) }
    private fun JSONArray?.toWeeklyItems() = objects { RecallWeeklyItem(it.optString("clip_id"), it.optString("title"), it.optString("topic_id"), it.optString("topic_label"), it.optInt("recall_count", 0), it.optString("captured_at")) }
    private fun parseWeeklySummary(json: JSONObject?) = RecallWeeklySummary(
        savedCount = json?.optInt("saved_count", 0) ?: 0,
        recallCount = json?.optInt("recall_count", 0) ?: 0,
        topicCount = json?.optInt("topic_count", 0) ?: 0,
        connectionCount = json?.optInt("connection_count", 0) ?: 0,
        summaryText = json?.optString("summary_text", "") ?: "",
    )
    private fun JSONArray?.toStrings(): List<String> = if (this == null) emptyList() else buildList { for (i in 0 until length()) optString(i).takeIf(String::isNotBlank)?.let(::add) }
    private fun <T> JSONArray?.objects(transform: (JSONObject) -> T): List<T> = if (this == null) emptyList() else buildList { for (i in 0 until length()) optJSONObject(i)?.let { add(transform(it)) } }
    private fun JSONObject.requireOk(): JSONObject { if (opt("ok") !is Boolean || !optBoolean("ok")) throw JSONException("ok must be true"); return this }
}
