package com.sudox.perclip.capabilities

import com.sudox.perclip.config.PerClipSettings
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONException

class AppCapabilitiesApi(
    private val client: OkHttpClient = defaultClient(),
) {
    fun fetch(settings: PerClipSettings): AppCapabilityResult {
        val normalized = settings.normalized()
        if (!normalized.hasUploadConfig) {
            return failure(AppCapabilityFailure.CONFIGURATION, "请先完成连接设置。")
        }
        val request = try {
            Request.Builder()
                .url("${normalized.apiUrl}/api/app-capabilities")
                .header("Authorization", "Bearer ${normalized.ingestToken}")
                .get()
                .build()
        } catch (_: IllegalArgumentException) {
            return failure(AppCapabilityFailure.CONFIGURATION, "服务地址无效。")
        }
        return try {
            client.newCall(request).execute().use { response ->
                val body = response.body.string()
                when (response.code) {
                    401, 403 -> failure(AppCapabilityFailure.AUTHENTICATION, "服务端可连接，但认证失败，请检查连接令牌。")
                    404 -> failure(AppCapabilityFailure.CONTRACT_MISSING, MISSING_CONTRACT_MESSAGE)
                    in 500..599 -> failure(AppCapabilityFailure.SERVER, "服务端暂时不可用（HTTP ${response.code}）。")
                    else -> if (!response.isSuccessful) {
                        failure(AppCapabilityFailure.SERVER, "服务端返回 HTTP ${response.code}。")
                    } else {
                        parseSuccess(body)
                    }
                }
            }
        } catch (_: IOException) {
            failure(AppCapabilityFailure.UNREACHABLE, "无法连接服务器，请检查 API 地址和网络。")
        } catch (_: JSONException) {
            failure(AppCapabilityFailure.INVALID_RESPONSE, "服务端可连接，但能力响应格式无法解析。")
        }
    }

    private fun parseSuccess(body: String): AppCapabilityResult {
        val capabilities = AppCapabilitiesJson.parse(body)
        if (!capabilities.isCurrentPerClipApi) {
            return failure(AppCapabilityFailure.CONTRACT_MISMATCH, MISSING_CONTRACT_MESSAGE)
        }
        if (!capabilities.features.complete) {
            return AppCapabilityResult(
                ok = true,
                capabilities = capabilities,
                failure = AppCapabilityFailure.FEATURES_INCOMPLETE,
                message = "PerClip API 已连接，部分功能可用。",
            )
        }
        return AppCapabilityResult(true, capabilities, message = "PerClip API 连接正常，完整功能可用。")
    }

    private fun failure(type: AppCapabilityFailure, message: String) =
        AppCapabilityResult(ok = false, failure = type, message = message)

    companion object {
        const val MISSING_CONTRACT_MESSAGE =
            "服务端可连接，但不是当前版本的完整 PerClip API。请更新服务端或检查 API 地址/反向代理。"
        private const val TIMEOUT_SECONDS = 10L

        private fun defaultClient() = OkHttpClient.Builder()
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .callTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .build()
    }
}
