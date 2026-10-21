package com.sudox.perclip.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class CaptureSaveFailurePolicyTest {
    @Test
    fun localFailureDoesNotExposeExceptionDetails() {
        val message = CaptureSaveFailurePolicy.userMessage(
            IllegalStateException("/private/app/path: permission denied"),
        )

        assertEquals("本地保存失败，请重试。", message)
        assertFalse(message.contains("/private"))
        assertFalse(message.contains("permission"))
    }
}
