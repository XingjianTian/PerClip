package com.sudox.perclip.capabilities

import com.sudox.perclip.config.PerClipSettings
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppCapabilitiesApiTest {
    @Test
    fun acceptsExactCurrentContractAndSendsBearerToken() {
        var path = ""
        var auth = ""
        val api = AppCapabilitiesApi(client(200, FULL_RESPONSE) { chain ->
            path = chain.request().url.encodedPath
            auth = chain.request().header("Authorization").orEmpty()
        })

        val result = api.fetch(settings())

        assertTrue(result.ok)
        assertTrue(result.capabilities!!.features.complete)
        assertTrue(result.supportsTopicReadModel)
        assertTrue(result.supportsMemoryPlanet)
        assertTrue(result.supportsKnowledgeListV2)
        assertEquals("/api/app-capabilities", path)
        assertEquals("Bearer test-token", auth)
    }

    @Test
    fun classifiesMissingContractWithoutDisplayingHtml() {
        val result = AppCapabilitiesApi(client(404, "<html>proxy not found</html>")).fetch(settings())

        assertFalse(result.ok)
        assertEquals(AppCapabilityFailure.CONTRACT_MISSING, result.failure)
        assertEquals(AppCapabilitiesApi.MISSING_CONTRACT_MESSAGE, result.message)
        assertFalse(result.message.contains("html", ignoreCase = true))
    }

    @Test
    fun distinguishesAuthenticationAndIncompleteFeatures() {
        assertEquals(
            AppCapabilityFailure.AUTHENTICATION,
            AppCapabilitiesApi(client(401, "denied")).fetch(settings()).failure,
        )
        val incomplete = FULL_RESPONSE.replace("\"recall\":true", "\"recall\":false")
        val partial = AppCapabilitiesApi(client(200, incomplete)).fetch(settings())
        assertTrue(partial.ok)
        assertFalse(partial.complete)
        assertTrue(partial.supportsKnowledgeBases)
        assertFalse(partial.supportsRecall)
        assertEquals("基础保存正常；部分功能可用", AppCapabilitySummary.settings(partial))
        assertEquals(AppCapabilityFailure.FEATURES_INCOMPLETE, partial.failure)
    }

    @Test
    fun gatesFeaturesIndependentlyForBothPartialDirections() {
        val knowledgeOnly = AppCapabilitiesApi(client(200, FULL_RESPONSE.replace("\"recall\":true", "\"recall\":false"))).fetch(settings())
        assertEquals(AppFeatureAvailability.AVAILABLE, knowledgeOnly.featureAvailability { it.knowledgeBases })
        assertEquals(AppFeatureAvailability.UNAVAILABLE, knowledgeOnly.featureAvailability { it.recall })

        val recallOnly = AppCapabilitiesApi(client(200, FULL_RESPONSE.replace("\"knowledge_bases\":true", "\"knowledge_bases\":false"))).fetch(settings())
        assertEquals(AppFeatureAvailability.UNAVAILABLE, recallOnly.featureAvailability { it.knowledgeBases })
        assertEquals(AppFeatureAvailability.AVAILABLE, recallOnly.featureAvailability { it.recall })
        assertEquals(
            AppFeatureAvailability.UNAVAILABLE,
            combinedFeatureAvailability(
                recallOnly.featureAvailability { it.knowledgeBases },
                recallOnly.featureAvailability { it.routing },
            ),
        )
    }

    @Test
    fun rejectsMissingInvalidAuthenticationAndNoConfiguration() {
        assertEquals(AppCapabilityFailure.CONTRACT_MISSING, AppCapabilitiesApi(client(404, "missing")).fetch(settings()).failure)
        assertEquals(AppCapabilityFailure.INVALID_RESPONSE, AppCapabilitiesApi(client(200, "not-json")).fetch(settings()).failure)
        assertEquals(AppCapabilityFailure.AUTHENTICATION, AppCapabilitiesApi(client(403, "denied")).fetch(settings()).failure)
        assertEquals(AppCapabilityFailure.CONFIGURATION, AppCapabilitiesApi().fetch(settings().copy(ingestToken = "")).failure)
    }

    @Test
    fun availabilityRequiresSuccessfulFeatureHandshake() {
        assertEquals(AppFeatureAvailability.CHECKING, null.featureAvailability { it.recall })
        val missing = AppCapabilityResult(false, failure = AppCapabilityFailure.CONTRACT_MISSING, message = "old")
        assertEquals(AppFeatureAvailability.UNAVAILABLE, missing.featureAvailability { it.recall })
        val available = AppCapabilitiesApi(client(200, FULL_RESPONSE)).fetch(settings())
        assertEquals(AppFeatureAvailability.AVAILABLE, available.featureAvailability { it.knowledgeBases })
    }

    @Test
    fun memoryPlanetFeatureIsFalseWhenMissingOrExplicitlyFalseAndTrueOnlyWhenAdvertised() {
        val missing = AppCapabilitiesApi(
            client(200, FULL_RESPONSE.replace(",\"memory_planet\":true", "")),
        ).fetch(settings())
        assertFalse(missing.supportsMemoryPlanet)
        assertEquals(
            AppFeatureAvailability.UNAVAILABLE,
            missing.featureAvailability { it.memoryPlanet },
        )

        val disabled = AppCapabilitiesApi(
            client(200, FULL_RESPONSE.replace("\"memory_planet\":true", "\"memory_planet\":false")),
        ).fetch(settings())
        assertFalse(disabled.supportsMemoryPlanet)

        val enabled = AppCapabilitiesApi(client(200, FULL_RESPONSE)).fetch(settings())
        assertTrue(enabled.supportsMemoryPlanet)
        assertEquals(
            AppFeatureAvailability.AVAILABLE,
            enabled.featureAvailability { it.memoryPlanet },
        )
    }

    @Test
    fun knowledgeListV2RequiresCapabilityAndExactContractVersion() {
        val oldQualityOnly = AppCapabilitiesApi(
            client(200, FULL_RESPONSE.replace(",\"knowledge_list_v2\":true", "").replace(",\"contracts\":{\"knowledge_list\":\"perclip.knowledge-list.v2\"}", "")),
        ).fetch(settings())
        assertTrue(oldQualityOnly.supportsTopicReadModel)
        assertFalse(oldQualityOnly.supportsKnowledgeListV2)

        val wrongVersion = AppCapabilitiesApi(
            client(200, FULL_RESPONSE.replace("perclip.knowledge-list.v2", "perclip.knowledge-list.v1")),
        ).fetch(settings())
        assertFalse(wrongVersion.supportsKnowledgeListV2)
        assertTrue(AppCapabilitiesApi(client(200, FULL_RESPONSE)).fetch(settings()).supportsKnowledgeListV2)
    }

    private fun client(code: Int, body: String, inspect: (Interceptor.Chain) -> Unit = {}) =
        OkHttpClient.Builder().addInterceptor { chain ->
            inspect(chain)
            Response.Builder()
                .request(chain.request())
                .protocol(Protocol.HTTP_1_1)
                .code(code)
                .message("test")
                .body(body.toResponseBody("application/json".toMediaType()))
                .build()
        }.build()

    private fun settings() = PerClipSettings("http://127.0.0.1:18082/", "test-token", "test", true, false)

    companion object {
        private const val FULL_RESPONSE = """{"ok":true,"api_contract":"perclip.app.v1","service":"perclip-ingest","features":{"knowledge_bases":true,"routing":true,"recall":true,"recall_domain":true,"mobile_batch_status":true,"ingest_v1":true,"ragflow_capabilities":true,"quality_read_model":true,"memory_planet":true,"knowledge_list_v2":true},"contracts":{"knowledge_list":"perclip.knowledge-list.v2"}}"""
    }
}
