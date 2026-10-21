package com.sudox.perclip.recall

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RecallApiErrorTest {
    @Test
    fun rootFeature404ExplainsServerMismatch() {
        val message = RecallApiError.http(404, "<html>proxy error</html>", "/api/recall/overview?days=7")
        assertEquals("当前服务端未提供记忆星球接口，请更新服务端或检查 API 地址", message)
        assertFalse(message.contains("html", ignoreCase = true))
    }

    @Test
    fun item404ExplainsExpiredContent() {
        assertEquals(
            "对应内容不存在或已失效",
            RecallApiError.http(404, "not found", "/api/recall/topics/topic-1"),
        )
    }

    @Test
    fun authenticationIsDistinct() {
        assertEquals(
            "认证失败，请检查连接令牌",
            RecallApiError.http(401, "<html>denied</html>", "/api/recall/overview"),
        )
    }
}
