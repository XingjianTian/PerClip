package com.sudox.perclip.config

import java.net.URI

data class SettingsValidationResult(
    val apiUrlError: String?,
    val tokenError: String?,
    val apiUrlWarning: String?,
) {
    val isValid: Boolean
        get() = apiUrlError == null && tokenError == null
}

object SettingsValidation {
    fun validate(apiUrl: String, ingestToken: String): SettingsValidationResult {
        val apiUrlError = validateApiUrl(apiUrl)
        return SettingsValidationResult(
            apiUrlError = apiUrlError,
            tokenError = validateToken(ingestToken),
            apiUrlWarning = if (apiUrlError == null) warnApiUrl(apiUrl) else null,
        )
    }

    fun validateApiUrl(apiUrl: String): String? {
        val value = apiUrl.trim()
        if (value.isBlank()) return "请填写服务地址。"
        if (!value.startsWith("http://", ignoreCase = true) && !value.startsWith("https://", ignoreCase = true)) {
            return "服务地址必须以 http:// 或 https:// 开头。"
        }

        val uri = runCatching { URI(value) }.getOrNull()
            ?: return "服务地址格式无效。"
        if (uri.scheme?.lowercase() !in setOf("http", "https")) {
            return "服务地址必须以 http:// 或 https:// 开头。"
        }
        if (uri.host.isNullOrBlank()) {
            return "服务地址需要包含主机名或 IP。"
        }
        if (!uri.userInfo.isNullOrBlank()) {
            return "服务地址不能包含用户名或密码。"
        }
        if (!uri.rawQuery.isNullOrBlank() || !uri.rawFragment.isNullOrBlank()) {
            return "服务地址不能包含查询参数或片段。"
        }
        return null
    }

    fun warnApiUrl(apiUrl: String): String? {
        val uri = runCatching { URI(apiUrl.trim()) }.getOrNull() ?: return null
        if (uri.scheme?.lowercase() != "http") return null
        val host = uri.host ?: return null
        if (isTrustedCleartextHost(host)) return null
        return "公网 HTTP 会明文传输 mobile token；公网地址建议使用 HTTPS，或改用 Tailscale/内网地址。"
    }

    fun validateToken(ingestToken: String): String? {
        val value = ingestToken.trim()
        if (value.isBlank()) return "请填写连接令牌。"
        if (value.any { it.isWhitespace() }) return "Token 不能包含空格或换行。"
        return null
    }

    private fun isTrustedCleartextHost(host: String): Boolean {
        val normalizedHost = host.trim().trim('[', ']').trimEnd('.').lowercase()
        if (normalizedHost == "localhost" || normalizedHost.endsWith(".localhost") || normalizedHost.endsWith(".local")) {
            return true
        }
        if (normalizedHost == "::1" ||
            normalizedHost.startsWith("fc") ||
            normalizedHost.startsWith("fd") ||
            normalizedHost.startsWith("fe80:")
        ) {
            return true
        }

        val ipv4Parts = parseIpv4Host(normalizedHost) ?: return false
        val first = ipv4Parts[0]
        val second = ipv4Parts[1]
        return first == 10 ||
            first == 127 ||
            (first == 172 && second in 16..31) ||
            (first == 192 && second == 168) ||
            (first == 169 && second == 254) ||
            (first == 100 && second in 64..127)
    }

    private fun parseIpv4Host(host: String): List<Int>? {
        val parts = host.split(".")
        if (parts.size != 4) return null
        return parts.map { part ->
            if (part.isBlank() || part.any { !it.isDigit() }) return null
            part.toIntOrNull()?.takeIf { it in 0..255 } ?: return null
        }
    }
}
