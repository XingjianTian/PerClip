package com.sudox.perclip

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.ClipData
import android.content.ClipboardManager
import android.net.Uri
import android.os.Environment
import android.os.SystemClock
import android.provider.MediaStore
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.sudox.perclip.data.ClipQueueStore
import com.sudox.perclip.screen.ScreenClipSnapshot
import com.sudox.perclip.screen.ScreenClipStore
import com.sudox.perclip.capture.CaptureRoutingMode
import com.sudox.perclip.upload.CachedPayloadCleaner
import java.io.File
import java.lang.ref.WeakReference
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ShareCaptureActivityInstrumentedTest {
    private lateinit var context: Context
    private lateinit var store: ClipQueueStore
    private val insertedMedia = mutableListOf<Uri>()
    private val createdQueueIds = mutableSetOf<String>()

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        store = ClipQueueStore(context)
    }

    @After
    fun tearDown() {
        insertedMedia.forEach { uri -> context.contentResolver.delete(uri, null, null) }
        createdQueueIds.forEach { id ->
            store.remove(id)?.let { CachedPayloadCleaner.deleteCachedPayloads(it, context.cacheDir) }
        }
        context.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(
            ClipData.newPlainText("", ""),
        )
    }

    @Test
    fun existingMainActivitySurvivesShareAndIndependentSharesCreateIndependentRecords() {
        val before = queueIds()
        val mainScenario = ActivityScenario.launch(MainActivity::class.java)
        lateinit var originalMain: WeakReference<MainActivity>
        mainScenario.onActivity { originalMain = WeakReference(it) }

        launchShare(textIntent("Stage 23.8D3A synthetic repeat"))
        val first = awaitNewQueueIds(before, expected = 1).single()
        launchShare(textIntent("Stage 23.8D3A synthetic repeat"))
        val second = awaitNewQueueIds(before, expected = 2).single { it != first }

        assertNotEquals(first, second)
        mainScenario.onActivity { activity ->
            assertSame(originalMain.get(), activity)
            assertFalse(activity.isFinishing)
            assertFalse(activity.isDestroyed)
        }
        mainScenario.close()
    }

    @Test
    fun textUrlImageFileMultipleAndInvalidShareUseTransientLocalCapture() {
        var baseline = queueIds()

        launchShare(textIntent("Stage 23.8D3A synthetic text"))
        val textIds = awaitNewQueueIds(baseline, 1)
        baseline += textIds

        launchShare(textIntent("https://example.com/perclip-stage-23-8d3a"))
        val urlIds = awaitNewQueueIds(baseline, 1)
        baseline += urlIds

        val image = insertMedia("stage23-8d3a-image.png", "image/png", byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47))
        launchShare(streamIntent(Intent.ACTION_SEND, "image/png", arrayListOf(image)))
        val imageIds = awaitNewQueueIds(baseline, 1)
        assertCachedItemsExist(imageIds.single())
        createdQueueIds += imageIds
        baseline += imageIds

        val file = insertMedia("stage23-8d3a-file.pdf", "application/pdf", "%PDF-synthetic".toByteArray())
        launchShare(streamIntent(Intent.ACTION_SEND, "application/pdf", arrayListOf(file)))
        val fileIds = awaitNewQueueIds(baseline, 1)
        assertCachedItemsExist(fileIds.single())
        createdQueueIds += fileIds
        baseline += fileIds

        val secondFile = insertMedia("stage23-8d3a-note.txt", "text/plain", "synthetic".toByteArray())
        launchShare(streamIntent(Intent.ACTION_SEND_MULTIPLE, "*/*", arrayListOf(file, secondFile)))
        val multipleIds = awaitNewQueueIds(baseline, 1)
        assertCachedItemsExist(multipleIds.single(), expectedItems = 2)
        createdQueueIds += multipleIds
        baseline += multipleIds

        launchShare(Intent(Intent.ACTION_SEND).setType("text/plain"))
        SystemClock.sleep(600)
        assertEquals(baseline, queueIds())
    }

    @Test
    fun douyinTextShareCreatesOneDefaultOnlyLocalUrlCapture() {
        val before = queueIds()
        val shared = "复制打开抖音，看看【示例作者的作品】 payload 内的视频简介 #科普 https://v.douyin.com/AbC123/ Xy9:/ 08/12"
        val intent = textIntent(shared)
            .putExtra(Intent.EXTRA_REFERRER_NAME, "android-app://com.ss.android.ugc.aweme")

        launchShare(intent)
        val id = awaitNewQueueIds(before, expected = 1).single()
        val queued = requireNotNull(store.find(id))

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, queued.metadata.routingMode)
        assertEquals(ClipKind.Url, queued.kind)
        assertEquals("payload 内的视频简介 #科普", queued.titleHint)
        assertEquals("https://v.douyin.com/AbC123/", queued.url)
        assertEquals(shared, queued.text)
        assertEquals("com.ss.android.ugc.aweme", queued.sourceApp)
        assertEquals(setOf(id), queueIds() - before)
        createdQueueIds += id
    }

    @Test
    fun xiaohongshuTextShareCreatesOneDefaultOnlyLocalUrlCapture() {
        val before = queueIds()
        val shared = "payload 内的图文标题 #露营 https://xhslink.com/a/AbC123 戳进【小红书】看看这篇好文！"
        val intent = textIntent(shared)
            .putExtra(Intent.EXTRA_REFERRER_NAME, "android-app://com.xingin.xhs")

        launchShare(intent)
        val id = awaitNewQueueIds(before, expected = 1).single()
        val queued = requireNotNull(store.find(id))

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, queued.metadata.routingMode)
        assertEquals(ClipKind.Url, queued.kind)
        assertEquals("payload 内的图文标题 #露营", queued.titleHint)
        assertEquals("https://xhslink.com/a/AbC123", queued.url)
        assertEquals(shared, queued.text)
        assertEquals("com.xingin.xhs", queued.sourceApp)
        assertEquals(setOf(id), queueIds() - before)
        createdQueueIds += id
    }

    @Test
    fun weChatOfficialAccountShareCreatesOneDefaultOnlyLocalUrlCapture() {
        val before = queueIds()
        val shared = "https://mp.weixin.qq.com/s/syntheticArticle123"
        val subject = "公众号 payload 内已有的文章标题"
        val intent = textIntent(shared)
            .putExtra(Intent.EXTRA_SUBJECT, subject)
            .putExtra(Intent.EXTRA_REFERRER_NAME, "android-app://com.tencent.mm")

        launchShare(intent)
        val id = awaitNewQueueIds(before, expected = 1).single()
        val queued = requireNotNull(store.find(id))

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, queued.metadata.routingMode)
        assertEquals(ClipKind.Url, queued.kind)
        assertEquals(subject, queued.titleHint)
        assertEquals(shared, queued.url)
        assertEquals(shared, queued.text)
        assertEquals("com.tencent.mm", queued.sourceApp)
        assertEquals(setOf(id), queueIds() - before)
        createdQueueIds += id
    }

    @Test
    fun activityRecreationReusesRequestIdAndOneCachePath() {
        val before = queueIds()
        val cacheBefore = cachedPayloadPaths()
        val intent = streamIntent(
            Intent.ACTION_SEND,
            "application/octet-stream",
            arrayListOf(SlowShareContentProvider.URI),
        )

        val scenario = ActivityScenario.launch<ShareCaptureActivity>(
            intent.setClass(context, ShareCaptureActivity::class.java),
        )
        scenario.recreate()
        val newIds = awaitNewQueueIds(before, expected = 1, timeoutMs = 20_000)
        val newCachePaths = awaitStableCachedPayloadDelta(cacheBefore, expected = 1)

        assertEquals(newIds, queueIds() - before)
        assertCachedItemsExist(newIds.single())
        assertEquals(1, newCachePaths.size)
        createdQueueIds += newIds
        scenario.close()
    }

    @Test
    fun clipboardBridgeUsesSharedDefaultOnlyCapture() {
        val before = queueIds()
        ScreenClipStore(context).savePendingAutoCapture(
            ScreenClipSnapshot(
                packageName = "com.example.synthetic",
                appLabel = "Synthetic Source",
                title = "Stage 23.8D3A Clipboard Bridge",
                text = "Synthetic screen text",
                url = "",
                capturedAtEpochMs = System.currentTimeMillis(),
            ),
        )
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            context.getSystemService(ClipboardManager::class.java).setPrimaryClip(
                ClipData.newPlainText(
                    "Synthetic link",
                    "https://xhslink.com/o/perclip-stage23-d3a-synthetic",
                ),
            )
        }

        val scenario = ActivityScenario.launch(ClipboardBridgeActivity::class.java)
        val id = awaitNewQueueIds(before, expected = 1).single()
        val queued = requireNotNull(store.find(id))

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, queued.metadata.routingMode)
        assertTrue(queued.url.startsWith("https://xhslink.com/"))
        createdQueueIds += id
        scenario.close()
    }

    @Test
    fun clipboardBridgeFailureSavesExistingScreenSnapshotWithoutPreview() {
        val before = queueIds()
        ScreenClipStore(context).savePendingAutoCapture(
            ScreenClipSnapshot(
                packageName = "com.example.synthetic",
                appLabel = "Synthetic Source",
                title = "Stage 23.8D3B Snapshot Fallback",
                text = "Synthetic fallback screen text",
                url = "",
                capturedAtEpochMs = System.currentTimeMillis(),
            ),
        )
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            context.getSystemService(ClipboardManager::class.java).setPrimaryClip(
                ClipData.newPlainText("Synthetic non-link", "not a share link"),
            )
        }

        val scenario = ActivityScenario.launch(ClipboardBridgeActivity::class.java)
        val id = awaitNewQueueIds(before, expected = 1).single()
        val queued = requireNotNull(store.find(id))

        assertEquals(CaptureRoutingMode.DEFAULT_ONLY, queued.metadata.routingMode)
        assertEquals(ClipKind.ScreenClip, queued.kind)
        assertEquals("", queued.url)
        assertTrue(queued.text.contains("Synthetic fallback screen text"))
        createdQueueIds += id
        scenario.close()
    }


    private fun textIntent(text: String): Intent = Intent(Intent.ACTION_SEND)
        .setType("text/plain")
        .putExtra(Intent.EXTRA_TEXT, text)

    private fun streamIntent(action: String, mimeType: String, uris: ArrayList<Uri>): Intent {
        return Intent(action).setType(mimeType).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION).apply {
            if (action == Intent.ACTION_SEND_MULTIPLE) {
                putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            } else {
                putExtra(Intent.EXTRA_STREAM, uris.single())
            }
        }
    }

    private fun launchShare(intent: Intent) {
        context.startActivity(
            intent.setClass(context, ShareCaptureActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun insertMedia(displayName: String, mimeType: String, bytes: ByteArray): Uri {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/PerClipSynthetic")
        }
        val uri = requireNotNull(
            context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values),
        )
        context.contentResolver.openOutputStream(uri).use { output ->
            requireNotNull(output).write(bytes)
        }
        insertedMedia += uri
        return uri
    }

    private fun assertCachedItemsExist(id: String, expectedItems: Int = 1) {
        val queued = requireNotNull(store.find(id))
        assertEquals(expectedItems, queued.items.size)
        assertTrue(queued.items.all { item -> item.cachedPath.isNotBlank() && File(item.cachedPath).isFile })
    }

    private fun queueIds(): Set<String> = store.all().mapTo(linkedSetOf()) { it.id }

    private fun cachedPayloadPaths(): Set<String> {
        return File(context.cacheDir, "shared_payloads")
            .listFiles()
            .orEmpty()
            .filter(File::isFile)
            .mapTo(linkedSetOf()) { it.absolutePath }
    }

    private fun awaitStableCachedPayloadDelta(
        before: Set<String>,
        expected: Int,
        timeoutMs: Long = 8_000,
    ): Set<String> {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        var stableSince = 0L
        var candidate = emptySet<String>()
        while (SystemClock.elapsedRealtime() < deadline) {
            val current = cachedPayloadPaths() - before
            if (current.size == expected) {
                if (current != candidate) {
                    candidate = current
                    stableSince = SystemClock.elapsedRealtime()
                } else if (SystemClock.elapsedRealtime() - stableSince >= 500) {
                    return current
                }
            } else {
                candidate = emptySet()
                stableSince = 0L
            }
            SystemClock.sleep(50)
        }
        error("Timed out waiting for $expected stable cached payload files")
    }

    private fun awaitNewQueueIds(
        before: Set<String>,
        expected: Int,
        timeoutMs: Long = 8_000,
    ): Set<String> {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val current = queueIds() - before
            if (current.size >= expected) {
                createdQueueIds += current
                SystemClock.sleep(350)
                return current
            }
            SystemClock.sleep(50)
        }
        error("Timed out waiting for $expected new queue records")
    }
}
