package com.sudox.perclip.recall.repository

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

/**
 * UI-independent access to the single Recall domain. Settings remain an explicit
 * argument because the Android app currently owns connection configuration.
 */
typealias RecallResult<T> = RecallApiResult<T>

interface RecallRepository {
    suspend fun overview(settings: PerClipSettings, days: Int = 7): RecallResult<RecallOverview>
    suspend fun topic(settings: PerClipSettings, topicId: String, days: Int = 7, filter: RecallTopicFilter = RecallTopicFilter.ALL): RecallResult<RecallTopicDetail>
    suspend fun weekly(settings: PerClipSettings, days: Int = 7): RecallResult<RecallWeeklyReview>
    suspend fun createSession(settings: PerClipSettings, request: RecallSessionRequest): RecallResult<RecallSessionResponse>
    suspend fun session(settings: PerClipSettings, sessionId: String): RecallResult<RecallSessionResponse>
    suspend fun action(settings: PerClipSettings, sessionId: String, itemId: String, request: RecallEventRequest): RecallResult<RecallEventResponse>
    suspend fun clip(settings: PerClipSettings, clipId: String): RecallResult<RecallClip>

    suspend fun domain(settings: PerClipSettings, request: RecallDomainRequest = RecallDomainRequest()): RecallResult<RecallDomainSnapshot>
    suspend fun resurface(settings: PerClipSettings, request: RecallResurfaceRequest = RecallResurfaceRequest()): RecallResult<RecallResurfacePage>
    suspend fun recordInteraction(settings: PerClipSettings, request: RecallInteractionRequest): RecallResult<RecallInteractionResult>
    suspend fun suppressions(settings: PerClipSettings, cursor: String = "", limit: Int = 50): RecallResult<RecallSuppressionPage>
    suspend fun memoryPlanet(settings: PerClipSettings, window: MemoryPlanetWindow): RecallResult<MemoryPlanet>
    suspend fun preferences(settings: PerClipSettings): RecallResult<RecallPreferences>
    suspend fun updatePreferences(settings: PerClipSettings, patch: RecallPreferencesPatch): RecallResult<RecallPreferences>
}
