package com.sudox.perclip.recall.repository

import com.sudox.perclip.capabilities.AppFeatureAvailability
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

class MemoryPlanetCompatibilityTest {
    @Test
    fun capabilityPolicyCallsDedicatedEndpointOnlyWhenExplicitlyTrue() {
        assertFalse(MemoryPlanetLoadPolicy.shouldRequest(AppFeatureAvailability.CHECKING))
        assertFalse(MemoryPlanetLoadPolicy.shouldRequest(AppFeatureAvailability.UNAVAILABLE))
        assertTrue(MemoryPlanetLoadPolicy.shouldRequest(AppFeatureAvailability.AVAILABLE))
    }

    @Test
    fun customRequestUsesActualRangeAndTimezoneWithoutLegacyDays() {
        var query = ""
        val api = RecallDomainApi(client(200, PLANET) { chain ->
            query = chain.request().url.encodedQuery.orEmpty()
        })
        val result = api.memoryPlanet(
            settings(),
            MemoryPlanetWindow(
                kind = "custom",
                days = 5,
                startDate = "2026-07-01",
                endDate = "2026-07-05",
                timezone = "Asia/Shanghai",
            ),
        )
        assertTrue(result.ok)
        assertTrue(query.contains("window=custom"))
        assertTrue(query.contains("start=2026-07-01"))
        assertTrue(query.contains("end=2026-07-05"))
        assertTrue(query.contains("timezone=Asia%2FShanghai"))
        assertFalse(query.contains("days="))
    }

    @Test
    fun endpoint404And5xxAreSafeFailures() {
        val missing = RecallDomainApi(client(404, """{"detail":"missing"}"""))
            .memoryPlanet(settings(), MemoryPlanetWindow())
        val server = RecallDomainApi(client(503, """{"detail":"busy"}"""))
            .memoryPlanet(settings(), MemoryPlanetWindow())
        assertFalse(missing.ok)
        assertFalse(server.ok)
        assertFalse(missing.message.contains("<html", ignoreCase = true))
    }

    @Test
    fun fallbackUsesDomainAndResurfaceWithoutInventingPrivateIdentity() {
        val domain = RecallDomainSnapshot(
            windowDays = 5,
            windowStart = "2026-07-01T00:00:00Z",
            windowEnd = "2026-07-06T00:00:00Z",
            topics = listOf(RecallDomainTopic("topic:a", "主题 A", clipCount = 1)),
            memories = listOf(
                RecallDomainMemory(
                    id = "clip:pc_00000000000000000000000000000001",
                    clipId = "pc_00000000000000000000000000000001",
                    primaryTopicId = "topic:a",
                    topicIds = listOf("topic:a"),
                    label = "Fallback",
                ),
            ),
        )
        val fallback = MemoryPlanetFallback.build(
            domain,
            RecallResurfacePage(),
            MemoryPlanetWindow(
                kind = "custom",
                startDate = "2026-07-01",
                endDate = "2026-07-05",
                timezone = "UTC",
            ),
        )
        assertEquals(5, fallback.window.days)
        assertEquals("Fallback", fallback.topics.single().memories.single().title)
        assertFalse(fallback.toString().contains("internal", ignoreCase = true))
    }

    @Test
    fun fallbackStillUsesCurrentDomainWhenResurfaceFails() {
        val fallback = MemoryPlanetFallback.buildAvailable(
            RecallDomainSnapshot(
                windowDays = 7,
                topics = listOf(RecallDomainTopic("topic:a", "主题 A", clipCount = 1)),
                memories = listOf(
                    RecallDomainMemory(
                        id = "memory",
                        clipId = "pc_00000000000000000000000000000001",
                        primaryTopicId = "topic:a",
                        topicIds = listOf("topic:a"),
                        label = "Domain only",
                    ),
                ),
            ),
            null,
            MemoryPlanetWindow(kind = "week"),
        )
        assertEquals("Domain only", fallback?.topics?.single()?.memories?.single()?.title)
    }

