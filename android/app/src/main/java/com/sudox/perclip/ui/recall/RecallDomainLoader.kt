package com.sudox.perclip.ui.recall

import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.recall.RecallApiResult
import com.sudox.perclip.recall.repository.RecallDomainRequest
import com.sudox.perclip.recall.repository.RecallDomainSnapshot

/** Shared domain loader for Recall Home and the Settings memory-planet shortcut. */
class RecallDomainLoader(
    private val request: suspend (PerClipSettings, RecallDomainRequest) -> RecallApiResult<RecallDomainSnapshot>,
) {
    fun begin(holder: RecallStateHolder, showLoading: Boolean = true): Long {
        val generation = holder.beginDomain()
        if (showLoading) {
            holder.update { current ->
                current.copy(domain = current.domain.copy(loading = true, error = ""))
            }
        }
        return generation
    }

    suspend fun complete(
        holder: RecallStateHolder,
        generation: Long,
        settings: PerClipSettings,
        domainRequest: RecallDomainRequest,
    ): Boolean {
        val result = request(settings, domainRequest)
        if (!holder.isDomainCurrent(generation)) return false
        holder.update { current ->
            if (result.ok && result.value != null) {
                RecallUiReducer.domainLoaded(current, result.value)
            } else {
                RecallUiReducer.domainFailed(current, result.message.safeRecallMessage())
            }
        }
        return true
    }

    suspend fun load(
        holder: RecallStateHolder,
        settings: PerClipSettings,
        domainRequest: RecallDomainRequest,
    ): Boolean = complete(holder, begin(holder), settings, domainRequest)
}

internal fun String.safeRecallMessage(): String = trim().takeIf { message ->
    message.isNotBlank() && !message.contains("<html", ignoreCase = true)
} ?: "暂时无法加载记忆星球内容，请稍后重试。"
