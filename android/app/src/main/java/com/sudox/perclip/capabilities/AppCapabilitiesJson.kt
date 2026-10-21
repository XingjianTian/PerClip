package com.sudox.perclip.capabilities

import org.json.JSONException
import org.json.JSONObject

object AppCapabilitiesJson {
    fun parse(bodyText: String): AppCapabilities {
        val root = JSONObject(bodyText)
        if (root.opt("ok") !is Boolean || !root.getBoolean("ok")) {
            throw JSONException("ok must be true")
        }
        val features = root.getJSONObject("features")
        val contracts = root.optJSONObject("contracts") ?: JSONObject()
        return AppCapabilities(
            apiContract = root.getString("api_contract"),
            service = root.getString("service"),
            features = AppFeatures(
                knowledgeBases = features.requiredBoolean("knowledge_bases"),
                routing = features.requiredBoolean("routing"),
                recall = features.requiredBoolean("recall"),
                recallDomain = features.requiredBoolean("recall_domain"),
                mobileBatchStatus = features.requiredBoolean("mobile_batch_status"),
                ingestV1 = features.requiredBoolean("ingest_v1"),
                ragflowCapabilities = features.requiredBoolean("ragflow_capabilities"),
                qualityReadModel = features.optBoolean("quality_read_model", false),
                memoryPlanet = features.optBoolean("memory_planet", false),
                knowledgeListV2 = features.optBoolean("knowledge_list_v2", false),
            ),
            contracts = AppContracts(
                knowledgeList = contracts.optString("knowledge_list"),
            ),
        )
    }

    private fun JSONObject.requiredBoolean(name: String): Boolean {
        if (opt(name) !is Boolean) throw JSONException("$name must be boolean")
        return getBoolean(name)
    }
}
