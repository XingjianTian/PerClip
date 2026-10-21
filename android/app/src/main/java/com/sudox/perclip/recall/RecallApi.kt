package com.sudox.perclip.recall

import com.sudox.perclip.config.PerClipSettings
import java.io.IOException
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException

/** Blocking API client, designed to be called from a coroutine IO dispatcher by the future UI. */
class RecallApi(private val client: OkHttpClient = defaultClient()) {
    fun recallOverview(settings: PerClipSettings, days: Int = 7) = get(settings, "/api/recall/overview?days=${days.coerceIn(1, 30)}", RecallJson::parseOverview)
    fun recallTopic(settings: PerClipSettings, topicId: String, days: Int = 7, filter: RecallTopicFilter = RecallTopicFilter.ALL) = get(
        settings,
        "/api/recall/topics/${topicId.pathSegment()}?days=${days.coerceIn(1, 30)}&filter=${filter.wireValue.queryValue()}",
        RecallJson::parseTopic,
    )

    fun createRecallSession(settings: PerClipSettings, request: RecallSessionRequest) = sendJson(
        settings, "/api/recall/sessions", "POST", RecallJson.createSessionBody(request.copy(days = request.days.coerceIn(1, 30))), RecallJson::parseSession,
    )
    fun getRecallSession(settings: PerClipSettings, sessionId: String) = get(settings, "/api/recall/sessions/${sessionId.pathSegment()}", RecallJson::parseSession)
    fun applyRecallAction(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest) = sendJson(
        settings, "/api/recall/sessions/${sessionId.pathSegment()}/items/${itemId.pathSegment()}/action", "POST", RecallJson.createEventBody(request), RecallJson::parseEvent,
    )
    fun weeklyReview(settings: PerClipSettings, days: Int = 7) = get(settings, "/api/recall/weekly-review?days=${days.coerceIn(1, 30)}", RecallJson::parseWeeklyReview)
    fun recallClip(settings: PerClipSettings, clipId: String) = get(settings, "/api/recall/clips/${clipId.pathSegment()}", RecallJson::parseClip)

    // Stage 16 compatibility aliases. New callers should use the contract-named methods above.
    fun overview(settings: PerClipSettings, days: Int = 7) = recallOverview(settings, days)
    fun topic(settings: PerClipSettings, topicId: String, days: Int = 7, filter: String = "all") = recallTopic(settings, topicId, days, RecallTopicFilter.entries.firstOrNull { it.wireValue == filter } ?: RecallTopicFilter.ALL)
    fun createSession(settings: PerClipSettings, request: RecallSessionRequest) = createRecallSession(settings, request)
    fun session(settings: PerClipSettings, sessionId: String) = getRecallSession(settings, sessionId)
    fun recordEvent(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest) = applyRecallAction(settings, sessionId, itemId, request)

    private fun <T> get(settings: PerClipSettings, path: String, parser: (String) -> T): RecallApiResult<T> = execute(settings, path, "GET", null, parser)
    private fun <T> sendJson(settings: PerClipSettings, path: String, method: String, bodyText: String, parser: (String) -> T): RecallApiResult<T> = execute(settings, path, method, bodyText, parser)
    private fun <T> execute(settings: PerClipSettings, path: String, method: String, bodyText: String?, parser: (String) -> T): RecallApiResult<T> {
        val normalized = settings.normalized()
        if (!normalized.hasUploadConfig) return RecallApiResult.failure("请先完成连接设置。")
        return try {
            val request = Request.Builder().url("${normalized.apiUrl}$path").header("Authorization", "Bearer ${normalized.ingestToken}")
                .method(method, bodyText?.toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())).build()
            client.newCall(request).execute().use { response ->
                val text = response.body.string()
                if (!response.isSuccessful) return RecallApiResult.failure(RecallApiError.http(response.code, text, path))
                RecallApiResult.success(parser(text))
            }
        } catch (_: IOException) { RecallApiResult.failure("网络不可用，请检查连接后重试")
        } catch (_: IllegalArgumentException) { RecallApiResult.failure("API 地址无效")
        } catch (_: JSONException) { RecallApiResult.failure("服务端响应格式无法解析。") }
    }

    private fun String.pathSegment() = URLEncoder.encode(this, StandardCharsets.UTF_8.toString()).replace("+", "%20")
    private fun String.queryValue() = URLEncoder.encode(this, StandardCharsets.UTF_8.toString())
    companion object {
        private fun defaultClient() = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).writeTimeout(15, TimeUnit.SECONDS).callTimeout(15, TimeUnit.SECONDS).build()
    }
}

object RecallApiError {
    fun http(code: Int, bodyText: String, path: String = ""): String {
        val detail = runCatching { org.json.JSONObject(bodyText).optString("detail") }.getOrDefault("").trim()
        val featureRoute = path.startsWith("/api/recall/overview") ||
            path.startsWith("/api/recall/weekly-review") ||
            (path.substringBefore('?') == "/api/recall/sessions")
        val label = when (code) {
            401, 403 -> "认证失败，请检查连接令牌"
            404 -> if (featureRoute) "当前服务端未提供记忆星球接口，请更新服务端或检查 API 地址" else "对应内容不存在或已失效"
            409 -> "回想状态冲突"
            422 -> "请求参数无效"
            else -> "HTTP $code"
        }
        return if (detail.isBlank()) label else "$label：$detail"
    }
}
