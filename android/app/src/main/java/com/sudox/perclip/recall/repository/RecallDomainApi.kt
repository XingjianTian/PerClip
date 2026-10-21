package com.sudox.perclip.recall.repository

import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.recall.RecallApiError
import com.sudox.perclip.recall.RecallApiResult
import java.io.IOException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException

/** Blocking transport for new domain endpoints; [NetworkRecallRepository] supplies the IO boundary. */
class RecallDomainApi(private val client: OkHttpClient = defaultClient()) {
    fun domain(settings: PerClipSettings, request: RecallDomainRequest) = get(settings, "/api/recall/domain?" + query(
        "days" to request.days?.coerceIn(1, 90)?.toString(), "topic_limit" to request.topicLimit.coerceIn(1, 30).toString(),
        "memory_limit" to request.memoryLimit.coerceIn(1, 200).toString(), "include_memories" to request.includeMemories.toString(),
        "topic_id" to request.topicId.takeIf(String::isNotBlank),
        "start" to request.startDate.takeIf(String::isNotBlank), "end" to request.endDate.takeIf(String::isNotBlank),
        "timezone" to request.timezone.takeIf(String::isNotBlank),
        "knowledge_base_id" to request.knowledgeBaseId.takeIf(String::isNotBlank),
    ), RecallDomainJson::parseDomain)
    fun resurface(settings: PerClipSettings, request: RecallResurfaceRequest) = get(settings, "/api/recall/resurface?" + query(
        "days" to request.days?.coerceIn(1, 90)?.toString(), "limit" to request.limit.coerceIn(1, 20).toString(),
        "cursor" to request.cursor.takeIf(String::isNotBlank), "topic_id" to request.topicId.takeIf(String::isNotBlank),
        "exclude_clip_ids" to request.excludeClipIds.take(50).filter(String::isNotBlank).joinToString(",").takeIf(String::isNotBlank),
        "start" to request.startDate.takeIf(String::isNotBlank), "end" to request.endDate.takeIf(String::isNotBlank),
        "timezone" to request.timezone.takeIf(String::isNotBlank),
        "knowledge_base_id" to request.knowledgeBaseId.takeIf(String::isNotBlank),
    ), RecallDomainJson::parseResurface)
    fun interaction(settings: PerClipSettings, request: RecallInteractionRequest) = send(settings, "/api/recall/interactions", "POST", RecallDomainJson.interactionBody(request), RecallDomainJson::parseInteraction)
    fun suppressions(settings: PerClipSettings, cursor: String = "", limit: Int = 50) =
        get(
            settings,
            "/api/recall/suppressions?" + query(
                "limit" to limit.coerceIn(1, 100).toString(),
                "cursor" to cursor.takeIf(String::isNotBlank),
            ),
            RecallDomainJson::parseSuppressions,
        )
    fun preferences(settings: PerClipSettings) = get(settings, "/api/recall/preferences", RecallDomainJson::parsePreferences)
    fun updatePreferences(settings: PerClipSettings, patch: RecallPreferencesPatch) = send(settings, "/api/recall/preferences", "PATCH", RecallDomainJson.preferencesPatchBody(patch), RecallDomainJson::parsePreferences)
    fun memoryPlanet(settings: PerClipSettings, window: MemoryPlanetWindow): RecallApiResult<MemoryPlanet> {
        val kind = window.kind.takeIf { it in setOf("week", "month", "custom") } ?: "week"
        val custom = kind == "custom"
        return get(
            settings,
            "/api/memory-planet?" + query(
                "window" to kind,
                "start" to window.startDate.takeIf { custom && it.isNotBlank() },
                "end" to window.endDate.takeIf { custom && it.isNotBlank() },
                "timezone" to window.timezone.takeIf { custom && it.isNotBlank() },
                "knowledge_base_id" to window.knowledgeBaseId.takeIf(String::isNotBlank),
            ),
            MemoryPlanetJson::parse,
        )
    }

    private fun <T> get(settings: PerClipSettings, path: String, parser: (String) -> T) = execute(settings, path, "GET", null, parser)
    private fun <T> send(settings: PerClipSettings, path: String, method: String, body: String, parser: (String) -> T) = execute(settings, path, method, body, parser)
    private fun <T> execute(settings: PerClipSettings, path: String, method: String, body: String?, parser: (String) -> T): RecallApiResult<T> {
        val normalized = settings.normalized()
        if (!normalized.hasUploadConfig) return RecallApiResult.failure("请先完成连接设置。")
        return try {
            val request = Request.Builder().url("${normalized.apiUrl}$path").header("Authorization", "Bearer ${normalized.ingestToken}")
                .method(method, body?.toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())).build()
            client.newCall(request).execute().use { response ->
                val text = response.body.string()
                if (!response.isSuccessful) RecallApiResult.failure(RecallApiError.http(response.code, text)) else RecallApiResult.success(parser(text))
            }
        } catch (error: IOException) { RecallApiResult.failure(error.message ?: "网络请求失败")
        } catch (error: IllegalArgumentException) { RecallApiResult.failure(error.message ?: "API 地址无效")
        } catch (_: JSONException) { RecallApiResult.failure("服务端响应格式无法解析。") }
    }
    private fun query(vararg values: Pair<String, String?>) = values.mapNotNull { (key, value) -> value?.let { "${key.encode()}=${it.encode()}" } }.joinToString("&")
    private fun String.encode() = URLEncoder.encode(this, StandardCharsets.UTF_8.toString()).replace("+", "%20")
    companion object { private fun defaultClient() = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).writeTimeout(15, TimeUnit.SECONDS).callTimeout(15, TimeUnit.SECONDS).build() }
}
