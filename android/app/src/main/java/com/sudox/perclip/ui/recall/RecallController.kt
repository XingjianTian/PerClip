package com.sudox.perclip.ui.recall

import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.recall.RecallApiResult
import com.sudox.perclip.recall.RecallEventRequest
import com.sudox.perclip.recall.RecallEventResponse
import com.sudox.perclip.recall.RecallOverview
import com.sudox.perclip.recall.RecallClip
import com.sudox.perclip.recall.RecallSessionRequest
import com.sudox.perclip.recall.RecallSessionResponse
import com.sudox.perclip.recall.RecallTopicDetail
import com.sudox.perclip.recall.RecallTopicFilter
import com.sudox.perclip.recall.RecallWeeklyReview
import com.sudox.perclip.recall.repository.NetworkRecallRepository
import com.sudox.perclip.recall.repository.RecallRepository
import com.sudox.perclip.recall.repository.RecallDomainRequest
import com.sudox.perclip.recall.repository.RecallDomainSnapshot
import com.sudox.perclip.recall.repository.RecallInteractionRequest
import com.sudox.perclip.recall.repository.RecallInteractionResult
import com.sudox.perclip.recall.repository.RecallResurfacePage
import com.sudox.perclip.recall.repository.RecallResurfaceRequest
import com.sudox.perclip.recall.repository.MemoryPlanet
import com.sudox.perclip.recall.repository.MemoryPlanetWindow
import com.sudox.perclip.recall.repository.RecallSuppressedItem
import com.sudox.perclip.recall.repository.RecallSuppressionPage

/** UI-friendly facade. Blocking network work belongs to [RecallRepository], never Compose. */
class RecallController(private val repository: RecallRepository = NetworkRecallRepository()) {
    suspend fun domain(settings: PerClipSettings, request: RecallDomainRequest): RecallApiResult<RecallDomainSnapshot> =
        repository.domain(settings, request)

    suspend fun resurface(settings: PerClipSettings, request: RecallResurfaceRequest): RecallApiResult<RecallResurfacePage> =
        repository.resurface(settings, request)

    suspend fun recordInteraction(settings: PerClipSettings, request: RecallInteractionRequest): RecallApiResult<RecallInteractionResult> =
        repository.recordInteraction(settings, request)

    suspend fun suppressions(settings: PerClipSettings, cursor: String = "", limit: Int = 50): RecallApiResult<RecallSuppressionPage> =
        repository.suppressions(settings, cursor, limit)

    suspend fun memoryPlanet(settings: PerClipSettings, window: MemoryPlanetWindow): RecallApiResult<MemoryPlanet> =
        repository.memoryPlanet(settings, window)

    suspend fun overview(settings: PerClipSettings, days: Int = 7): RecallApiResult<RecallOverview> =
        repository.overview(settings, days)

    suspend fun topic(settings: PerClipSettings, topicId: String, days: Int = 7, filter: RecallTopicFilter = RecallTopicFilter.ALL): RecallApiResult<RecallTopicDetail> =
        repository.topic(settings, topicId, days, filter)

    suspend fun createSession(settings: PerClipSettings, request: RecallSessionRequest): RecallApiResult<RecallSessionResponse> =
        repository.createSession(settings, request)

    suspend fun session(settings: PerClipSettings, sessionId: String): RecallApiResult<RecallSessionResponse> =
        repository.session(settings, sessionId)

    suspend fun action(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest): RecallApiResult<RecallEventResponse> =
        repository.action(settings, sessionId, itemId, request)

    suspend fun weekly(settings: PerClipSettings, days: Int = 7): RecallApiResult<RecallWeeklyReview> =
        repository.weekly(settings, days)

    suspend fun clip(settings: PerClipSettings, clipId: String): RecallApiResult<RecallClip> =
        repository.clip(settings, clipId)
}
