package com.sudox.perclip.upload

import com.sudox.perclip.SharedClip
import com.sudox.perclip.SharedClipItem
import com.sudox.perclip.config.PerClipSettings
import java.io.File
import java.io.IOException
import java.time.ZoneId
import java.time.Instant
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException

class PersonalClipsApi(
    private val client: OkHttpClient = uploadClient(),
    private val healthClient: OkHttpClient = healthClient(),
) {
    fun health(settings: PerClipSettings): UploadResult {
        val normalizedSettings = settings.normalized()
        if (!normalizedSettings.hasUploadConfig) {
            return UploadResult(
                ok = false,
                title = "连接测试",
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = "请先完成连接设置。",
            )
        }
        val request = Request.Builder()
            .url("${normalizedSettings.apiUrl}/api/mobile-clips/verify")
            .header("Authorization", "Bearer ${normalizedSettings.ingestToken}")
            .get()
            .build()
        return try {
            healthClient.newCall(request).execute().use { response ->
                val bodyText = response.body.string()
                if (response.isSuccessful) {
                    VerifyResponseParser.parse(bodyText)
                } else {
                    UploadResult(
                        ok = false,
                        title = "连接测试",
                        originalPath = "",
                        ragflowDocumentId = "",
                        duplicate = false,
                        message = "HTTP ${response.code}: 保存失败。",
                    )
                }
            }
        } catch (error: IOException) {
            UploadResult(
                ok = false,
                title = "连接测试",
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = error.message ?: "连接失败",
            )
        } catch (error: IllegalArgumentException) {
            UploadResult(
                ok = false,
                title = "连接测试",
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = error.message ?: "服务地址无效",
            )
        } catch (error: JSONException) {
            UploadResult(
                ok = false,
                title = "连接测试",
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = VerifyResponseParser.INVALID_VERIFY_MESSAGE,
            )
        }
    }

    fun upload(
        settings: PerClipSettings,
        clip: SharedClip,
        note: String,
        item: SharedClipItem?,
        cachedFile: File?,
        clientRequestId: String? = null,
        titleHint: String? = null,
        capture: UploadPartMetadata? = null,
        targetKnowledgeBaseId: String = "",
        routingMode: String = "",
        capturedAtEpochMs: Long,
        capturedTimezone: String,
    ): UploadResult {
        val normalizedSettings = settings.normalized()
        val partMetadata = capture ?: if (item == null) {
            UploadPartPlanner.forClip(clip)
        } else {
            UploadPartPlanner.forItem(
                clip = clip,
                displayName = item.displayName,
                mimeType = item.mimeType,
                itemIndex = null,
                totalItems = 1,
            )
        }
        val resolvedTitleHint = titleHint ?: partMetadata.titleHint
        val resolvedClientRequestId = clientRequestId ?: partMetadata.clientRequestId

        if (!normalizedSettings.hasUploadConfig) {
            return UploadResult(
                ok = false,
                title = resolvedTitleHint,
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = "请先在设置中完成连接设置。",
            )
        }
        if (item != null && !CachedPayloadFiles.isUsable(cachedFile)) {
            return UploadResult(
                ok = false,
                title = resolvedTitleHint,
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = CachedPayloadFiles.MISSING_FILE_MESSAGE,
            )
        }

        val form = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addText("source_type", clip.kind.toServerSourceType())
            .addText("title_hint", resolvedTitleHint)
            .addText("note", note)
            .addText("text", clip.text)
            .addText("url", clip.url)
            .addText("mime_type", item?.mimeType ?: clip.mimeType)
            .addText("device_name", normalizedSettings.deviceName)
            .addText("source_app", clip.sourceApp)
            .addText("captured_at", Instant.ofEpochMilli(capturedAtEpochMs).toString())
            .addText("client_request_id", resolvedClientRequestId)
            .addText("client_batch_id", partMetadata.clientBatchId)
            .addText("parent_client_request_id", partMetadata.parentClientRequestId)
            .addText("client_part_index", partMetadata.partIndex.toString())
            .addText("client_part_count", partMetadata.partCount.toString())
            .addText("part_role", partMetadata.partRole)
            .addText("source_intent", partMetadata.sourceIntent)
            .addText("captured_timezone", CaptureTimezone.normalize(capturedTimezone))

        routingMode.trim().takeIf { it.isNotBlank() }?.let { mode ->
            form.addText("routing_mode", mode)
        }

        targetKnowledgeBaseId.trim()
            .takeIf { it.isNotBlank() }
            ?.let { targetId ->
            form.addText("target_knowledge_base_id", targetId)
        }

        if (item != null && cachedFile != null) {
            form.addFormDataPart(
                "file",
                item.displayName,
                cachedFile.asRequestBody(item.mimeType.toMediaTypeOrNull()),
            )
        }

        val request = Request.Builder()
            .url("${normalizedSettings.apiUrl}/api/mobile-clips")
            .header("Authorization", "Bearer ${normalizedSettings.ingestToken}")
            .post(form.build())
            .build()

        return try {
            client.newCall(request).execute().use { response ->
                val bodyText = response.body.string()
                if (!response.isSuccessful) {
                    return UploadResult(
                        ok = false,
                        title = resolvedTitleHint,
                        originalPath = "",
                        ragflowDocumentId = "",
                        duplicate = false,
                        message = "HTTP ${response.code}: 保存失败。",
                        retryable = UploadFailurePolicy.isRetryableHttpStatus(response.code),
                    )
                }
                UploadResponseParser.parseSuccessfulUpload(bodyText, resolvedTitleHint)
            }
        } catch (error: IOException) {
            UploadResult(
                ok = false,
                title = resolvedTitleHint,
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = error.message ?: "网络请求失败",
                retryable = true,
            )
        } catch (error: JSONException) {
            UploadResult(
                ok = false,
                title = resolvedTitleHint,
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = UploadResponseParser.INVALID_RESPONSE_MESSAGE,
            )
        } catch (error: IllegalArgumentException) {
            UploadResult(
                ok = false,
                title = resolvedTitleHint,
                originalPath = "",
                ragflowDocumentId = "",
                duplicate = false,
                message = error.message ?: "保存参数无效",
            )
        }
    }

    private fun MultipartBody.Builder.addText(name: String, value: String): MultipartBody.Builder {
        return addFormDataPart(name, null, value.toRequestBody("text/plain; charset=utf-8".toMediaTypeOrNull()))
    }

    companion object {
        private const val HEALTH_TIMEOUT_SECONDS = 10L
        private const val UPLOAD_TIMEOUT_SECONDS = 120L

        private fun healthClient(): OkHttpClient {
            return OkHttpClient.Builder()
                .connectTimeout(HEALTH_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .readTimeout(HEALTH_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .writeTimeout(HEALTH_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .callTimeout(HEALTH_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .build()
        }

        private fun uploadClient(): OkHttpClient {
            return OkHttpClient.Builder()
                .connectTimeout(HEALTH_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .readTimeout(UPLOAD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .writeTimeout(UPLOAD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .callTimeout(UPLOAD_TIMEOUT_SECONDS, TimeUnit.SECONDS)
                .build()
        }
    }
}

object CaptureTimezone {
    fun normalize(value: String): String = runCatching { ZoneId.of(value.trim()).id }.getOrDefault("UTC")
}
