package com.sudox.perclip.recall

import com.sudox.perclip.config.PerClipSettings
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallApiContractTest {
    @Test
    fun encodesTopicSessionAndItemIdsAndUsesContractEndpoints() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallApi(capturingClient(captured))
        val settings = settings()

        assertTrue(api.recallTopic(settings, "topic: a/b", days = 99).ok)
        assertTrue(api.getRecallSession(settings, "session / one").ok)
        assertTrue(api.applyRecallAction(settings, "session / one", "item ? two", RecallEventRequest(RecallEventAction.REMEMBERED, "action-123")).ok)
        assertTrue(api.weeklyReview(settings, days = 0).ok)

        assertEquals("/api/recall/topics/topic%3A%20a%2Fb", captured[0].encodedPath)
        assertEquals("days=30&filter=all", captured[0].encodedQuery)
        assertEquals("/api/recall/sessions/session%20%2F%20one", captured[1].encodedPath)
        assertEquals("/api/recall/sessions/session%20%2F%20one/items/item%20%3F%20two/action", captured[2].encodedPath)
        assertEquals("POST", captured[2].method)
        assertTrue(captured[2].body.contains("\"client_action_id\":\"action-123\""))
        assertTrue(captured[2].body.contains("\"action\":\"remembered\""))
        assertEquals("/api/recall/weekly-review", captured[3].encodedPath)
        assertEquals("days=1", captured[3].encodedQuery)
    }

    @Test
    fun boundsSessionDaysAndLimitBeforeSending() {
        val captured = mutableListOf<CapturedRequest>()
        val result = RecallApi(capturingClient(captured)).createRecallSession(settings(), RecallSessionRequest(days = -4, limit = 99, topicId = "topic:a"))

        assertTrue(result.ok)
        assertEquals("/api/recall/sessions", captured.single().encodedPath)
        assertTrue(captured.single().body.contains("\"days\":1"))
        assertTrue(captured.single().body.contains("\"limit\":20"))
    }

    @Test
    fun malformedSuccessJsonReturnsFailureInsteadOfEscapingToUi() {
        val client = OkHttpClient.Builder().addInterceptor { chain -> responseFor(chain, "{ not-json") }.build()
        val result = RecallApi(client).recallOverview(settings())

        assertFalse(result.ok)
        assertEquals("服务端响应格式无法解析。", result.message)
    }

    @Test
    fun recallModelsDoNotExposeForbiddenTransportOrRemoteFields() {
        val models = listOf(
            RecallWindow::class.java, RecallMetrics::class.java, RecallGraph::class.java, RecallGraphNode::class.java,
            RecallGraphEdge::class.java, RecallHighlight::class.java, RecallOverview::class.java, RecallTopic::class.java,
            RecallTopicMetrics::class.java, RecallTopicClip::class.java, RecallTopicDetail::class.java,
            RecallSessionRequest::class.java, RecallProgress::class.java, RecallSession::class.java,
            RecallSessionItem::class.java, RecallEventRequest::class.java, RecallEventResponse::class.java,
            RecallWeeklySummary::class.java, RecallWeeklyTopic::class.java, RecallWeeklyItem::class.java,
            RecallWeeklyReview::class.java, RecallClip::class.java,
        )
        val fieldNames = models.flatMap { it.declaredFields.asIterable() }.map { it.name.lowercase() }
        listOf("ragflowapikey", "originalpath", "datasetid", "documentid", "authorization", "cookie", "password").forEach { forbidden ->
            assertFalse("Recall model exposes $forbidden", fieldNames.any { it.contains(forbidden) })
        }
    }

    private fun capturingClient(captured: MutableList<CapturedRequest>) = OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request()
        val buffer = Buffer()
        request.body?.writeTo(buffer)
        captured += CapturedRequest(request.method, request.url.encodedPath, request.url.encodedQuery.orEmpty(), buffer.readUtf8())
        responseFor(chain, """{"ok":true}""")
    }.build()

    private fun responseFor(chain: Interceptor.Chain, body: String) = Response.Builder()
        .request(chain.request())
        .protocol(Protocol.HTTP_1_1)
        .code(200)
        .message("OK")
        .body(body.toResponseBody("application/json".toMediaType()))
        .build()

    private fun settings() = PerClipSettings("http://127.0.0.1:18080/", "test-token", "test", true, false)

    private data class CapturedRequest(val method: String, val encodedPath: String, val encodedQuery: String, val body: String)
}
