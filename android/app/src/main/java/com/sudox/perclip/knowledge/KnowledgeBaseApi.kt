package com.sudox.perclip.knowledge

import com.sudox.perclip.config.PerClipSettings
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException

class KnowledgeBaseApi(
    private val client: OkHttpClient = defaultClient(),
) {
    fun listKnowledgeBases(settings: PerClipSettings): KnowledgeBaseApiResult<KnowledgeBaseListResponse> {
        return get(settings, "/api/knowledge-bases", KnowledgeBaseJson::parseList)
    }

    fun createKnowledgeBase(
        settings: PerClipSettings,
        name: String,
        description: String,
    ): KnowledgeBaseApiResult<KnowledgeBaseMutationResponse> {
        return sendJson(
            settings = settings,
            path = "/api/knowledge-bases",
            method = "POST",
            bodyText = KnowledgeBaseJson.createKnowledgeBaseBody(name, description),
            parser = KnowledgeBaseJson::parseMutation,
        )
    }

    fun updateKnowledgeBase(
        settings: PerClipSettings,
        knowledgeBaseId: String,
        name: String,
        description: String,
    ): KnowledgeBaseApiResult<KnowledgeBaseMutationResponse> {
        return sendJson(
            settings = settings,
            path = "/api/knowledge-bases/${knowledgeBaseId.encodePathSegment()}",
            method = "PATCH",
            bodyText = KnowledgeBaseJson.updateKnowledgeBaseBody(name, description),
            parser = KnowledgeBaseJson::parseMutation,
        )
    }

    fun setDefault(
        settings: PerClipSettings,
        knowledgeBaseId: String,
    ): KnowledgeBaseApiResult<KnowledgeBaseMutationResponse> {
        return sendJson(
            settings = settings,
            path = "/api/knowledge-bases/${knowledgeBaseId.encodePathSegment()}/set-default",
            method = "POST",
            bodyText = "{}",
            parser = KnowledgeBaseJson::parseMutation,
        )
    }

    fun archive(
        settings: PerClipSettings,
        knowledgeBaseId: String,
    ): KnowledgeBaseApiResult<KnowledgeBaseMutationResponse> {
        return sendJson(
            settings = settings,
            path = "/api/knowledge-bases/${knowledgeBaseId.encodePathSegment()}/archive",
            method = "POST",
            bodyText = "{}",
            parser = KnowledgeBaseJson::parseMutation,
        )
    }

    fun deleteKnowledgeBase(
        settings: PerClipSettings,
        knowledgeBaseId: String,
    ): KnowledgeBaseApiResult<KnowledgeBaseMutationResponse> {
        return sendJson(
            settings = settings,
            path = "/api/knowledge-bases/${knowledgeBaseId.encodePathSegment()}",
            method = "DELETE",
            bodyText = "",
            parser = KnowledgeBaseJson::parseMutation,
        )
    }

    fun ragflowCapabilities(settings: PerClipSettings): KnowledgeBaseApiResult<RagflowCapabilitySummary> {
        return get(settings, "/api/ragflow/capabilities", KnowledgeBaseJson::parseRagflowCapabilities)
    }

    fun ragflowProbe(settings: PerClipSettings): KnowledgeBaseApiResult<RagflowProbeSummary> {
        return get(settings, "/api/ragflow/probe", KnowledgeBaseJson::parseRagflowProbe)
    }

    fun ragflowSyncStatus(settings: PerClipSettings, clipId: String): KnowledgeBaseApiResult<RagflowSyncStatusResponse> {
        return get(settings, "/api/clips/${clipId.encodePathSegment()}/ragflow-sync", KnowledgeBaseJson::parseRagflowSyncStatus)
    }

    fun enrichmentStatus(settings: PerClipSettings, clipId: String): KnowledgeBaseApiResult<EnrichmentStatusResponse> {
        return get(settings, "/api/clips/${clipId.encodePathSegment()}/enrichment", KnowledgeBaseJson::parseEnrichmentStatus)
    }

    fun listTopicClips(
        settings: PerClipSettings,
        knowledgeBaseId: String,
        cursor: String = "",
        limit: Int = 100,
    ): KnowledgeBaseApiResult<KnowledgeTopicPage> {
        val cursorQuery = cursor.takeIf(String::isNotBlank)?.let { "&cursor=${it.encodePathSegment()}" }.orEmpty()
        return get(
            settings,
            "/api/knowledge-bases/${knowledgeBaseId.encodePathSegment()}/clips?limit=${limit.coerceIn(1, 100)}$cursorQuery",
            KnowledgeTopicJson::parsePage,
        )
    }

    fun listKnowledgeV2(
        settings: PerClipSettings,
        query: KnowledgeListQuery,
        cursor: String = "",
        limit: Int = 50,
    ): KnowledgeBaseApiResult<KnowledgeListPage> = knowledgeGet(
        settings,
        "/api/knowledge/clips",
        query,
        cursor = cursor,
        limit = limit.coerceIn(1, 100),
        parser = KnowledgeTopicJson::parseKnowledgeList,
    )

    fun knowledgeSummary(
        settings: PerClipSettings,
        query: KnowledgeListQuery,
    ): KnowledgeBaseApiResult<KnowledgeListSummary> = knowledgeGet(
        settings,
        "/api/knowledge/summary",
        query,
        parser = KnowledgeTopicJson::parseKnowledgeSummary,
    )

    /** The Android cache always consumes the one global feed. */
    fun knowledgeChanges(
        settings: PerClipSettings,
        afterRevision: Long,
        limit: Int = 100,
    ): KnowledgeBaseApiResult<KnowledgeChangePage> = knowledgeGet(
        settings,
        "/api/knowledge/changes",
        query = KnowledgeListQuery(),
        afterRevision = afterRevision.coerceAtLeast(0),
        limit = limit.coerceIn(1, 100),
        parser = KnowledgeTopicJson::parseKnowledgeChanges,
    )

    fun topicDetail(settings: PerClipSettings, clipId: String): KnowledgeBaseApiResult<KnowledgeTopicDetail> =
        get(settings, "/api/clips/${clipId.encodePathSegment()}/quality", KnowledgeTopicJson::parseDetail)

    fun topicRegistry(settings: PerClipSettings): KnowledgeBaseApiResult<TopicRegistry> =
        get(settings, "/api/topics", KnowledgeTopicJson::parseRegistry)

    fun setTopicAssignment(
        settings: PerClipSettings,
        clipId: String,
        topicId: String,
    ): KnowledgeBaseApiResult<ClipTopicAssignment> = sendJson(
        settings,
        "/api/clips/${clipId.encodePathSegment()}/topic-assignment",
        "PUT",
        KnowledgeTopicJson.assignmentBody(topicId),
        KnowledgeTopicJson::parseAssignmentMutation,
    )

    fun clearTopicAssignment(
        settings: PerClipSettings,
        clipId: String,
    ): KnowledgeBaseApiResult<ClipTopicAssignment> = sendJson(
        settings,
        "/api/clips/${clipId.encodePathSegment()}/topic-assignment",
        "DELETE",
        "",
        KnowledgeTopicJson::parseAssignmentMutation,
    )

    private fun <T> get(
        settings: PerClipSettings,
        path: String,
        parser: (String) -> T,
    ): KnowledgeBaseApiResult<T> {
        val normalizedSettings = settings.normalized()
        if (!normalizedSettings.hasUploadConfig) {
            return KnowledgeBaseApiResult.failure("请先完成连接设置。")
        }
        val request = Request.Builder()
            .url("${normalizedSettings.apiUrl}$path")
            .header("Authorization", "Bearer ${normalizedSettings.ingestToken}")
            .get()
            .build()
        return execute(request, parser)
    }

    private fun <T> knowledgeGet(
        settings: PerClipSettings,
        path: String,
        query: KnowledgeListQuery,
        cursor: String = "",
        afterRevision: Long? = null,
        limit: Int? = null,
        parser: (String) -> T,
    ): KnowledgeBaseApiResult<T> {
        val normalizedSettings = settings.normalized()
        if (!normalizedSettings.hasUploadConfig) {
            return KnowledgeBaseApiResult.failure("请先完成连接设置。")
        }
        val url = buildKnowledgeUrl(normalizedSettings.apiUrl, path, query, cursor, afterRevision, limit)
            ?: return KnowledgeBaseApiResult.failure("API 地址无效")
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${normalizedSettings.ingestToken}")
            .get()
            .build()
        return execute(request, parser)
    }

    internal fun buildKnowledgeUrl(
        apiUrl: String,
        path: String,
        rawQuery: KnowledgeListQuery,
        cursor: String = "",
        afterRevision: Long? = null,
        limit: Int? = null,
    ): HttpUrl? {
        val base = apiUrl.trimEnd('/').toHttpUrlOrNull() ?: return null
        val builder = base.newBuilder().encodedPath(path)
        val query = rawQuery.normalized()
        limit?.let { builder.addQueryParameter("limit", it.toString()) }
        query.knowledgeBaseIds.forEach { builder.addQueryParameter("knowledge_base_id", it) }
        query.text.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("query", it) }
        query.source.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("source", it) }
        query.sourceType.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("source_type", it) }
        query.attachment.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("attachment", it) }
        query.capturedAfter.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("captured_after", it) }
        query.capturedBefore.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("captured_before", it) }
        cursor.takeIf(String::isNotBlank)?.let { builder.addQueryParameter("cursor", it) }
        afterRevision?.let { builder.addQueryParameter("after_revision", it.toString()) }
        return builder.build()
    }

    private fun <T> sendJson(
        settings: PerClipSettings,
        path: String,
        method: String,
        bodyText: String,
        parser: (String) -> T,
    ): KnowledgeBaseApiResult<T> {
        val normalizedSettings = settings.normalized()
        if (!normalizedSettings.hasUploadConfig) {
            return KnowledgeBaseApiResult.failure("请先完成连接设置。")
        }
        val body = bodyText.toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
        val request = Request.Builder()
            .url("${normalizedSettings.apiUrl}$path")
            .header("Authorization", "Bearer ${normalizedSettings.ingestToken}")
            .method(method, if (method == "DELETE") null else body)
            .build()
        return execute(request, parser)
    }

    private fun <T> execute(
        request: Request,
        parser: (String) -> T,
    ): KnowledgeBaseApiResult<T> {
        return try {
            client.newCall(request).execute().use { response ->
                val bodyText = response.body.string()
                if (!response.isSuccessful) {
                    return KnowledgeBaseApiResult.failure(KnowledgeBaseApiError.http(response.code, bodyText))
                }
                KnowledgeBaseApiResult.success(parser(bodyText))
            }
        } catch (error: IOException) {
            KnowledgeBaseApiResult.failure(error.message ?: "网络请求失败")
        } catch (error: IllegalArgumentException) {
            KnowledgeBaseApiResult.failure(error.message ?: "API 地址无效")
        } catch (_: JSONException) {
            KnowledgeBaseApiResult.failure("服务端响应格式无法解析。")
        }
    }

    private fun String.encodePathSegment(): String {
        return replace("/", "%2F")
    }

    companion object {
        private const val TIMEOUT_SECONDS = 15L

        private fun defaultClient(): OkHttpClient {
            return OkHttpClient.Builder()
                .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .build()
        }
    }
}

object KnowledgeBaseApiError {
    fun http(code: Int, bodyText: String): String {
        val detail = runCatching {
            org.json.JSONObject(bodyText).optString("detail")
        }.getOrDefault("").trim()
        val label = when (code) {
            401 -> "认证失败，请检查连接令牌。"
            404 -> "服务端没有找到请求的资源"
            409 -> "操作冲突"
            422 -> "请求参数无效"
            else -> "HTTP $code"
        }
        return if (detail.isBlank()) label else "$label：$detail"
    }
}
