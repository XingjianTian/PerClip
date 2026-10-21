package com.sudox.perclip.knowledge

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject

/** Independent, configuration-isolated remote Knowledge cache. */
class KnowledgeMemoryCacheStore(private val context: Context) {
    @Volatile private var helper = CacheDb(context.applicationContext)

    fun load(configuration: String, query: KnowledgeListQuery): KnowledgeCacheSnapshot = guarded {
        val normalized = query.normalized()
        val key = normalized.key
        val db = helper.writableDatabase
        val state = db.query(
            "query_state", null, "configuration=? and query_key=?", arrayOf(configuration, key),
            null, null, null,
        ).use { cursor -> if (cursor.moveToFirst()) cursor.toState() else null }
        touch(db, configuration, key)
        KnowledgeCacheSnapshot(
            queryKey = key,
            initialized = state?.headInitialized == true,
            items = readItems(db, configuration, key),
            summary = (state?.summary ?: KnowledgeListSummary()).let { summary ->
                if (summary.totalCount != null) summary else summary.copy(
                    totalCount = loadScopeTotal(db, configuration, normalized.knowledgeBaseIds),
                )
            },
            nextCursor = state?.cursor.orEmpty(),
            complete = state?.complete ?: false,
            lastSuccessAt = state?.lastSuccess.orEmpty(),
            lastError = state?.error.orEmpty(),
            dirty = state?.dirty ?: false,
        )
    }

    fun savePage(
        configuration: String,
        query: KnowledgeListQuery,
        page: KnowledgeListPage,
        append: Boolean,
        initialWatermark: Long? = null,
    ) = guardedWrite { db ->
        val normalized = query.normalized()
        val key = normalized.key
        val previous = loadState(db, configuration, key)
        val existingIds = if (!append) readEntryIds(db, configuration, key) else emptyList()
        val headIds = page.items.mapTo(hashSetOf()) { it.clip.clipId }
        val retainedIds = existingIds.filterNot { it in headIds }
        val preservingTail = !append && normalized.baseQuery && existingIds.isNotEmpty()
        upsertState(db, stateValues(
            configuration, normalized, page.summary,
            cursor = if (preservingTail) previous?.cursor.orEmpty() else page.nextCursor,
            complete = if (preservingTail) previous?.complete ?: false else !page.hasMore,
            error = "",
            dirty = false,
            headInitialized = true,
        ))
        if (!append) db.delete("query_entries", "configuration=? and query_key=?", arrayOf(configuration, key))
        val start = if (append) entryCount(db, configuration, key) else 0
        page.items.forEachIndexed { index, item ->
            upsertItem(db, configuration, item)
            db.insertWithOnConflict("query_entries", null, ContentValues().apply {
                put("configuration", configuration); put("query_key", key)
                put("public_clip_id", item.clip.clipId); put("position", start + index)
            }, SQLiteDatabase.CONFLICT_REPLACE)
        }
        if (preservingTail) {
            retainedIds.forEachIndexed { index, id ->
                db.insertWithOnConflict("query_entries", null, ContentValues().apply {
                    put("configuration", configuration); put("query_key", key)
                    put("public_clip_id", id); put("position", page.items.size + index)
                }, SQLiteDatabase.CONFLICT_REPLACE)
            }
        }
        initialWatermark?.let { revision ->
            db.insertWithOnConflict("sync_state", null, ContentValues().apply {
                put("configuration", configuration)
                put("next_revision", revision)
                put("last_success", page.summary.generatedAt)
                put("last_error", "")
            }, SQLiteDatabase.CONFLICT_IGNORE)
        }
        pruneQueries(db, configuration)
    }

    fun saveSummary(configuration: String, query: KnowledgeListQuery, summary: KnowledgeListSummary) = guardedWrite { db ->
        val current = loadState(db, configuration, query.key)
        upsertState(db, stateValues(
            configuration, query.normalized(), summary, current?.cursor.orEmpty(),
            current?.complete ?: false, "", current?.dirty ?: false,
            current?.headInitialized ?: false,
        ))
        pruneQueries(db, configuration)
    }

    fun saveError(configuration: String, queryKey: String, error: String) = guardedWrite { db ->
        db.execSQL(
            "update query_state set last_error=? where configuration=? and query_key=?",
            arrayOf(error.take(240), configuration, queryKey),
        )
    }

