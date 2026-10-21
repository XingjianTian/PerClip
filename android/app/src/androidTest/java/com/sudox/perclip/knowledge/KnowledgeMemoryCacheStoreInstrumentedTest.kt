package com.sudox.perclip.knowledge

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.sudox.perclip.ClipKind
import com.sudox.perclip.SharedClip
import com.sudox.perclip.config.PerClipSettings
import com.sudox.perclip.ui.KnowledgeRecordState
import com.sudox.perclip.ui.UploadCompletionToastPolicy
import com.sudox.perclip.ui.screens.KnowledgeCountLabelPolicy
import com.sudox.perclip.ui.screens.KnowledgeEmptyAuthoritativeCount
import com.sudox.perclip.ui.screens.KnowledgeUnifiedListPolicy
import com.sudox.perclip.upload.UploadRecord
import com.sudox.perclip.upload.UploadStatus
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class KnowledgeMemoryCacheStoreInstrumentedTest {
    private lateinit var context: Context
    private lateinit var store: KnowledgeMemoryCacheStore

    @Before fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        context.deleteDatabase("knowledge_local_first_v2.db")
        store = KnowledgeMemoryCacheStore(context)
    }

    @After fun tearDown() { context.deleteDatabase("knowledge_local_first_v2.db") }

    @Test fun pageAppendPersistsCursorItemsAndAuthoritativeCounts() {
        val query = KnowledgeListQuery(listOf("kb-a"))
        store.savePage("config-a", query, page(1, "next", true, 501), append = false)
        store.savePage("config-a", query, page(2, "", false, 501), append = true)
        val snapshot = store.load("config-a", query)
        assertEquals(listOf(id(1), id(2)), snapshot.items.map { it.clip.clipId })
        assertEquals(501, snapshot.summary.totalCount)
        assertEquals(501, snapshot.summary.matchingCount)
        assertTrue(snapshot.complete)
        assertEquals("", snapshot.nextCursor)
        assertTrue(store.load("config-b", query).items.isEmpty())
    }

    @Test fun summaryOnlyStateKeepsAuthoritativeTotalButDoesNotInitializeHead() {
        val query = KnowledgeListQuery()
        store.saveSummary("summary-only", query, KnowledgeListSummary(501, 501, 501, "summary"))
        val summaryOnly = store.load("summary-only", query)
        assertFalse(summaryOnly.initialized)
        assertEquals(501, summaryOnly.summary.totalCount)

        store.savePage(
            "summary-only", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(0, 0, 502, "head"), emptyList(), "", false),
            append = false,
        )
        assertTrue(store.load("summary-only", query).initialized)
        store.saveSummary("summary-only", query, KnowledgeListSummary(0, 0, 503, "later"))
        assertTrue(store.load("summary-only", query).initialized)
    }

    @Test fun failedFirstHeadRetriesFromSuccessfulPageRevisionWithoutBootstrapReplayForLargeLibraries() = runBlocking {
        listOf(501, 20_000).forEach { total ->
            val configuration = "first-retry-$total"
            val query = KnowledgeListQuery()
            var headCalls = 0
            val changeWatermarks = mutableListOf<Long>()
            val snapshotRevision = total.toLong() + 100
            val remote = object : KnowledgeListRemote {
                override fun list(
                    settings: PerClipSettings,
                    query: KnowledgeListQuery,
                    cursor: String,
                    limit: Int,
                ): KnowledgeBaseApiResult<KnowledgeListPage> {
                    assertEquals("", cursor)
                    headCalls += 1
                    if (headCalls == 1) return KnowledgeBaseApiResult.failure("head unavailable")
                    return KnowledgeBaseApiResult.success(KnowledgeListPage(
                        emptyList(),
                        KnowledgeListSummary(total, total, snapshotRevision, "page"),
                        (1..50).map(::item),
                        "cursor-50",
                        true,
                    ))
                }

                override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                    KnowledgeBaseApiResult.success(KnowledgeListSummary(total, total, snapshotRevision, "summary"))

                override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                    changeWatermarks += afterRevision
                    return KnowledgeBaseApiResult.success(
                        KnowledgeChangePage(emptyList(), snapshotRevision, false, snapshotRevision),
                    )
                }
            }
            val repository = KnowledgeRepository(store, remote)
            repository.cached(configuration, query, KnowledgeReadMode.V2_LOCAL_FIRST)
            val failed = repository.synchronize(settings(), configuration, query, KnowledgeReadMode.V2_LOCAL_FIRST)
            assertFalse(failed.snapshot.initialized)
            assertEquals(total, failed.snapshot.summary.totalCount)
            assertEquals(emptyList<Long>(), changeWatermarks)

            val recovered = repository.synchronize(settings(), configuration, query, KnowledgeReadMode.V2_LOCAL_FIRST)
            assertTrue(recovered.snapshot.initialized)
            assertEquals(50, recovered.snapshot.items.size)
            assertEquals(2, headCalls)
            assertEquals(listOf(snapshotRevision), changeWatermarks)
            assertFalse(changeWatermarks.contains(0L))
            assertEquals(snapshotRevision, store.watermark(configuration))
            assertEquals("cursor-50", recovered.snapshot.nextCursor)
        }
    }

    @Test fun schemaFourRebuildsToFiveWithoutTouchingSiblingApplicationDatabase() {
        store.close()
        context.deleteDatabase("knowledge_local_first_v2.db")
        val sibling = context.getDatabasePath("stage23_7b_upload_queue_boundary.db")
        SQLiteDatabase.openOrCreateDatabase(sibling, null).use { db ->
            db.execSQL("create table marker(value text not null)")
            db.execSQL("insert into marker(value) values ('preserved')")
        }
        try {
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("knowledge_local_first_v2.db"), null).use { db ->
                db.execSQL("create table query_state(configuration text not null)")
                db.version = 4
            }
            store = KnowledgeMemoryCacheStore(context)
            store.load("schema-five", KnowledgeListQuery())
            SQLiteDatabase.openDatabase(
                context.getDatabasePath("knowledge_local_first_v2.db").path,
                null,
                SQLiteDatabase.OPEN_READONLY,
            ).use { db ->
                assertEquals(5, db.version)
                val columns = db.rawQuery("pragma table_info(query_state)", null).use { rows ->
                    buildList { while (rows.moveToNext()) add(rows.getString(rows.getColumnIndexOrThrow("name"))) }
                }
                assertTrue("head_initialized" in columns)
            }
            SQLiteDatabase.openDatabase(sibling.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                val marker = db.rawQuery("select value from marker", null).use { rows ->
                    rows.moveToFirst(); rows.getString(0)
                }
                assertEquals("preserved", marker)
            }
        } finally {
            context.deleteDatabase("stage23_7b_upload_queue_boundary.db")
        }
    }

    @Test fun api35RegistryCoordinatorCoversV2LegacyIsolationLastGoodAndAuthoritativeEmpty() = runBlocking {
        var calls = 0
        var fail = false
        val coordinator = KnowledgeTopicRegistryCoordinator {
            calls += 1
            if (fail) KnowledgeBaseApiResult.failure("registry unavailable")
            else KnowledgeBaseApiResult.success(
                if (calls == 1) TopicRegistry(listOf(TopicLabel("work", "工作"))) else TopicRegistry(emptyList()),
            )
        }
        assertTrue(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.V2_LOCAL_FIRST))
        assertTrue(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.LEGACY_QUALITY_READ))
        assertFalse(KnowledgeTopicRegistryPolicy.shouldLoad(true, true, KnowledgeReadMode.LOCAL_ONLY))
        val v2 = coordinator.load(settings("v2"), "registry-v2")
        assertEquals(listOf("work"), v2.registry.topics.map { it.id })
        assertEquals(v2, coordinator.load(settings("v2"), "registry-v2"))
        val legacyEmpty = coordinator.load(settings("legacy"), "registry-legacy")
        assertTrue(legacyEmpty.loaded)
        assertTrue(legacyEmpty.registry.topics.isEmpty())
        fail = true
        val retained = coordinator.load(settings("v2"), "registry-v2", force = true)
        assertEquals(listOf("work"), retained.registry.topics.map { it.id })
        assertEquals("registry unavailable", retained.error)
        assertEquals(3, calls)
    }

    @Test fun changePageIsAtomicAndWatermarkUsesNextRevisionOnly() {
        val query = KnowledgeListQuery()
        store.savePage("config", query, page(1, "", false, 1), append = false)
        store.applyChanges("config", KnowledgeChangePage(
            changes = listOf(KnowledgeChange(8, id(1), "kb-a", emptyList(), "remove", "delete", "", "now", null)),
            nextRevision = 8, hasMore = false, currentRevision = 999,
        ))
        assertTrue(store.load("config", query).items.isEmpty())
        assertEquals(8, store.watermark("config"))
    }

    @Test fun queryLruIsBoundedAndKeysDoNotLeakQueryText() {
        repeat(14) { index ->
            val query = KnowledgeListQuery(text = "private query $index")
            assertFalse(query.key.contains("private"))
            store.savePage("config", query, page(index + 1, "", false, 1), append = false)
            Thread.sleep(2)
        }
        assertEquals(KnowledgeMemoryCacheStore.MAX_QUERIES, store.queryCount("config"))
    }

    @Test fun repositoryTraversesAll501WithOneRequestPerCursorAndDurableResume() = runBlocking {
        val remote = Synthetic501Remote()
        val repository = KnowledgeRepository(store, remote)
        val query = KnowledgeListQuery()
        val settings = PerClipSettings("http://127.0.0.1", "synthetic-test-token", "E2E", false, false)
        repository.cached("config", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        var state = repository.synchronize(settings, "config", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(50, state.snapshot.items.size)
        assertEquals(42, store.watermark("config"))
        assertEquals(1, remote.cursors.count(String::isBlank))
        state = repository.synchronize(settings, "config", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        while (!state.snapshot.complete) {
            state = repository.loadNext(settings, "config", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        }
        assertEquals(501, state.snapshot.items.size)
        assertEquals(501, state.snapshot.items.map { it.clip.clipId }.toSet().size)
        assertEquals(2, remote.cursors.count(String::isBlank))
        assertEquals(10, remote.cursors.filter(String::isNotBlank).toSet().size)
        assertEquals(501, state.snapshot.summary.totalCount)
        assertEquals(42, store.watermark("config"))
        assertTrue(store.load("config", query).complete)
        state = repository.synchronize(settings, "config", query, KnowledgeReadMode.V2_LOCAL_FIRST, forceHead = true)
        assertEquals(501, state.snapshot.items.size)
        assertTrue(state.snapshot.complete)
    }

    @Test fun legacyModeNeverCallsV2Remote() = runBlocking {
        var calls = 0
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
                calls += 1; error("v2 list must not be called")
            }
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery): KnowledgeBaseApiResult<KnowledgeListSummary> {
                calls += 1; error("v2 summary must not be called")
            }
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                calls += 1; error("v2 changes must not be called")
            }
        }
        val repository = KnowledgeRepository(store, remote)
        val settings = PerClipSettings("http://127.0.0.1", "synthetic-test-token", "E2E", false, false)
        repository.cached("legacy", KnowledgeListQuery(), KnowledgeReadMode.LEGACY_QUALITY_READ)
        repository.synchronize(settings, "legacy", KnowledgeListQuery(), KnowledgeReadMode.LEGACY_QUALITY_READ)
        assertEquals(0, calls)
    }

    @Test fun newHeadStaysOutOfViewportUntilBannerIsAccepted() = runBlocking {
        val query = KnowledgeListQuery()
        val initial = KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 2, 2, "now"), listOf(item(2), item(1)), "", false)
        store.savePage("banner", query, initial, append = false)
        val newest = item(3).copy(clip = item(3).clip.copy(capturedAt = "2026-07-29T00:00:00Z"))
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeListPage(emptyList(), KnowledgeListSummary(3, 3, 3, "later"), listOf(newest, item(2), item(1)), "", false))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(3, 3, 3, "later"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeChangePage(
                    listOf(KnowledgeChange(3, newest.clip.clipId, "kb-a", listOf("kb-a"), "upsert", "insert", "", "later", newest)),
                    3, false, 3,
                ))
        }
        val repository = KnowledgeRepository(store, remote)
        val settings = PerClipSettings("http://127.0.0.1", "synthetic-test-token", "E2E", false, false)
        repository.cached("banner", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val waiting = repository.synchronize(settings, "banner", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(1, waiting.newContentCount)
        assertEquals(listOf(id(2), id(1)), waiting.snapshot.items.map { it.clip.clipId })
        val accepted = repository.acceptNewContent("banner", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(listOf(id(3), id(2), id(1)), accepted.snapshot.items.map { it.clip.clipId })
    }

    @Test fun uploadCompletionForceHeadMakesNewMemoryVisibleAndRestartDurable() = runBlocking {
        val query = KnowledgeListQuery()
        store.savePage(
            "upload-completion",
            query,
            KnowledgeListPage(
                emptyList(),
                KnowledgeListSummary(1, 1, 1, "initial"),
                listOf(item(1)),
                "",
                false,
            ),
            append = false,
            initialWatermark = 1,
        )
        val saved = item(2).copy(
            clip = item(2).clip.copy(title = "Stage 27 自动可检索标题", capturedAt = "2026-07-29T00:00:00Z"),
        )
        val shared = item(3).copy(
            clip = item(3).clip.copy(title = "Stage 27 分享自动可检索标题", capturedAt = "2026-07-30T00:00:00Z"),
        )
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(
                    KnowledgeListPage(
                        emptyList(),
                        KnowledgeListSummary(3, 3, 3, "saved"),
                        listOf(shared, saved, item(1)),
                        "",
                        false,
                    ),
                )

            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(3, 3, 3, "saved"))

            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(
                    KnowledgeChangePage(
                        listOf(
                            KnowledgeChange(
                                2,
                                saved.clip.clipId,
                                "kb-a",
                                listOf("kb-a"),
                                "upsert",
                                "association_upsert",
                                "",
                                "saved",
                                saved,
                            ),
                            KnowledgeChange(
                                3,
                                shared.clip.clipId,
                                "kb-a",
                                listOf("kb-a"),
                                "upsert",
                                "association_upsert",
                                "",
                                "saved",
                                shared,
                            ),
                        ),
                        3,
                        false,
                        3,
                    ),
                )
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("upload-completion", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val completionBaseline = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                uploadRecord(id(2), UploadStatus.Waiting),
                uploadRecord(id(3), UploadStatus.Waiting),
            ),
            state = UploadCompletionToastPolicy.State(),
        )
        val completion = UploadCompletionToastPolicy.evaluate(
            records = listOf(
                uploadRecord(id(2), UploadStatus.Uploaded),
                uploadRecord(id(3), UploadStatus.Uploaded),
            ),
            state = completionBaseline.state,
        )
        assertEquals(listOf(id(2), id(3)), completion.newlyUploadedClipIds)
        assertTrue(
            KnowledgeUploadRefreshPolicy.shouldRefresh(
                completionRevision = completion.newlyUploadedClipIds.size,
                handledRevision = 0,
                mode = KnowledgeReadMode.V2_LOCAL_FIRST,
                scope = KnowledgeLibraryScope.All,
            ),
        )

        val refreshed = repository.synchronize(
            settings(),
            "upload-completion",
            query,
            KnowledgeReadMode.V2_LOCAL_FIRST,
            forceHead = true,
        )

        assertEquals(0, refreshed.newContentCount)
        assertEquals(listOf(id(3), id(2), id(1)), refreshed.snapshot.items.map { it.clip.clipId })
        assertEquals("Stage 27 分享自动可检索标题", refreshed.snapshot.items.first().clip.title)
        store.close()
        store = KnowledgeMemoryCacheStore(context)
        val reopened = store.load("upload-completion", query)
        assertEquals(listOf(id(3), id(2), id(1)), reopened.items.map { it.clip.clipId })
    }

    private fun uploadRecord(id: String, status: UploadStatus): UploadRecord = UploadRecord(
        clip = SharedClip(id = id, kind = ClipKind.Text, titleHint = id, text = id, mimeType = "text/plain"),
        status = status,
        message = "",
    )

    @Test fun changeUpsertReordersAndMembershipMoveRemovesOldScope() {
        val global = KnowledgeListQuery()
        val scoped = KnowledgeListQuery(listOf("kb-a"))
        val destination = KnowledgeListQuery(listOf("kb-b"))
        val search = KnowledgeListQuery(text = "server-only body match")
        val old = item(1).copy(clip = item(1).clip.copy(capturedAt = "2026-01-01T00:00:00Z"))
        val newer = item(2).copy(clip = item(2).clip.copy(capturedAt = "2026-01-02T00:00:00Z"))
        val initial = KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 2, 2, "now"), listOf(newer, old), "", false)
        store.savePage("config", global, initial, append = false)
        store.savePage("config", scoped, initial, append = false)
        store.savePage("config", destination, KnowledgeListPage(listOf("kb-b"), KnowledgeListSummary(0, 0, 2, "now"), emptyList(), "", false), append = false)
        store.savePage("config", search, initial, append = false)
        val moved = old.copy(
            clip = old.clip.copy(title = "Updated", capturedAt = "2026-01-03T00:00:00Z"),
            knowledgeBaseIds = listOf("kb-b"), knowledgeBaseId = "kb-b", itemRevision = 9,
        )
        store.applyChanges("config", KnowledgeChangePage(
            listOf(KnowledgeChange(9, moved.clip.clipId, "kb-b", listOf("kb-b"), "upsert", "move", "", "now", moved)),
            9, false, 100,
        ))
        assertEquals(listOf(id(1), id(2)), store.load("config", global).items.map { it.clip.clipId })
        assertEquals("Updated", store.load("config", global).items.first().clip.title)
        assertEquals(listOf(id(2)), store.load("config", scoped).items.map { it.clip.clipId })
        assertEquals(listOf(id(1)), store.load("config", destination).items.map { it.clip.clipId })
        assertTrue(store.isDirty("config", search))
    }

    @Test fun complexQueriesReplaceEntriesWhileBaseRefreshPreservesLoadedTail() {
        val base = KnowledgeListQuery(listOf("kb-a"))
        val old = item(1)
        val tail = item(2).copy(clip = item(2).clip.copy(capturedAt = "2026-07-27T00:00:00Z"))
        store.savePage(
            "replace", base,
            KnowledgeListPage(listOf("kb-a"), KnowledgeListSummary(2, 2, 10, "now"), listOf(old, tail), "old-cursor", true),
            append = false,
        )
        val complexQueries = listOf(
            KnowledgeListQuery(listOf("kb-a"), text = "old title"),
            KnowledgeListQuery(listOf("kb-a"), source = "Old Platform"),
            KnowledgeListQuery(listOf("kb-a"), sourceType = "url"),
            KnowledgeListQuery(listOf("kb-a"), attachment = "with"),
            KnowledgeListQuery(listOf("kb-a"), capturedAfter = "2026-07-01T00:00:00Z"),
            KnowledgeListQuery(listOf("kb-a"), capturedBefore = "2026-08-01T00:00:00Z"),
        )
        complexQueries.forEach { query ->
            store.savePage(
                "replace", query,
                KnowledgeListPage(listOf("kb-a"), KnowledgeListSummary(2, 1, 10, "now"), listOf(old), "complex-old", true),
                append = false,
            )
        }
        val updated = old.copy(clip = old.clip.copy(title = "no longer matches"), itemRevision = 11)
        store.applyChanges(
            "replace",
            KnowledgeChangePage(
                listOf(KnowledgeChange(11, old.clip.clipId, "kb-a", listOf("kb-a"), "upsert", "update", "", "later", updated)),
                11, false, 11,
            ),
        )
        complexQueries.forEach { query ->
            assertTrue(store.isDirty("replace", query))
            store.savePage(
                "replace", query,
                KnowledgeListPage(listOf("kb-a"), KnowledgeListSummary(2, 0, 11, "later"), emptyList(), "", false),
                append = false,
            )
            val snapshot = store.load("replace", query)
            assertTrue(snapshot.items.isEmpty())
            assertEquals("", snapshot.nextCursor)
            assertTrue(snapshot.complete)
            assertFalse(snapshot.dirty)
        }
        store.savePage(
            "replace", base,
            KnowledgeListPage(listOf("kb-a"), KnowledgeListSummary(3, 2, 12, "head"), listOf(item(3), updated), "new-head", true),
            append = false,
        )
        val baseSnapshot = store.load("replace", base)
        assertEquals(listOf(id(3), id(1), id(2)), baseSnapshot.items.map { it.clip.clipId })
        assertEquals("old-cursor", baseSnapshot.nextCursor)
        assertFalse(baseSnapshot.complete)
    }

    @Test fun complexHeadFailurePreservesEntriesCursorAndDirtyState() = runBlocking {
        val query = KnowledgeListQuery(text = "old match")
        store.savePage(
            "dirty", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(3, 1, 5, "old"), listOf(item(1)), "retry-cursor", true),
            append = false,
            initialWatermark = 5,
        )
        store.applyChanges(
            "dirty",
            KnowledgeChangePage(
                listOf(KnowledgeChange(6, id(1), "kb-a", listOf("kb-a"), "upsert", "update", "", "now", item(1))),
                6, false, 6,
            ),
        )
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.failure<KnowledgeListPage>("head failed")
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(3, 0, 6, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), afterRevision, false, afterRevision))
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("dirty", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val state = repository.synchronize(settings(), "dirty", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertTrue(state.partialSyncFailure)
        assertFalse(state.offline)
        assertEquals(listOf(id(1)), state.snapshot.items.map { it.clip.clipId })
        assertEquals("retry-cursor", state.snapshot.nextCursor)
        assertTrue(state.snapshot.dirty)
        assertTrue(state.syncError.contains("head failed"))
    }

    @Test fun changesFailureCannotBeHiddenBySuccessfulHeadAndRecoveryReplaysTailDelete() = runBlocking {
        val query = KnowledgeListQuery()
        val allItems = (1..150).map(::item)
        store.savePage(
            "partial", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(150, 150, 42, "initial"), allItems.take(50), "50", true),
            append = false,
            initialWatermark = 42,
        )
        store.savePage(
            "partial", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(150, 150, 42, "initial"), allItems.drop(50).take(50), "100", true),
            append = true,
        )
        store.savePage(
            "partial", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(150, 150, 42, "initial"), allItems.drop(100), "", false),
            append = true,
        )
        var changesFail = true
        val revisions = mutableListOf<Long>()
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeListPage(emptyList(), KnowledgeListSummary(149, 149, 43, "head"), allItems.take(50), "50", true))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(149, 149, 43, "head"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                revisions += afterRevision
                if (changesFail) return KnowledgeBaseApiResult.failure("changes unavailable")
                return KnowledgeBaseApiResult.success(
                    KnowledgeChangePage(
                        listOf(KnowledgeChange(43, id(150), "kb-a", emptyList(), "remove", "delete", "", "later", null)),
                        43, false, 43,
                    ),
                )
            }
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("partial", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        var state = repository.synchronize(settings(), "partial", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertTrue(state.partialSyncFailure)
        assertFalse(state.offline)
        assertEquals(150, state.snapshot.items.size)
        assertEquals(42, store.watermark("partial"))
        assertTrue(state.syncError.contains("changes unavailable"))
        changesFail = false
        state = repository.synchronize(settings(), "partial", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertFalse(state.partialSyncFailure)
        assertEquals(149, state.snapshot.items.size)
        assertFalse(state.snapshot.items.any { it.clip.clipId == id(150) })
        assertEquals(149, state.snapshot.items.map { it.clip.clipId }.toSet().size)
        assertEquals(43, store.watermark("partial"))
        assertEquals(listOf(42L, 42L), revisions)
    }

    @Test fun firstSyncRequestsHeadOnceAndChasesCurrentRevisionWithoutLosingConcurrentEvent() = runBlocking {
        val query = KnowledgeListQuery()
        val cursors = mutableListOf<String>()
        val revisions = mutableListOf<Long>()
        var summaryCalls = 0
        val concurrent = item(2).copy(clip = item(2).clip.copy(title = "Concurrent"), itemRevision = 44)
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
                cursors += cursor
                return KnowledgeBaseApiResult.success(
                    KnowledgeListPage(emptyList(), KnowledgeListSummary(1, 1, 42, "snapshot"), listOf(item(1)), "next-page", true),
                )
            }
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery): KnowledgeBaseApiResult<KnowledgeListSummary> {
                summaryCalls += 1
                return KnowledgeBaseApiResult.success(KnowledgeListSummary(1, 1, 42, "snapshot"))
            }
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                revisions += afterRevision
                return if (afterRevision == 42L) {
                    KnowledgeBaseApiResult.success(
                        KnowledgeChangePage(
                            listOf(KnowledgeChange(43, concurrent.clip.clipId, "kb-a", listOf("kb-a"), "upsert", "insert", "", "now", concurrent)),
                            43, false, 44,
                        ),
                    )
                } else {
                    KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), 44, false, 44))
                }
            }
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("first", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val state = repository.synchronize(settings(), "first", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(1, summaryCalls)
        assertEquals(listOf(""), cursors)
        assertEquals(listOf(42L, 43L), revisions)
        assertEquals(44, store.watermark("first"))
        assertEquals(setOf(id(1), id(2)), state.snapshot.items.map { it.clip.clipId }.toSet())
        assertEquals("next-page", state.snapshot.nextCursor)
    }

    @Test fun noProgressChangeServiceFailsClosedWithoutPersistingCurrentRevision() = runBlocking {
        val query = KnowledgeListQuery()
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeListPage(emptyList(), KnowledgeListSummary(1, 1, 42, "snapshot"), listOf(item(1)), "", false))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(1, 1, 42, "snapshot"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), 42, false, 999))
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("no-progress", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val state = repository.synchronize(settings(), "no-progress", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertTrue(state.partialSyncFailure)
        assertTrue(state.syncError.contains("水位未推进"))
        assertEquals(42, store.watermark("no-progress"))
    }

    @Test fun changeFailureResumesFromLastSuccessfulNextRevision() = runBlocking {
        val query = KnowledgeListQuery()
        var failAt43 = true
        val revisions = mutableListOf<Long>()
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeListPage(emptyList(), KnowledgeListSummary(1, 1, 42, "snapshot"), listOf(item(1)), "", false))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(1, 1, 44, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                revisions += afterRevision
                if (afterRevision == 43L && failAt43) return KnowledgeBaseApiResult.failure("middle failure")
                return if (afterRevision == 42L) {
                    KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), 43, false, 44))
                } else {
                    KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), 44, false, 44))
                }
            }
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("resume", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        var state = repository.synchronize(settings(), "resume", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertTrue(state.partialSyncFailure)
        assertEquals(43, store.watermark("resume"))
        failAt43 = false
        state = repository.synchronize(settings(), "resume", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertFalse(state.partialSyncFailure)
        assertEquals(44, store.watermark("resume"))
        assertEquals(listOf(42L, 43L, 43L), revisions)
    }

    @Test fun pendingHeadsAreQueryIsolatedAndStaleGenerationCannotPolluteCurrentBanner() = runBlocking {
        val queryA = KnowledgeListQuery(knowledgeBaseIds = listOf("kb-A"))
        val queryB = KnowledgeListQuery(knowledgeBaseIds = listOf("kb-B"))
        store.savePage("pending", queryA, singlePage(item(1)), append = false, initialWatermark = 1)
        store.savePage("pending", queryB, singlePage(item(2)), append = false)
        val aStarted = CountDownLatch(1)
        val releaseA = CountDownLatch(1)
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
                if (query.knowledgeBaseIds == listOf("kb-A")) {
                    aStarted.countDown()
                    check(releaseA.await(10, TimeUnit.SECONDS))
                }
                val old = if (query.knowledgeBaseIds == listOf("kb-A")) item(1) else item(2)
                val newest = if (query.knowledgeBaseIds == listOf("kb-A")) item(11) else item(22)
                return KnowledgeBaseApiResult.success(
                    KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 2, 2, "now"), listOf(newest, old), "", false),
                )
            }
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(2, 2, 2, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), afterRevision, false, afterRevision))
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("pending", queryA, KnowledgeReadMode.V2_LOCAL_FIRST)
        val delayedA = async(Dispatchers.IO) {
            repository.synchronize(settings(), "pending", queryA, KnowledgeReadMode.V2_LOCAL_FIRST)
        }
        assertTrue(aStarted.await(10, TimeUnit.SECONDS))
        repository.cached("pending", queryB, KnowledgeReadMode.V2_LOCAL_FIRST)
        val stateB = repository.synchronize(settings(), "pending", queryB, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(1, stateB.newContentCount)
        releaseA.countDown()
        delayedA.await()
        val acceptedB = repository.acceptNewContent("pending", queryB, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(listOf(id(22), id(2)), acceptedB.snapshot.items.map { it.clip.clipId })
        val acceptedAWithoutPending = repository.acceptNewContent("pending", queryA, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(listOf(id(1)), acceptedAWithoutPending.snapshot.items.map { it.clip.clipId })
        assertEquals(0, repository.pendingCount())
    }

    @Test fun pendingHeadsAreConfigurationIsolatedAndBoundedAcrossQuerySwitches() = runBlocking {
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
                val seed = settings.deviceName.removePrefix("device-").toIntOrNull()
                    ?: if (settings.deviceName == "A") 101 else 202
                return KnowledgeBaseApiResult.success(
                    KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 2, 2, "now"), listOf(item(seed), item(1)), "", false),
                )
            }
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(2, 2, 2, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), afterRevision, false, afterRevision))
        }
        val repository = KnowledgeRepository(store, remote)
        val shared = KnowledgeListQuery(knowledgeBaseIds = listOf("kb-shared"))
        store.savePage("config-a", shared, singlePage(item(1)), append = false, initialWatermark = 1)
        store.savePage("config-b", shared, singlePage(item(1)), append = false, initialWatermark = 1)
        repository.cached("config-a", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        repository.synchronize(settings("A"), "config-a", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        repository.cached("config-b", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        repository.synchronize(settings("B"), "config-b", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        val acceptedB = repository.acceptNewContent("config-b", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(id(202), acceptedB.snapshot.items.first().clip.clipId)
        val acceptedA = repository.acceptNewContent("config-a", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(id(101), acceptedA.snapshot.items.first().clip.clipId)

        repeat(14) { index ->
            val configuration = "bounded-$index"
            store.savePage(configuration, shared, singlePage(item(1)), append = false, initialWatermark = 1)
            repository.cached(configuration, shared, KnowledgeReadMode.V2_LOCAL_FIRST)
            repository.synchronize(settings("device-${index + 300}"), configuration, shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        }
        assertTrue(repository.pendingCount() <= KnowledgeRepository.MAX_PENDING_HEADS)
        repository.acceptNewContent("bounded-13", shared, KnowledgeReadMode.V2_LOCAL_FIRST)
        Unit
    }

    @Test fun scopeTotalFallbackIsStrictAcrossKnowledgeBaseScopesAndConfigurations() {
        val all = KnowledgeListQuery()
        val kbA = KnowledgeListQuery(listOf("kb-a"))
        store.saveSummary("scope", all, KnowledgeListSummary(501, 501, 10, "now"))
        store.saveSummary("scope", kbA, KnowledgeListSummary(65, 65, 10, "now"))
        val searchAll = KnowledgeListQuery(text = "deep")
        val searchA = KnowledgeListQuery(listOf("kb-a"), text = "deep")
        val searchB = KnowledgeListQuery(listOf("kb-b"), text = "deep")
        assertEquals(501, store.load("scope", searchAll).summary.totalCount)
        assertEquals(65, store.load("scope", searchA).summary.totalCount)
        assertEquals(null, store.load("scope", searchB).summary.totalCount)
        assertEquals(null, store.load("other", searchAll).summary.totalCount)
        store.saveSummary("scope", searchA, KnowledgeListSummary(66, 1, 11, "later"))
        assertEquals(66, store.loadScopeTotal("scope", listOf("kb-a")))
        assertEquals(501, store.loadScopeTotal("scope", emptyList()))
    }

    @Test fun topicCorrectionChangeImmediatelyUpdatesV2CacheAndAdvancesNextRevision() = runBlocking {
        val query = KnowledgeListQuery()
        val original = item(1)
        store.savePage("topic", query, singlePage(original, revision = 10), append = false, initialWatermark = 10)
        val correctedAssignment = ClipTopicAssignment(
            primary = TopicLabel("corrected", "已修正"),
            unclassified = false,
            manualOverride = true,
        )
        val corrected = original.copy(
            clip = original.clip.copy(topicAssignment = correctedAssignment),
            itemRevision = 11,
        )
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(singlePage(corrected, revision = 11))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(1, 1, 11, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.success(
                    KnowledgeChangePage(
                        listOf(KnowledgeChange(11, id(1), "kb-a", listOf("kb-a"), "upsert", "topic_correction", "", "now", corrected)),
                        11, false, 11,
                    ),
                )
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("topic", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        val state = repository.synchronize(settings(), "topic", query, KnowledgeReadMode.V2_LOCAL_FIRST, forceHead = true)
        assertEquals("corrected", state.snapshot.items.single().clip.topicAssignment.primary.id)
        assertEquals("已修正", state.snapshot.items.single().clip.topicAssignment.primary.displayName)
        assertEquals(11, store.watermark("topic"))
        assertFalse(state.partialSyncFailure)

        store.close()
        store = KnowledgeMemoryCacheStore(context)
        val reopened = store.load("topic", query)
        assertEquals("corrected", reopened.items.single().clip.topicAssignment.primary.id)
        assertEquals("已修正", reopened.items.single().clip.topicAssignment.primary.displayName)
        assertEquals(11, store.watermark("topic"))
    }

    @Test fun configurationWideChangeMutexSerializesDifferentQueries() = runBlocking {
        val queryA = KnowledgeListQuery(text = "A")
        val queryB = KnowledgeListQuery(text = "B")
        store.savePage("mutex", queryA, singlePage(item(1)), append = false, initialWatermark = 1)
        store.savePage("mutex", queryB, singlePage(item(2)), append = false)
        val active = AtomicInteger(0)
        val maximum = AtomicInteger(0)
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int) =
                KnowledgeBaseApiResult.success(singlePage(if (query.text == "A") item(1) else item(2)))
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.success(KnowledgeListSummary(2, 1, 1, "now"))
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int): KnowledgeBaseApiResult<KnowledgeChangePage> {
                val now = active.incrementAndGet()
                maximum.updateAndGet { previous -> maxOf(previous, now) }
                Thread.sleep(80)
                active.decrementAndGet()
                return KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), afterRevision, false, afterRevision))
            }
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("mutex", queryA, KnowledgeReadMode.V2_LOCAL_FIRST)
        val first = async(Dispatchers.IO) { repository.synchronize(settings(), "mutex", queryA, KnowledgeReadMode.V2_LOCAL_FIRST) }
        val second = async(Dispatchers.IO) { repository.synchronize(settings(), "mutex", queryB, KnowledgeReadMode.V2_LOCAL_FIRST) }
        first.await()
        second.await()
        assertEquals(1, maximum.get())
    }

    @Test fun failedCursorCanRetryButSuccessfulCursorIsNeverRequestedAgain() = runBlocking {
        val query = KnowledgeListQuery()
        store.savePage(
            "cursor-retry", query,
            KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 1, 1, "now"), listOf(item(1)), "cursor-1", true),
            append = false,
        )
        var fail = true
        val cursors = mutableListOf<String>()
        val remote = object : KnowledgeListRemote {
            override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
                cursors += cursor
                if (fail) return KnowledgeBaseApiResult.failure("page unavailable")
                return KnowledgeBaseApiResult.success(
                    KnowledgeListPage(emptyList(), KnowledgeListSummary(2, 2, 2, "later"), listOf(item(2)), "", false),
                )
            }
            override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
                KnowledgeBaseApiResult.failure<KnowledgeListSummary>("unused")
            override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
                KnowledgeBaseApiResult.failure<KnowledgeChangePage>("unused")
        }
        val repository = KnowledgeRepository(store, remote)
        repository.cached("cursor-retry", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        var state = repository.loadNext(settings(), "cursor-retry", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals("cursor-1", state.snapshot.nextCursor)
        assertEquals(1, state.snapshot.items.size)
        assertTrue(state.pageLoadFailure)
        fail = false
        state = repository.loadNext(settings(), "cursor-retry", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals("", state.snapshot.nextCursor)
        assertEquals(2, state.snapshot.items.size)
        assertFalse(state.pageLoadFailure)
        repository.loadNext(settings(), "cursor-retry", query, KnowledgeReadMode.V2_LOCAL_FIRST)
        assertEquals(listOf("cursor-1", "cursor-1"), cursors)
    }

    @Test fun offlineUnknownAndPartialStatesCannotRenderAuthoritativeEmptyOnApi35() {
        assertFalse(KnowledgeEmptyStatePolicy.shouldShow(
            cacheReadComplete = true,
            loading = false,
            offline = true,
            partialSyncFailure = false,
            authoritativeCount = null,
            remoteItemCount = 0,
            pendingCount = 0,
            failedCount = 0,
            unconfirmedUploadedCount = 0,
            dirty = false,
        ))
        assertFalse(KnowledgeEmptyStatePolicy.shouldShow(
            cacheReadComplete = true,
            loading = false,
            offline = false,
            partialSyncFailure = true,
            authoritativeCount = 0,
            remoteItemCount = 0,
            pendingCount = 0,
            failedCount = 0,
            unconfirmedUploadedCount = 0,
            dirty = false,
        ))
        assertTrue(KnowledgeEmptyStatePolicy.shouldShow(
            cacheReadComplete = true,
            loading = false,
            offline = false,
            partialSyncFailure = false,
            authoritativeCount = 0,
            remoteItemCount = 0,
            pendingCount = 0,
            failedCount = 0,
            unconfirmedUploadedCount = 0,
            dirty = false,
        ))
        assertEquals(0, KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Pending, 501))
        assertEquals(0, KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Failed, 501))
        assertTrue(KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, false,
            KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Pending, 501),
            0, 0, 0, 0, false,
        ))
        assertTrue(KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, false,
            KnowledgeEmptyAuthoritativeCount.forStatus(KnowledgeRecordState.Failed, 501),
            0, 0, 0, 0, false,
        ))
        assertFalse(KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, false, 0, 0, 1, 0, 0, false,
        ))
        assertFalse(KnowledgeEmptyStatePolicy.shouldShow(
            true, false, false, false, 0, 0, 0, 1, 0, false,
        ))
    }

    @Test fun legacyAndLocalCountsNeverMasqueradeAsAuthoritativeOnApi35() {
        assertEquals(null, KnowledgeCountLabelPolicy.cloudTotal(KnowledgeReadMode.LEGACY_QUALITY_READ, 12))
        assertEquals("已加载 12 条", KnowledgeCountLabelPolicy.listLabel(
            KnowledgeReadMode.LEGACY_QUALITY_READ, null, null, 12,
        ))
        assertEquals(null, KnowledgeCountLabelPolicy.cloudTotal(KnowledgeReadMode.LOCAL_ONLY, 4))
        assertEquals("本机 4 条", KnowledgeCountLabelPolicy.listLabel(
            KnowledgeReadMode.LOCAL_ONLY, null, null, 4,
        ))
        assertEquals("读取中", KnowledgeCountLabelPolicy.listLabel(
            KnowledgeReadMode.V2_LOCAL_FIRST, null, null, 0,
        ))
    }

    @Test fun uploadedUnconfirmedCountMatchesVisibleTransitionAndDisappearsOnConfirmationOnApi35() {
        assertEquals(102, KnowledgeUnifiedListPolicy.statusCount(
            status = null,
            remoteMatchingCount = 100,
            pendingCount = 1,
            failedCount = 0,
            unconfirmedUploadedCount = 1,
        ))
        assertEquals(101, KnowledgeUnifiedListPolicy.statusCount(
            status = KnowledgeRecordState.Ingested,
            remoteMatchingCount = 100,
            pendingCount = 0,
            failedCount = 0,
            unconfirmedUploadedCount = 1,
        ))
        assertEquals(100, KnowledgeUnifiedListPolicy.statusCount(
            status = KnowledgeRecordState.Ingested,
            remoteMatchingCount = 100,
            pendingCount = 0,
            failedCount = 0,
            unconfirmedUploadedCount = 0,
        ))
    }

    @Test fun corruptDatabaseAndOldSchemaRebuildWithoutTouchingOtherAppData() {
        store.close()
        context.getDatabasePath("knowledge_local_first_v2.db").writeText("not sqlite")
        store = KnowledgeMemoryCacheStore(context)
        assertTrue(store.load("config", KnowledgeListQuery()).items.isEmpty())
        store.close()
        context.deleteDatabase("knowledge_local_first_v2.db")
        SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("knowledge_local_first_v2.db"), null).use { db ->
            db.execSQL("create table obsolete(value text)")
            db.version = 1
        }
        store = KnowledgeMemoryCacheStore(context)
        store.savePage("config", KnowledgeListQuery(), page(1, "", false, 1), append = false)
        assertEquals(1, store.load("config", KnowledgeListQuery()).items.size)
    }

    @Test fun conditionalAvdPerformanceObservations() {
        val query = KnowledgeListQuery()
        val pages = (0 until 11).map { pageIndex ->
            val start = pageIndex * 50
            val end = minOf(start + 50, 501)
            KnowledgeListPage(emptyList(), KnowledgeListSummary(501, 501, 42, "now"),
                (start until end).map { item(it + 1) }, if (end < 501) end.toString() else "", end < 501)
        }
        val firstPageStart = SystemClock.elapsedRealtimeNanos()
        store.savePage("perf", query, pages.first(), append = false)
        val firstPageWriteMs = elapsedMs(firstPageStart)
        val read50Start = SystemClock.elapsedRealtimeNanos()
        assertEquals(50, store.load("perf", query).items.size)
        val read50Ms = elapsedMs(read50Start)
        val nextPageStart = SystemClock.elapsedRealtimeNanos()
        store.savePage("perf", query, pages[1], append = true)
        val nextPageMs = elapsedMs(nextPageStart)
        val writeStart = SystemClock.elapsedRealtimeNanos()
        pages.drop(2).forEach { page -> store.savePage("perf", query, page, append = true) }
        val writeMs = elapsedMs(writeStart)
        val readStart = SystemClock.elapsedRealtimeNanos()
        assertEquals(501, store.load("perf", query).items.size)
        val read501Ms = elapsedMs(readStart)
        store.close()
        store = KnowledgeMemoryCacheStore(context)
        val coldCacheStart = SystemClock.elapsedRealtimeNanos()
        assertEquals(501, store.load("perf", query).items.size)
        val coldCacheReadMs = elapsedMs(coldCacheStart)
        val searchStart = SystemClock.elapsedRealtimeNanos()
        val searchQuery = KnowledgeListQuery(text = "deep marker")
        store.savePage("perf", searchQuery, page(1, "", false, 1), append = false)
        assertEquals(1, store.load("perf", searchQuery).items.size)
        val searchSwitchMs = elapsedMs(searchStart)
        val changes = (1..100).map { index ->
            val value = item(index).copy(clip = item(index).clip.copy(title = "Changed $index"), itemRevision = 1000L + index)
            KnowledgeChange(1000L + index, value.clip.clipId, "kb-a", listOf("kb-a"), "upsert", "update", "", "now", value)
        }
        val changeStart = SystemClock.elapsedRealtimeNanos()
        store.applyChanges("perf", KnowledgeChangePage(changes, 1100, false, 9999))
        val changesMs = elapsedMs(changeStart)
        Log.i(
            "PERCLIP_STAGE237B",
            "conditional_avd first_page_write_ms=$firstPageWriteMs read_50_ms=$read50Ms next_page_tx_ms=$nextPageMs " +
                "remaining_401_write_ms=$writeMs read_501_ms=$read501Ms cold_reopen_read_501_ms=$coldCacheReadMs " +
                "search_switch_ms=$searchSwitchMs apply_100_changes_ms=$changesMs",
        )
    }

    private fun page(index: Int, cursor: String, more: Boolean, total: Int) = KnowledgeListPage(
        listOf("kb-a"), KnowledgeListSummary(total, total, index.toLong(), "now"),
        listOf(item(index)), cursor, more,
    )

    private fun singlePage(value: KnowledgeListItem, revision: Long = value.itemRevision) = KnowledgeListPage(
        listOf("kb-a"), KnowledgeListSummary(1, 1, revision, "now"), listOf(value), "", false,
    )

    private fun settings(serviceName: String = "E2E") =
        PerClipSettings("http://127.0.0.1", "synthetic-test-token", serviceName, false, false)

    private fun item(index: Int) = KnowledgeListItem(
        KnowledgeTopicClip(id(index), "Title $index", capturedAt = "2026-07-28T00:00:00Z"),
        listOf("kb-a"), "kb-a", "A", itemRevision = index.toLong(), correlationIdentity = "request-$index",
    )

    private fun id(index: Int) = "pc_${index.toString(16).padStart(32, '0')}"
    private fun elapsedMs(start: Long) = (SystemClock.elapsedRealtimeNanos() - start) / 1_000_000.0

    private inner class Synthetic501Remote : KnowledgeListRemote {
        val cursors = mutableListOf<String>()

        override fun list(settings: PerClipSettings, query: KnowledgeListQuery, cursor: String, limit: Int): KnowledgeBaseApiResult<KnowledgeListPage> {
            check(limit == 50)
            check(cursor.isBlank() || cursor !in cursors) { "duplicate cursor request: $cursor" }
            cursors += cursor
            val offset = cursor.ifBlank { "0" }.toInt()
            val end = minOf(offset + limit, 501)
            val items = (offset until end).map { item(it + 1) }
            val next = if (end < 501) end.toString() else ""
            return KnowledgeBaseApiResult.success(
                KnowledgeListPage(emptyList(), KnowledgeListSummary(501, 501, 42, "now"), items, next, next.isNotBlank()),
            )
        }

        override fun summary(settings: PerClipSettings, query: KnowledgeListQuery) =
            KnowledgeBaseApiResult.success(KnowledgeListSummary(501, 501, 42, "now"))

        override fun changes(settings: PerClipSettings, afterRevision: Long, limit: Int) =
            KnowledgeBaseApiResult.success(KnowledgeChangePage(emptyList(), 42, false, 42))
    }
}
