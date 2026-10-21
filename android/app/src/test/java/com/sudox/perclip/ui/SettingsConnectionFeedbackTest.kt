package com.sudox.perclip.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsConnectionFeedbackTest {
    @Test
    fun leavesConnectionSuccessMessageUnchangedWhenNothingWasRequeued() {
        assertEquals(
            "连接与 token 正常。",
            SettingsConnectionFeedback.successMessage("连接与 token 正常。", requeuedCount = 0),
        )
    }

    @Test
    fun appendsRequeuedWaitingRecordCount() {
        assertEquals(
            "连接与 token 正常。 已重新排队 2 条待同步记录。",
            SettingsConnectionFeedback.successMessage("连接与 token 正常。", requeuedCount = 2),
        )
    }
}