    @Test
    fun resurfaceOnlyFallbackGroupsTopicsAndRemainsVisibleWhenDomainFails() {
        val fallback = MemoryPlanetFallback.buildAvailable(
            null,
            RecallResurfacePage(
                windowDays = 7,
                items = listOf(
                    surfaced(1, "topic:a", "主题 A"),
                    surfaced(2, "topic:a", "主题 A"),
                    surfaced(3, "topic:b", "主题 B"),
                ),
            ),
            MemoryPlanetWindow(kind = "week", days = 7),
        )
        assertEquals(listOf("topic:a", "topic:b"), fallback?.topics?.map { it.topicId })
        assertEquals(listOf(2, 1), fallback?.topics?.map { it.memories.size })
        assertTrue(fallback?.topics?.isNotEmpty() == true)
    }

    @Test
    fun resurfaceWithoutTopicBecomesUnclassifiedAndCrossTopicDuplicatesAppearOnce() {
        val duplicate = "pc_${"7".padStart(32, '0')}"
        val fallback = MemoryPlanetFallback.buildAvailable(
            null,
            RecallResurfacePage(
                windowDays = 7,
                items = listOf(
                    surfaced(1, "", ""),
                    surfaced(7, "topic:a", "主题 A"),
                    surfaced(7, "topic:b", "主题 B").copy(clipId = duplicate),
                    surfaced(2, "topic:b", "主题 B"),
                ),
            ),
            MemoryPlanetWindow(kind = "week", days = 7),
        )!!
        assertEquals(1, fallback.unclassifiedCount)
        assertEquals("pc_${"1".padStart(32, '0')}", fallback.unclassifiedPreview.single().clipId)
        assertEquals(
            1,
            fallback.topics.flatMap { it.memories }.count { it.clipId == duplicate },
        )
    }

    @Test
    fun domainTopicDefinitionsWinWhileResurfaceSupplementsTheirMemories() {
        val fallback = MemoryPlanetFallback.buildAvailable(
            RecallDomainSnapshot(
                windowDays = 7,
                topics = listOf(RecallDomainTopic("topic:a", "Domain A")),
            ),
            RecallResurfacePage(
                windowDays = 7,
                items = listOf(surfaced(1, "topic:a", "Resurface A")),
            ),
            MemoryPlanetWindow(kind = "week", days = 7),
        )!!
        assertEquals("Domain A", fallback.topics.single().displayName)
        assertEquals(1, fallback.topics.single().memories.size)
    }

    @Test
    fun blankResurfaceTopicUsesDomainPrimaryWithoutUnclassifiedDuplicate() {
        val clipX = "pc_${"20".padStart(32, '0')}"
        val fallback = MemoryPlanetFallback.buildAvailable(
            RecallDomainSnapshot(
                windowDays = 7,
                topics = listOf(RecallDomainTopic("topic:a", "Domain A")),
                memories = listOf(
                    RecallDomainMemory(
                        id = "domain-x",
                        clipId = clipX,
                        primaryTopicId = "topic:a",
                        topicIds = listOf("topic:a"),
                        label = "Domain X",
                    ),
                ),
            ),
            RecallResurfacePage(
                windowDays = 7,
                items = listOf(surfaced(20, "", "").copy(title = "Fresh X")),
            ),
            MemoryPlanetWindow(kind = "week", days = 7),
        )!!

        assertEquals(listOf(clipX), fallback.topics.single().memories.map { it.clipId })
        assertEquals("Fresh X", fallback.topics.single().memories.single().title)
        assertEquals(0, fallback.unclassifiedCount)
        assertTrue(fallback.unclassifiedPreview.isEmpty())
    }

