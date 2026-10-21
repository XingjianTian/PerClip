package com.sudox.perclip.recall.repository

import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.recall.RecallApi
import com.sudox.perclip.recall.RecallClip
import com.sudox.perclip.recall.RecallEventRequest
import com.sudox.perclip.recall.RecallEventResponse
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallSessionRequest
import com.sudox.perclip.recall.RecallSessionResponse
import com.sudox.perclip.recall.RecallTopicDetail
import com.sudox.perclip.recall.RecallTopicFilter
import com.sudox.perclip.recall.RecallWeeklyReview
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Production repository: old and new endpoint projections share one caller-facing boundary. */
class NetworkRecallRepository(
    private val recallApi: RecallApi = RecallApi(),
    private val domainApi: RecallDomainApi = RecallDomainApi(),
) : RecallRepository {
    override suspend fun overview(settings: PerClipSettings, days: Int): RecallResult<RecallOverview> = io { recallApi.recallOverview(settings, days) }
    override suspend fun topic(settings: PerClipSettings, topicId: String, days: Int, filter: RecallTopicFilter): RecallResult<RecallTopicDetail> = io { recallApi.recallTopic(settings, topicId, days, filter) }
    override suspend fun weekly(settings: PerClipSettings, days: Int): RecallResult<RecallWeeklyReview> = io { recallApi.weeklyReview(settings, days) }
    override suspend fun createSession(settings: PerClipSettings, request: RecallSessionRequest): RecallResult<RecallSessionResponse> = io { recallApi.createRecallSession(settings, request) }
    override suspend fun session(settings: PerClipSettings, sessionId: String): RecallResult<RecallSessionResponse> = io { recallApi.getRecallSession(settings, sessionId) }
    override suspend fun action(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest): RecallResult<RecallEventResponse> = io { recallApi.applyRecallAction(settings, sessionId, itemId, request) }
    override suspend fun clip(settings: PerClipSettings, clipId: String): RecallResult<RecallClip> = io { recallApi.recallClip(settings, clipId) }
    override suspend fun domain(settings: PerClipSettings, request: RecallDomainRequest): RecallResult<RecallDomainSnapshot> = io { domainApi.domain(settings, request) }
    override suspend fun resurface(settings: PerClipSettings, request: RecallResurfaceRequest): RecallResult<RecallResurfacePage> = io { domainApi.resurface(settings, request) }
    override suspend fun recordInteraction(settings: PerClipSettings, request: RecallInteractionRequest): RecallResult<RecallInteractionResult> = io { domainApi.interaction(settings, request) }
    override suspend fun suppressions(settings: PerClipSettings, cursor: String, limit: Int): RecallResult<RecallSuppressionPage> = io { domainApi.suppressions(settings, cursor, limit) }
    override suspend fun memoryPlanet(settings: PerClipSettings, window: MemoryPlanetWindow): RecallResult<MemoryPlanet> = io { domainApi.memoryPlanet(settings, window) }
    override suspend fun preferences(settings: PerClipSettings): RecallResult<RecallPreferences> = io { domainApi.preferences(settings) }
    override suspend fun updatePreferences(settings: PerClipSettings, patch: RecallPreferencesPatch): RecallResult<RecallPreferences> = io { domainApi.updatePreferences(settings, patch) }
    private suspend fun <T> io(block: () -> RecallResult<T>) = withContext(Dispatchers.IO) { block() }
}