    fun saveSyncError(configuration: String, error: String) = guardedWrite { db ->
        val watermark = db.rawQuery(
            "select next_revision from sync_state where configuration=?", arrayOf(configuration),
        ).use { if (it.moveToFirst()) it.getLong(0) else 0L }
        db.insertWithOnConflict("sync_state", null, ContentValues().apply {
            put("configuration", configuration)
            put("next_revision", watermark)
            put("last_success", "")
            put("last_error", error.take(240))
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    /** Applies a complete changes page and advances only to next_revision in one transaction. */
    fun applyChanges(configuration: String, page: KnowledgeChangePage) = guardedWrite { db ->
        page.changes.forEach { change ->
            if (change.operation == "remove" || change.item == null) {
                db.delete("items", "configuration=? and public_clip_id=?", arrayOf(configuration, change.publicClipId))
                db.delete("query_entries", "configuration=? and public_clip_id=?", arrayOf(configuration, change.publicClipId))
            } else {
                upsertItem(db, configuration, change.item)
                updateQueryMemberships(db, configuration, change.item)
            }
        }
        reorderEntries(db, configuration)
        db.insertWithOnConflict("sync_state", null, ContentValues().apply {
            put("configuration", configuration)
            put("next_revision", page.nextRevision)
            put("last_success", page.changes.lastOrNull()?.changedAt.orEmpty())
            put("last_error", "")
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun watermark(configuration: String): Long = guarded {
        helper.readableDatabase.rawQuery(
            "select next_revision from sync_state where configuration=?", arrayOf(configuration),
        ).use { if (it.moveToFirst()) it.getLong(0) else 0L }
    }

    fun syncError(configuration: String): String = guarded {
        helper.readableDatabase.rawQuery(
            "select last_error from sync_state where configuration=?", arrayOf(configuration),
        ).use { if (it.moveToFirst()) it.getString(0).orEmpty() else "" }
    }

    fun loadScopeTotal(configuration: String, knowledgeBaseIds: List<String>): Int? = guarded {
        loadScopeTotal(helper.readableDatabase, configuration, knowledgeBaseIds)
    }

    fun queryCount(configuration: String): Int = guarded {
        helper.readableDatabase.rawQuery(
            "select count(*) from query_state where configuration=?", arrayOf(configuration),
        ).use { if (it.moveToFirst()) it.getInt(0) else 0 }
    }

    fun isDirty(configuration: String, query: KnowledgeListQuery): Boolean = guarded {
        helper.readableDatabase.rawQuery(
            "select dirty from query_state where configuration=? and query_key=?",
            arrayOf(configuration, query.key),
        ).use { it.moveToFirst() && it.getInt(0) != 0 }
    }

    fun hasCache(configuration: String): Boolean = guarded {
        helper.readableDatabase.rawQuery(
            "select exists(select 1 from query_state where configuration=? and total_count is not null)",
            arrayOf(configuration),
        ).use { it.moveToFirst() && it.getInt(0) == 1 }
    }

    fun close() = helper.close()

    private fun readItems(db: SQLiteDatabase, configuration: String, queryKey: String): List<KnowledgeListItem> =
        db.rawQuery(
            """select i.* from query_entries e join items i
               on i.configuration=e.configuration and i.public_clip_id=e.public_clip_id
               where e.configuration=? and e.query_key=? order by e.position""",
            arrayOf(configuration, queryKey),
        ).use { rows -> buildList { while (rows.moveToNext()) add(rows.toItem()) } }

    private fun upsertItem(db: SQLiteDatabase, configuration: String, item: KnowledgeListItem) {
        val values = ContentValues().apply {
            put("configuration", configuration); put("public_clip_id", item.clip.clipId)
            put("knowledge_base_ids", JSONArray(item.knowledgeBaseIds).toString())
            put("knowledge_base_id", item.knowledgeBaseId); put("knowledge_base_name", item.knowledgeBaseName)
            put("title", item.clip.title); put("summary", item.clip.summary); put("source", item.clip.source)
            put("source_type", item.sourceType); put("captured_at", item.clip.capturedAt)
            put("safe_display_url", item.clip.safeDisplayUrl); put("has_attachment", item.hasAttachment.toInt())
            put("topic_assignment", assignmentJson(item.clip.topicAssignment).toString())
            put("item_revision", item.itemRevision); put("updated_at", item.updatedAt)
            put("correlation_identity", item.correlationIdentity)
        }
        val updated = db.update(
            "items", values, "configuration=? and public_clip_id=?",
            arrayOf(configuration, item.clip.clipId),
        )
        if (updated == 0) db.insertOrThrow("items", null, values)
    }

    private fun stateValues(
        configuration: String,
        query: KnowledgeListQuery,
        summary: KnowledgeListSummary,
        cursor: String,
        complete: Boolean,
        error: String,
        dirty: Boolean,
        headInitialized: Boolean,
    ) = ContentValues().apply {
        put("configuration", configuration); put("query_key", query.key)
        put("query_json", queryJson(query).toString()); put("total_count", summary.totalCount)
        put("matching_count", summary.matchingCount); put("revision", summary.revision)
        put("generated_at", summary.generatedAt); put("next_cursor", cursor)
        put("complete", complete.toInt()); put("last_success", summary.generatedAt)
        put("last_error", error); put("last_access", System.currentTimeMillis())
        put("dirty", dirty.toInt()); put("pinned", query.baseQuery.toInt())
        put("head_initialized", headInitialized.toInt())
    }

    private fun loadScopeTotal(
        db: SQLiteDatabase,
        configuration: String,
        knowledgeBaseIds: List<String>,
    ): Int? {
        val normalizedScope = knowledgeBaseIds.map(String::trim).filter(String::isNotBlank).distinct().sorted()
        return db.rawQuery(
            "select query_json,total_count from query_state where configuration=? and total_count is not null order by last_access desc",
            arrayOf(configuration),
        ).use { rows ->
            while (rows.moveToNext()) {
                val query = runCatching { JSONObject(rows.getString(0)) }.getOrNull() ?: continue
                val scope = query.optJSONArray("knowledge_base_ids")?.toString()?.let(::jsonStrings).orEmpty()
                if (scope == normalizedScope) return@use rows.getInt(1)
            }
            null
        }
    }

    private fun upsertState(db: SQLiteDatabase, values: ContentValues) {
        val configuration = values.getAsString("configuration")
        val key = values.getAsString("query_key")
        val updated = db.update(
            "query_state", values, "configuration=? and query_key=?", arrayOf(configuration, key),
        )
        if (updated == 0) db.insertOrThrow("query_state", null, values)
    }

    private fun touch(db: SQLiteDatabase, configuration: String, key: String) {
        db.execSQL("update query_state set last_access=? where configuration=? and query_key=?", arrayOf<Any?>(System.currentTimeMillis(), configuration, key))
    }

    private fun pruneQueries(db: SQLiteDatabase, configuration: String) {
        db.execSQL(
            """delete from query_entries where configuration=? and query_key in
               (select query_key from query_state where configuration=? and pinned=0 order by last_access desc limit -1 offset ?)""",
            arrayOf<Any?>(configuration, configuration, MAX_QUERIES),
        )
        db.execSQL(
            """delete from query_state where configuration=? and query_key in
               (select query_key from query_state where configuration=? and pinned=0 order by last_access desc limit -1 offset ?)""",
            arrayOf<Any?>(configuration, configuration, MAX_QUERIES),
        )
    }

    private fun entryCount(db: SQLiteDatabase, configuration: String, key: String): Int = db.rawQuery(
        "select count(*) from query_entries where configuration=? and query_key=?", arrayOf(configuration, key),
    ).use { if (it.moveToFirst()) it.getInt(0) else 0 }

    private fun readEntryIds(db: SQLiteDatabase, configuration: String, key: String): List<String> = db.rawQuery(
        "select public_clip_id from query_entries where configuration=? and query_key=? order by position",
        arrayOf(configuration, key),
    ).use { rows -> buildList { while (rows.moveToNext()) add(rows.getString(0)) } }

    private fun loadState(db: SQLiteDatabase, configuration: String, key: String): StoredState? = db.query(
        "query_state", null, "configuration=? and query_key=?", arrayOf(configuration, key), null, null, null,
    ).use { if (it.moveToFirst()) it.toState() else null }

    private fun updateQueryMemberships(db: SQLiteDatabase, configuration: String, item: KnowledgeListItem) {
        db.rawQuery(
            "select query_key,query_json from query_state where configuration=?", arrayOf(configuration),
        ).use { queries ->
            while (queries.moveToNext()) {
                val queryKey = queries.getString(0)
                val query = runCatching { JSONObject(queries.getString(1)) }.getOrNull()
                val scope = query?.optJSONArray("knowledge_base_ids")?.toString()?.let(::jsonStrings).orEmpty()
                val base = query != null && listOf("text", "source", "source_type", "attachment", "captured_after", "captured_before")
                    .all { query.optString(it).isBlank() }
                if (!base) {
                    db.execSQL(
                        "update query_state set dirty=1 where configuration=? and query_key=?",
                        arrayOf<Any?>(configuration, queryKey),
                    )
                } else if (scope.isEmpty() || scope.any { it in item.knowledgeBaseIds }) {
                    db.insertWithOnConflict("query_entries", null, ContentValues().apply {
                        put("configuration", configuration); put("query_key", queryKey)
                        put("public_clip_id", item.clip.clipId); put("position", 0)
                    }, SQLiteDatabase.CONFLICT_REPLACE)
                } else {
                    db.delete(
                        "query_entries", "configuration=? and query_key=? and public_clip_id=?",
                        arrayOf(configuration, queryKey, item.clip.clipId),
                    )
                }
            }
        }
    }

    private fun reorderEntries(db: SQLiteDatabase, configuration: String) {
        val keys = db.rawQuery(
            "select query_key from query_state where configuration=?", arrayOf(configuration),
        ).use { rows -> buildList { while (rows.moveToNext()) add(rows.getString(0)) } }
        keys.forEach { key ->
            val ids = db.rawQuery(
                """select e.public_clip_id from query_entries e join items i
                   on i.configuration=e.configuration and i.public_clip_id=e.public_clip_id
                   where e.configuration=? and e.query_key=?
                   order by i.captured_at desc,i.public_clip_id desc""",
                arrayOf(configuration, key),
            ).use { rows -> buildList { while (rows.moveToNext()) add(rows.getString(0)) } }
            ids.forEachIndexed { position, id ->
                db.execSQL(
                    "update query_entries set position=? where configuration=? and query_key=? and public_clip_id=?",
                    arrayOf<Any?>(position, configuration, key, id),
                )
            }
        }
    }

    private fun <T> guarded(block: () -> T): T = try {
        block()
    } catch (first: SQLiteException) {
        recover()
        block()
    }

    private fun guardedWrite(block: (SQLiteDatabase) -> Unit) = guarded {
        val db = helper.writableDatabase
        db.beginTransaction()
        try {
            block(db)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    @Synchronized private fun recover() {
        runCatching { helper.close() }
        context.deleteDatabase(DB_NAME)
        helper = CacheDb(context.applicationContext)
    }

    private data class StoredState(
        val summary: KnowledgeListSummary,
        val cursor: String,
        val complete: Boolean,
        val lastSuccess: String,
        val error: String,
        val dirty: Boolean,
        val headInitialized: Boolean,
    )

    private fun Cursor.toState() = StoredState(
        KnowledgeListSummary(nullableInt("total_count"), nullableInt("matching_count"), long("revision"), string("generated_at")),
        string("next_cursor"), int("complete") != 0, string("last_success"), string("last_error"),
        int("dirty") != 0, int("head_initialized") != 0,
    )

    private fun Cursor.toItem(): KnowledgeListItem = KnowledgeListItem(
        clip = KnowledgeTopicClip(
            clipId = string("public_clip_id"), title = string("title"), summary = string("summary"),
            source = string("source"), capturedAt = string("captured_at"), safeDisplayUrl = string("safe_display_url"),
            topicAssignment = assignmentFromJson(string("topic_assignment")),
        ),
        knowledgeBaseIds = jsonStrings(string("knowledge_base_ids")), knowledgeBaseId = string("knowledge_base_id"),
        knowledgeBaseName = string("knowledge_base_name"), sourceType = string("source_type"),
        hasAttachment = int("has_attachment") != 0, itemRevision = long("item_revision"),
        updatedAt = string("updated_at"), correlationIdentity = string("correlation_identity"),
    )

    private fun Cursor.string(name: String) = getString(getColumnIndexOrThrow(name)).orEmpty()
    private fun Cursor.int(name: String) = getInt(getColumnIndexOrThrow(name))
    private fun Cursor.long(name: String) = getLong(getColumnIndexOrThrow(name))
    private fun Cursor.nullableInt(name: String): Int? = getColumnIndexOrThrow(name).let { if (isNull(it)) null else getInt(it) }
    private fun Boolean.toInt() = if (this) 1 else 0

    private fun queryJson(query: KnowledgeListQuery) = JSONObject()
        .put("knowledge_base_ids", JSONArray(query.knowledgeBaseIds)).put("text", query.text)
        .put("source", query.source).put("source_type", query.sourceType).put("attachment", query.attachment)
        .put("captured_after", query.capturedAfter).put("captured_before", query.capturedBefore)

    private fun assignmentJson(value: ClipTopicAssignment) = JSONObject()
        .put("primary", JSONObject().put("id", value.primary.id).put("name", value.primary.displayName))
        .put("secondary", JSONArray(value.secondary.map { JSONObject().put("id", it.id).put("name", it.displayName) }))
        .put("entities", JSONArray(value.entities)).put("keywords", JSONArray(value.keywords))
        .put("unclassified", value.unclassified).put("manual", value.manualOverride).put("disabled", value.topicDisabled)

    private fun assignmentFromJson(raw: String): ClipTopicAssignment = runCatching {
        val value = JSONObject(raw); val primary = value.getJSONObject("primary")
        ClipTopicAssignment(
            primary = TopicLabel(primary.getString("id"), primary.getString("name")),
            secondary = value.getJSONArray("secondary").let { array ->
                buildList { for (index in 0 until array.length()) array.getJSONObject(index).let { add(TopicLabel(it.getString("id"), it.getString("name"))) } }
            },
            entities = jsonStrings(value.optJSONArray("entities")?.toString().orEmpty()),
            keywords = jsonStrings(value.optJSONArray("keywords")?.toString().orEmpty()),
            unclassified = value.optBoolean("unclassified", true), manualOverride = value.optBoolean("manual"),
            topicDisabled = value.optBoolean("disabled"),
        )
    }.getOrDefault(ClipTopicAssignment())

    private fun jsonStrings(raw: String): List<String> = runCatching {
        val array = JSONArray(raw); buildList { for (index in 0 until array.length()) add(array.getString(index)) }
    }.getOrDefault(emptyList())

    private class CacheDb(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {
        override fun onConfigure(db: SQLiteDatabase) {
            db.setForeignKeyConstraintsEnabled(true)
            db.enableWriteAheadLogging()
        }

        override fun onCreate(db: SQLiteDatabase) = createSchema(db)

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            db.execSQL("drop table if exists query_entries")
            db.execSQL("drop table if exists query_state")
            db.execSQL("drop table if exists items")
            db.execSQL("drop table if exists sync_state")
            createSchema(db)
        }

        private fun createSchema(db: SQLiteDatabase) {
            db.execSQL("""create table items(configuration text not null, public_clip_id text not null,
                knowledge_base_ids text not null, knowledge_base_id text not null, knowledge_base_name text not null,
                title text not null, summary text not null, source text not null, source_type text not null,
                captured_at text not null, safe_display_url text not null, has_attachment integer not null,
                topic_assignment text not null, item_revision integer not null, updated_at text not null,
                correlation_identity text not null, primary key(configuration,public_clip_id))""")
            db.execSQL("""create table query_state(configuration text not null, query_key text not null,
                query_json text not null, total_count integer, matching_count integer, revision integer not null,
                generated_at text not null, next_cursor text not null, complete integer not null,
                last_success text not null, last_error text not null, last_access integer not null,
                dirty integer not null, pinned integer not null, head_initialized integer not null,
                primary key(configuration,query_key))""")
            db.execSQL("""create table query_entries(configuration text not null, query_key text not null,
                public_clip_id text not null, position integer not null,
                primary key(configuration,query_key,public_clip_id),
                foreign key(configuration,query_key) references query_state(configuration,query_key) on delete cascade,
                foreign key(configuration,public_clip_id) references items(configuration,public_clip_id) on delete cascade)""")
            db.execSQL("create index query_entries_order on query_entries(configuration,query_key,position)")
            db.execSQL("create index items_captured_order on items(configuration,captured_at desc,public_clip_id desc)")
            db.execSQL("create index items_revision on items(configuration,item_revision)")
            db.execSQL("create index items_correlation on items(configuration,correlation_identity)")
            db.execSQL("create table sync_state(configuration text primary key, next_revision integer not null, last_success text not null, last_error text not null)")
        }
    }

    companion object {
        const val MAX_QUERIES = 10
        private const val DB_NAME = "knowledge_local_first_v2.db"
        internal const val DB_VERSION = 5
    }
}
