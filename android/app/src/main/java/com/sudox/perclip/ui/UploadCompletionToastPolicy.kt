package com.sudox.perclip.ui

import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus

object UploadCompletionToastPolicy {
    const val UPLOADED_MESSAGE = "已保存，后台处理完成。"

    data class State(
        val initialized: Boolean = false,
        val announcedUploadedClipIds: Set<String> = emptySet(),
    )

    data class Evaluation(
        val state: State,
        val newlyUploadedClipIds: List<String>,
    )

    fun evaluate(
        records: List<UploadRecord>,
        state: State,
    ): Evaluation {
        val uploadedClipIds = records
            .asSequence()
            .filter { it.status == UploadStatus.Uploaded }
            .map { it.clip.id }
            .distinct()
            .toList()
        if (!state.initialized) {
            return Evaluation(
                state = State(
                    initialized = true,
                    announcedUploadedClipIds = uploadedClipIds.toSet(),
                ),
                newlyUploadedClipIds = emptyList(),
            )
        }

        val newlyUploadedClipIds = uploadedClipIds.filterNot(state.announcedUploadedClipIds::contains)
        return Evaluation(
            state = state.copy(
                announcedUploadedClipIds = state.announcedUploadedClipIds + newlyUploadedClipIds,
            ),
            newlyUploadedClipIds = newlyUploadedClipIds,
        )
    }
}
