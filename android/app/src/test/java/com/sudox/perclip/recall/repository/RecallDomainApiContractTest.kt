package com.sudox.perclip.recall.repository

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

class RecallDomainApiContractTest {
    @Test fun domainAndResurfaceEncodeOptionalQueriesWithoutAddingDays() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallDomainApi(capturingClient(captured))
        assertTrue(api.domain(settings(), RecallDomainRequest(topicId = "topic: a/b")).ok)
        assertTrue(api.resurface(settings(), RecallResurfaceRequest(cursor = "eyJ2IjoxfQ==", topicId = "topic: a/b", excludeClipIds = listOf("a b", "x/y"))).ok)

        assertEquals("/api/recall/domain", captured[0].path)
        assertFalse(captured[0].query.contains("days="))
        assertTrue(captured[0].query.contains("topic_id=topic%3A%20a%2Fb"))
        assertEquals("/api/recall/resurface", captured[1].path)
        assertTrue(captured[1].query.contains("cursor=eyJ2IjoxfQ%3D%3D"))
        assertTrue(captured[1].query.contains("exclude_clip_ids=a%20b%2Cx%2Fy"))
    }

    @Test fun explicitDaysAreSentWhileNullableDaysAreOmitted() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallDomainApi(capturingClient(captured))
        assertTrue(api.domain(settings(), RecallDomainRequest(days = 14)).ok)
        assertTrue(api.resurface(settings(), RecallResurfaceRequest(days = 21)).ok)

        assertTrue(captured[0].query.contains("days=14"))
        assertTrue(captured[1].query.contains("days=21"))
    }

    @Test fun customDomainAndResurfaceSendExactDatesAndTimezone() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallDomainApi(capturingClient(captured))
        val domain = RecallDomainRequest(days = 5, startDate = "2026-07-01", endDate = "2026-07-05", timezone = "Asia/Shanghai")
        val resurface = RecallResurfaceRequest(days = 5, startDate = domain.startDate, endDate = domain.endDate, timezone = domain.timezone)
        assertTrue(api.domain(settings(), domain).ok)
        assertTrue(api.resurface(settings(), resurface).ok)
        captured.forEach {
            assertTrue(it.query.contains("start=2026-07-01"))
            assertTrue(it.query.contains("end=2026-07-05"))
            assertTrue(it.query.contains("timezone=Asia%2FShanghai"))
        }
    }

    @Test fun knowledgeBaseScopeIsSentToDomainResurfaceAndPlanetRequests() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallDomainApi(capturingClient(captured))
        val knowledgeBaseId = "kb-development-test"

        assertTrue(api.domain(settings(), RecallDomainRequest(knowledgeBaseId = knowledgeBaseId)).ok)
        assertTrue(api.resurface(settings(), RecallResurfaceRequest(knowledgeBaseId = knowledgeBaseId)).ok)
        api.memoryPlanet(settings(), MemoryPlanetWindow(knowledgeBaseId = knowledgeBaseId))

        assertTrue(captured.all { it.query.contains("knowledge_base_id=kb-development-test") })
    }

    @Test fun interactionAndPreferenceBodiesAreTypedAndUseOnlyMobileToken() {
        val captured = mutableListOf<CapturedRequest>()
        val api = RecallDomainApi(capturingClient(captured))
        assertTrue(api.interaction(settings(), RecallInteractionRequest("graph", "impression", nodeId = "clip:7", metadata = RecallInteractionMetadata(position = 3, dwellMs = 200))).ok)
        assertTrue(api.updatePreferences(settings(), RecallPreferencesPatch(defaultDays = 14, includeMemoryLabels = false)).ok)

        assertEquals("Bearer mobile-token", captured[0].authorization)
        assertTrue(captured[0].body.contains("\"position\":3")); assertFalse(captured[0].body.contains("ragflow", true))
        assertEquals("PATCH", captured[1].method); assertTrue(captured[1].body.contains("\"default_days\":14"))
    }

    private fun capturingClient(captured: MutableList<CapturedRequest>) = OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request(); val buffer = Buffer(); request.body?.writeTo(buffer)
        captured += CapturedRequest(request.method, request.url.encodedPath, request.url.encodedQuery.orEmpty(), buffer.readUtf8(), request.header("Authorization").orEmpty())
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK")
            .body("""{"ok":true,"preferences":{}}""".toResponseBody("application/json".toMediaType())).build()
    }.build()

    private fun settings() = PerClipSettings("http://127.0.0.1:18080/", "mobile-token", "test", true, false)
    private data class CapturedRequest(val method: String, val path: String, val query: String, val body: String, val authorization: String)
}
