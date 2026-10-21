package com.sudox.perclip.knowledge

import android.content.Context
import com.sudox.perclip.config.PerClipSettings
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

class KnowledgeBaseLocalCache(
    context: Context,
    configurationScope: String,
) {
    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )
    private val itemsKey = "$KEY_ITEMS_PREFIX$configurationScope"

    fun load(): List<KnowledgeBaseSummary> {
        return KnowledgeBaseCacheCodec.decode(preferences.getString(itemsKey, null))
    }

    fun save(items: List<KnowledgeBaseSummary>) {
        preferences.edit()
            .putString(itemsKey, KnowledgeBaseCacheCodec.encode(items))
            .apply()
    }

    private companion object {
        const val PREFERENCES_NAME = "perclip_knowledge_base_cache"
        const val KEY_ITEMS_PREFIX = "knowledge_bases_"
    }
}

object KnowledgeBaseCacheScope {
    fun fromSettings(settings: PerClipSettings): String {
        val normalized = settings.normalized()
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest((normalized.apiUrl + "\u0000" + normalized.ingestToken).toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }
}

object KnowledgeBaseCacheCodec {
    fun encode(items: List<KnowledgeBaseSummary>): String {
        val array = JSONArray()
        KnowledgeBaseUiLogic.activeSaveTargets(items).forEach { item ->
            val topics = JSONArray()
            item.topTopics.take(3).forEach { topic ->
                topics.put(
                    JSONObject()
                        .put("id", topic.id)
                        .put("label", topic.label)
                        .put("clip_count", topic.clipCount),
                )
            }
            array.put(
                JSONObject()
                    .put("id", item.id)
                    .put("name", item.name)
                    .put("description", item.description)
                    .put("is_default", item.isDefault)
                    .put("updated_at", item.updatedAt)
                    .put("top_topics", topics),
            )
        }
        return array.toString()
    }

    fun decode(value: String?): List<KnowledgeBaseSummary> {
        if (value.isNullOrBlank()) return emptyList()
        return runCatching {
            val array = JSONArray(value)
            buildList {
                for (index in 0 until array.length()) {
                    val item = array.optJSONObject(index) ?: continue
                    val id = item.optString("id")
                    val name = item.optString("name")
                    if (id.isBlank() || name.isBlank()) continue
                    add(
                        KnowledgeBaseSummary(
                            id = id,
                            name = name,
                            description = item.optString("description"),
                            isDefault = item.optBoolean("is_default"),
                            updatedAt = item.optString("updated_at"),
                            topTopics = buildList {
                                val topics = item.optJSONArray("top_topics") ?: JSONArray()
                                for (topicIndex in 0 until topics.length()) {
                                    val topic = topics.optJSONObject(topicIndex) ?: continue
                                    val topicId = topic.optString("id")
                                    val label = topic.optString("label")
                                    if (topicId.isBlank() || label.isBlank()) continue
                                    add(
                                        KnowledgeBaseTopicSummary(
                                            id = topicId,
                                            label = label,
                                            clipCount = topic.optInt("clip_count", 0).coerceAtLeast(0),
                                        ),
                                    )
                                }
                            },
                        ),
                    )
                }
            }
        }.getOrDefault(emptyList())
    }
}
