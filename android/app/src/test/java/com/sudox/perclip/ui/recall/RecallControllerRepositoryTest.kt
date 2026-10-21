package com.sudox.perclip.ui.recall

import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.recall.RecallApiResult
import com.sudox.perclip.recall.RecallClip
import com.sudox.perclip.recall.RecallEventRequest
import com.sudox.perclip.recall.RecallEventResponse
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallSessionRequest
import com.sudox.perclip.recall.RecallSessionResponse
import com.sudox.perclip.recall.RecallTopicDetail
import com.sudox.perclip.recall.RecallTopicFilter
import com.sudox.perclip.recall.RecallWeeklyReview
import com.sudox.perclip.recall.repository.RecallDomainRequest
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallDomainTopic
import com.sudox.perclip.recall.repository.RecallInteractionRequest
import com.sudox.perclip.recall.repository.RecallInteractionResult
import com.sudox.perclip.recall.repository.RecallPreferences
import com.sudox.perclip.recall.repository.RecallPreferencesPatch
import com.sudox.perclip.recall.repository.RecallRepository
import com.sudox.perclip.recall.repository.RecallResurfacePage
import com.sudox.perclip.recall.repository.RecallResurfaceRequest
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.recall.repository.RecallSuppressionPage
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class RecallControllerRepositoryTest {
    @Test fun controllerAndSharedDomainLoaderUseInjectableRepository() = runBlocking {
        val fake = FakeRepository()
        val controller = RecallController(fake)
        assertEquals("from-fake", controller.overview(settings()).value?.highlights?.single()?.title)
        val holder = RecallStateHolder()
        RecallDomainLoader(controller::domain).load(holder, settings(), RecallDomainRequest(days = 7, topicLimit = 5))
        assertEquals("topic-1", holder.state.domain.value?.topics?.single()?.id)
        assertEquals(false, holder.state.domain.loading)
        assertEquals(listOf("overview", "domain"), fake.calls)

        RecallDomainLoader { _, _ -> RecallApiResult.failure("failed safely") }
            .load(holder, settings(), RecallDomainRequest())
        assertEquals("failed safely", holder.state.domain.error)
        assertEquals(false, holder.state.domain.loading)
    }

    private fun settings() = PerClipSettings("http://127.0.0.1:18080/", "mobile-token", "test", true, false)

    private class FakeRepository : RecallRepository {
        val calls = mutableListOf<String>()
        override suspend fun overview(settings: PerClipSettings, days: Int): RecallApiResult<RecallOverview> {
            calls += "overview"
            return RecallApiResult.success(RecallOverview(highlights = listOf(com.sudox.perclip.recall.RecallHighlight(title = "from-fake"))))
        }
        override suspend fun topic(settings: PerClipSettings, topicId: String, days: Int, filter: RecallTopicFilter): RecallApiResult<RecallTopicDetail> = RecallApiResult.failure("unused")
        override suspend fun weekly(settings: PerClipSettings, days: Int): RecallApiResult<RecallWeeklyReview> = RecallApiResult.failure("unused")
        override suspend fun createSession(settings: PerClipSettings, request: RecallSessionRequest): RecallApiResult<RecallSessionResponse> = RecallApiResult.failure("unused")
        override suspend fun session(settings: PerClipSettings, sessionId: String): RecallApiResult<RecallSessionResponse> = RecallApiResult.failure("unused")
        override suspend fun action(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest): RecallApiResult<RecallEventResponse> = RecallApiResult.failure("unused")
        override suspend fun clip(settings: PerClipSettings, clipId: String): RecallApiResult<RecallClip> = RecallApiResult.failure("unused")
        override suspend fun domain(settings: PerClipSettings, request: RecallDomainRequest): RecallApiResult<RecallDomainSnapshot> {
            calls += "domain"
            return RecallApiResult.success(RecallDomainSnapshot(topics = listOf(RecallDomainTopic("topic-1", "主题"))))
        }
        override suspend fun resurface(settings: PerClipSettings, request: RecallResurfaceRequest): RecallApiResult<RecallResurfacePage> = RecallApiResult.failure("unused")
        override suspend fun recordInteraction(settings: PerClipSettings, request: RecallInteractionRequest): RecallApiResult<RecallInteractionResult> = RecallApiResult.failure("unused")
        override suspend fun suppressions(settings: PerClipSettings, cursor: String, limit: Int): RecallApiResult<RecallSuppressionPage> =
            RecallApiResult.success(RecallSuppressionPage())
        override suspend fun memoryPlanet(settings: PerClipSettings, window: com.sudox.perclip.recall.repository.MemoryPlanetWindow): RecallApiResult<com.sudox.perclip.recall.repository.MemoryPlanet> = RecallApiResult.failure("unused")
        override suspend fun preferences(settings: PerClipSettings): RecallApiResult<RecallPreferences> = RecallApiResult.failure("unused")
        override suspend fun updatePreferences(settings: PerClipSettings, patch: RecallPreferencesPatch): RecallApiResult<RecallPreferences> = RecallApiResult.failure("unused")
    }
}