    @Test
    fun domainTopicsResolveBlankResurfaceTopicsWithoutCrossRegionDuplicates() {
        val clipX = "pc_${"21".padStart(32, '0')}"
        val clipY = "pc_${"22".padStart(32, '0')}"
        val clipWithoutTopic = "pc_${"23".padStart(32, '0')}"
        val clipWithDomainMembership = "pc_${"24".padStart(32, '0')}"
        val fallback = MemoryPlanetFallback.buildAvailable(
            RecallDomainSnapshot(
                windowDays = 7,
                topics = listOf(RecallDomainTopic("topic:a", "Domain A")),
                memories = listOf(
                    RecallDomainMemory(
                        id = "domain-x",
                        clipId = clipX,
                        primaryTopicId = "topic:a",
                        topicIds = listOf("topic:a"),
                        label = "Domain X",
                    ),
                    RecallDomainMemory(
                        id = "domain-y",
                        clipId = clipY,
                        primaryTopicId = "topic:a",
                        topicIds = listOf("topic:a"),
                        label = "Domain Y",
                    ),
                    RecallDomainMemory(
                        id = "domain-unclassified",
                        clipId = clipWithoutTopic,
                        label = "Domain unclassified",
                    ),
                    RecallDomainMemory(
                        id = "domain-membership",
                        clipId = clipWithDomainMembership,
                        topicIds = listOf("topic:a"),
                        label = "Domain membership",
                    ),
                ),
            ),
            RecallResurfacePage(
                windowDays = 7,
                items = listOf(
                    surfaced(21, "", "").copy(
                        title = "Fresh X",
                        summary = "Fresh summary X",
                        sourceLabel = "Fresh source X",
                        capturedAt = "2026-07-24T08:00:00Z",
                    ),
                    surfaced(22, "topic:a", "Resurface A").copy(title = "Fresh Y"),
                    surfaced(23, "", "").copy(title = "Fresh unclassified"),
                    surfaced(24, "", "").copy(title = "Fresh membership"),
                ),
            ),
            MemoryPlanetWindow(kind = "week", days = 7),
        )!!

        val topic = fallback.topics.single()
        assertEquals("Domain A", topic.displayName)
        assertEquals(
            listOf(clipX, clipY, clipWithDomainMembership),
            topic.memories.map { it.clipId },
        )
        assertEquals("Fresh X", topic.memories.first().title)
        assertEquals("Fresh summary X", topic.memories.first().summary)
        assertEquals("Fresh source X", topic.memories.first().source)
        assertEquals("2026-07-24T08:00:00Z", topic.memories.first().capturedAt)
        assertEquals(1, fallback.unclassifiedCount)
        assertEquals(listOf(clipWithoutTopic), fallback.unclassifiedPreview.map { it.clipId })

        val allVisibleIds = topic.memories.map { it.clipId } +
            fallback.unclassifiedPreview.map { it.clipId }
        assertEquals(allVisibleIds.size, allVisibleIds.distinct().size)
    }

    @Test
    fun domainAndResurfaceRejectAnotherPeriodOrCustomRange() {
        val custom = MemoryPlanetWindow(
            kind = "custom",
            days = 5,
            startDate = "2026-07-01",
            endDate = "2026-07-05",
            timezone = "Asia/Shanghai",
        )
        val matchingDomain = RecallDomainSnapshot(
            windowDays = 5,
            windowStart = "2026-06-30T16:00:00Z",
            windowEnd = "2026-07-05T16:00:00Z",
        )
        val staleResurface = RecallResurfacePage(
            windowDays = 7,
            windowStart = "2026-06-28T16:00:00Z",
            windowEnd = "2026-07-05T16:00:00Z",
        )
        assertTrue(matchingDomain.matches(custom))
        assertFalse(staleResurface.matches(custom))
        assertFalse(matchingDomain.matches(custom.copy(endDate = "2026-07-06", days = 6)))
    }

    private fun client(
        code: Int,
        body: String,
        inspect: (Interceptor.Chain) -> Unit = {},
    ) = OkHttpClient.Builder().addInterceptor { chain ->
        inspect(chain)
        Response.Builder()
            .request(chain.request())
            .protocol(Protocol.HTTP_1_1)
            .code(code)
            .message("test")
            .body(body.toResponseBody("application/json".toMediaType()))
            .build()
    }.build()

    private fun settings() =
        PerClipSettings("http://127.0.0.1:18082/", "test-token", "test", true, false)

    private fun surfaced(index: Int, topicId: String, topicLabel: String) =
        RecallResurfaceItem(
            clipId = "pc_${index.toString().padStart(32, '0')}",
            topicId = topicId,
            topicLabel = topicLabel,
            title = "Resurface $index",
        )

    companion object {
        private const val PLANET =
            """{"ok":true,"planet":{"contract_version":"perclip.memory-planet.v1","window":{"kind":"custom","days":5,"start":"2026-07-01T00:00:00Z","end":"2026-07-06T00:00:00Z","start_date":"2026-07-01","end_date":"2026-07-05","timezone":"Asia/Shanghai"},"topics":[],"unclassified_count":0,"unclassified_preview":[],"has_more_unclassified":false}}"""
    }
}
