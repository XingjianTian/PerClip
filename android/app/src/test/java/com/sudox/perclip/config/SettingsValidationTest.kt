package com.sudox.perclip.config

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsValidationTest {
    @Test
    fun acceptsHttpAndHttpsApiUrls() {
        assertNull(SettingsValidation.validateApiUrl("http://100.64.0.10:18081"))
        assertNull(SettingsValidation.validateApiUrl("HTTP://100.64.0.10:18081"))
        assertNull(SettingsValidation.validateApiUrl("https://perclip.example.com/api"))
    }

    @Test
    fun rejectsBlankOrIncompleteApiUrls() {
        assertEquals("请填写服务地址。", SettingsValidation.validateApiUrl(" "))
        assertEquals("服务地址必须以 http:// 或 https:// 开头。", SettingsValidation.validateApiUrl("100.64.0.10:18081"))
        assertEquals("服务地址需要包含主机名或 IP。", SettingsValidation.validateApiUrl("http:///health"))
    }

    @Test
    fun rejectsApiUrlsWithCredentialsQueryOrFragment() {
        assertEquals(
            "服务地址不能包含用户名或密码。",
            SettingsValidation.validateApiUrl("https://user:pass@perclip.example.com"),
        )
        assertEquals(
            "服务地址不能包含查询参数或片段。",
            SettingsValidation.validateApiUrl("https://perclip.example.com?token=abc"),
        )
        assertEquals(
            "服务地址不能包含查询参数或片段。",
            SettingsValidation.validateApiUrl("https://perclip.example.com#mobile"),
        )
    }

    @Test
    fun rejectsBlankOrWhitespaceToken() {
        assertEquals("请填写连接令牌。", SettingsValidation.validateToken(""))
        assertEquals("Token 不能包含空格或换行。", SettingsValidation.validateToken("abc def"))
        assertEquals("Token 不能包含空格或换行。", SettingsValidation.validateToken("abc\ndef"))
    }

    @Test
    fun warnsForPublicHttpApiUrlsWithoutBlockingSave() {
        val result = SettingsValidation.validate("http://perclip.example.com:18081", "mobile-token")

        assertTrue(result.isValid)
        assertEquals(
            "公网 HTTP 会明文传输 mobile token；公网地址建议使用 HTTPS，或改用 Tailscale/内网地址。",
            result.apiUrlWarning,
        )
    }

    @Test
    fun doesNotWarnForHttpsOrTrustedCleartextHosts() {
        assertNull(SettingsValidation.warnApiUrl("https://perclip.example.com"))
        assertNull(SettingsValidation.warnApiUrl("http://100.64.0.10:18081"))
        assertNull(SettingsValidation.warnApiUrl("http://192.168.1.8:18081"))
        assertNull(SettingsValidation.warnApiUrl("http://10.0.2.2:18081"))
        assertNull(SettingsValidation.warnApiUrl("http://172.20.1.8:18081"))
        assertNull(SettingsValidation.warnApiUrl("http://localhost:18081"))
        assertNull(SettingsValidation.warnApiUrl("http://perclip.local:18081"))
    }

    @Test
    fun combinesApiUrlAndTokenState() {
        val valid = SettingsValidation.validate("http://100.64.0.10:18081", "mobile-token")
        val invalid = SettingsValidation.validate("ftp://100.64.0.10", " ")

        assertTrue(valid.isValid)
        assertFalse(invalid.isValid)
    }
}
