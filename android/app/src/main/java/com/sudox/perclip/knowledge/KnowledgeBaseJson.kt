package com.sudox.perclip.knowledge

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

object KnowledgeBaseJson {
    fun parseList(bodyText: String): KnowledgeBaseListResponse {
        val root = JSONObject(bodyText)
        return KnowledgeBaseListResponse(
            ok = root.requireBoolean("ok"),
            knowledgeBases = root.optJSONArray("knowledge_bases").toKnowledgeBases(),
        )
    }

    fun parseMutation(bodyText: String): KnowledgeBaseMutationResponse {
        val root = JSONObject(bodyText)
        return KnowledgeBaseMutationResponse(
            ok = root.requireBoolean("ok"),
            knowledgeBase = parseKnowledgeBase(root.getJSONObject("knowledge_base")),
            ragflowDatasetDeleted = root.optBoolean("ragflow_dataset_deleted", false),
        )
    }

    fun parseRagflowCapabilities(bodyText: String): RagflowCapabilitySummary {
        val root = JSONObject(bodyText)
        root.requireBoolean("ok")
        val ragflow = root.getJSONObject("ragflow")
        val capabilities = ragflow.optJSONObject("capabilities") ?: JSONObject()
        return RagflowCapabilitySummary(
            adapterStatus = ragflow.optString("adapter_status"),
            configured = ragflow.optBoolean("configured", false),
            capabilities = capabilities.keys().asSequence().associateWith { key -> capabilities.optString(key) },
            notes = ragflow.optJSONArray("notes").toStringList(),
        )
    }

    fun parseRagflowProbe(bodyText: String): RagflowProbeSummary {
        val root = JSONObject(bodyText)
        root.requireBoolean("ok")
        val capabilities = root.optJSONObject("capabilities") ?: JSONObject()
        return RagflowProbeSummary(
            configured = root.optBoolean("configured", false),
            status = root.optString("status"),
            capabilities = capabilities.keys().asSequence().associateWith { key -> capabilities.optString(key) },
            warnings = root.optJSONArray("warnings").toStringList(),
            latencyMs = root.optLong("latency_ms").takeIf { root.has("latency_ms") },
        )
    }

    fun parseRagflowSyncStatus(bodyText: String): RagflowSyncStatusResponse {
        val sync = JSONObject(bodyText).getJSONObject("sync")
        val plan = sync.optJSONObject("plan") ?: JSONObject()
        return RagflowSyncStatusResponse(
            operation = sync.optString("operation"),
            status = sync.optString("status"),
            dryRun = sync.optBoolean("dry_run", false),
            reason = sync.optString("reason"),
            targetDatasetId = sync.optString("ragflow_dataset_id"),
            documentId = sync.optString("ragflow_document_id"),
            planSummary = plan.optString("summary"),
        )
    }

    fun parseEnrichmentStatus(bodyText: String): EnrichmentStatusResponse {
        val enrichment = JSONObject(bodyText).getJSONObject("enrichment")
        return EnrichmentStatusResponse(
            status = enrichment.optString("status"),
            summary = enrichment.optString("summary"),
            tags = enrichment.optJSONArray("tags").toStringList(),
            language = enrichment.optString("language"),
            extractedText = enrichment.optString("extracted_text"),
        )
    }

    fun createKnowledgeBaseBody(name: String, description: String): String {
        return JSONObject()
            .put("name", name)
            .put("description", description)
            .put("template_key", "general")
            .toString()
    }

    fun updateKnowledgeBaseBody(name: String, description: String): String {
        return JSONObject()
            .put("name", name)
            .put("description", description)
            .toString()
    }

    fun parseKnowledgeBase(json: JSONObject): KnowledgeBaseSummary {
        return KnowledgeBaseSummary(
            id = json.optString("id"),
            name = json.optString("name"),
            description = json.optString("description"),
            icon = json.optString("icon"),
            color = json.optString("color"),
            isDefault = json.optBoolean("is_default", false),
            isArchived = json.optBoolean("is_archived", false),
            ragflowDatasetId = json.optString("ragflow_dataset_id"),
            ragflowDatasetName = json.optString("ragflow_dataset_name"),
            templateKey = json.optString("template_key").ifBlank { "general" },
            createdAt = json.optString("created_at"),
            updatedAt = json.optString("updated_at"),
            deletedAt = json.optString("deleted_at"),
            topTopics = json.optJSONArray("top_topics").toKnowledgeBaseTopics(),
        )
    }

    private fun JSONArray?.toKnowledgeBaseTopics(): List<KnowledgeBaseTopicSummary> {
        if (this == null) return emptyList()
        return buildList {
            for (index in 0 until length()) {
                val topic = optJSONObject(index) ?: continue
                val id = topic.optString("id")
                val label = topic.optString("label")
                if (id.isBlank() || label.isBlank()) continue
                add(
                    KnowledgeBaseTopicSummary(
                        id = id,
                        label = label,
                        clipCount = topic.optInt("clip_count", 0).coerceAtLeast(0),
                    ),
                )
            }
        }
    }

    private fun JSONArray?.toKnowledgeBases(): List<KnowledgeBaseSummary> {
        if (this == null) return emptyList()
        return buildList {
            for (index in 0 until length()) {
                add(parseKnowledgeBase(getJSONObject(index)))
            }
        }
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        return buildList {
            for (index in 0 until length()) {
                optString(index).takeIf { it.isNotBlank() }?.let { add(it) }
            }
        }
    }

    private fun JSONObject.requireBoolean(name: String): Boolean {
        val value = opt(name)
        if (value !is Boolean) {
            throw JSONException("$name must be boolean")
        }
        return value
    }
}
