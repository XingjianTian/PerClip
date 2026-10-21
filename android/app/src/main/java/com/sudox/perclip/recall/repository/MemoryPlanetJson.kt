package com.sudox.perclip.recall.repository

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

object MemoryPlanetJson {
    const val CONTRACT = "perclip.memory-planet.v1"
    private val publicClipId = Regex("pc_[0-9a-f]{32}")

    fun parse(bodyText: String): MemoryPlanet {
        val root = JSONObject(bodyText)
        if (root.opt("ok") !is Boolean || !root.getBoolean("ok")) throw JSONException("ok must be true")
        val planet = root.getJSONObject("planet")
        if (planet.getString("contract_version") != CONTRACT) throw JSONException("unsupported memory planet contract")
        val seen = mutableSetOf<String>()
        val topics = planet.optJSONArray("topics").objects { topic ->
            MemoryPlanetTopic(
                topicId = topic.getString("topic_id"),
                displayName = topic.getString("display_name"),
                memoryCount = topic.optInt("memory_count"),
                memories = topic.optJSONArray("memories").objects(::memory)
                    .filter { seen.add(it.clipId) }
                    .take(5),
            )
        }.take(5)
        val unclassified = planet.optJSONArray("unclassified_preview").objects(::memory)
            .filter { seen.add(it.clipId) }
            .take(3)
        val window = planet.getJSONObject("window")
        return MemoryPlanet(
            contractVersion = CONTRACT,
            window = MemoryPlanetWindow(
                kind = window.optString("kind"),
                days = window.optInt("days"),
                start = window.optString("start"),
                end = window.optString("end"),
                startDate = window.optString("start_date"),
                endDate = window.optString("end_date"),
                timezone = window.optString("timezone"),
                knowledgeBaseId = window.optString("knowledge_base_id"),
            ),
            topics = topics,
            unclassifiedCount = planet.optInt("unclassified_count"),
            unclassifiedPreview = unclassified,
            hasMoreUnclassified = planet.optBoolean("has_more_unclassified", false),
        )
    }

    private fun memory(value: JSONObject): MemoryPlanetMemory {
        val clipId = value.getString("clip_id")
        if (!publicClipId.matches(clipId)) throw JSONException("memory identity must be public")
        return MemoryPlanetMemory(
            clipId = clipId,
            title = value.optString("title").ifBlank { "未命名记忆" },
            summary = value.optString("summary"),
            capturedAt = value.optString("captured_at"),
            source = value.optString("source"),
        )
    }

    private fun <T> JSONArray?.objects(transform: (JSONObject) -> T): List<T> {
        if (this == null) return emptyList()
        return buildList { for (index in 0 until length()) add(transform(getJSONObject(index))) }
    }
}
