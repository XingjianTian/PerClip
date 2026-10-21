package com.sudox.perclip.recall

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecallJsonTest {
    @Test fun parsesOverviewWindowAndSafeGraphContract() {
        val overview = RecallJson.parseOverview("""{"ok":true,"window":{"days":7,"start":"2026-07-03T00:00:00Z","end":"2026-07-10T00:00:00Z"},"metrics":{"eligible_clip_count":8,"recall_count":3,"new_topic_count":2,"reviewed_ratio":0.5},"graph":{"nodes":[{"id":"topic:abc","type":"topic","label":"AI Agent","weight":12,"color_slot":1,"topic_id":"topic:abc"}],"edges":[]},"highlights":[{"type":"topic","title":"AI Agent","subtitle":"2 clips","topic_id":"topic:abc","occurred_at":"2026-07-10T00:00:00Z"}]}""")
        assertEquals(7, overview.window.days); assertEquals(8, overview.metrics.eligibleClipCount); assertEquals("topic:abc", overview.highlights.single().topicId)
        assertFalse(overview.toString().contains("original_path"))
    }

    @Test fun parsesHighlightClientRequestId() {
        val overview = RecallJson.parseOverview("""{"ok":true,"window":{"days":7},"highlights":[{"type":"clip","title":"安全标题","clip_id":"42","client_request_id":"local-clip:note"}]}""")
        assertEquals("local-clip:note", overview.highlights.single().clientRequestId)
    }

    @Test fun parsesEveryTopicFilterItemFieldAndMissingOptionals() {
        val topic = RecallJson.parseTopic("""{"ok":true,"window":{"days":7},"topic":{"topic_id":"topic:a","label":"AI"},"metrics":{"clip_count":2,"recall_count":2,"unrecalled_count":1},"graph":{},"items":[{"clip_id":"9","client_request_id":"request-9","title":"React","summary":"A pattern","tags":["web"],"source_type":"url","source_label":"Chrome","knowledge_base_name":"Personal","captured_at":"2026-07-10T00:00:00Z","recall_count":2,"recalled_in_window":true,"score":9.5}]}""")
        assertEquals("topic:a", topic.topic.id); assertEquals(2, topic.metrics.clipCount); assertEquals(2, topic.metrics.recallCount); assertEquals(1, topic.metrics.unrecalledCount); assertEquals("request-9", topic.items.single().clientRequestId); assertEquals(2, topic.items.single().recallCount); assertEquals(9.5, topic.items.single().score, 0.0); assertTrue(topic.items.single().recalledInWindow)
        val safeEmpty = RecallJson.parseTopic("""{"ok":true,"topic":{"id":"topic:empty","label":"Empty"}}""")
        assertTrue(safeEmpty.items.isEmpty())
    }

    @Test fun parsesSessionSnapshotProgressAndActionReveal() {
        val session = RecallJson.parseSession("""{"ok":true,"session":{"id":"session-1","kind":"general","status":"active","days":7,"window":{"days":7,"start":"2026-07-04T00:00:00Z","end":"2026-07-10T12:00:00Z"},"window_start":"ignored-by-nested-window","window_end":"ignored-by-nested-window","snapshot_key":"safe-sha256","total_items":2,"current_position":1},"items":[{"id":"item-9","clip_id":"9","position":1,"title":"React","cue":"What is the pattern?","reveal_text":"Composition","summary":"Summary","tags":["web"],"status":"pending"}],"current_item":{"id":"item-9","clip_id":"9","title":"React"},"progress":{"completed":0,"total":2,"current_position":1}}""")
        assertEquals("Composition", session.items.single().revealText); assertEquals(2, session.progress.total); assertEquals("item-9", session.currentItem?.id)
        assertEquals(7, session.session.window.days); assertEquals("2026-07-04T00:00:00Z", session.session.window.start); assertEquals("2026-07-10T12:00:00Z", session.session.window.end); assertEquals("safe-sha256", session.session.snapshotKey)
        val action = RecallJson.parseEvent("""{"ok":true,"session":{"id":"session-1","status":"active","days":7,"window":{"days":7,"start":"2026-07-04T00:00:00Z","end":"2026-07-10T12:00:00Z"},"snapshot_key":"safe-sha256"},"item":{"id":"item-9","clip_id":"9","title":"React","status":"pending"},"current_item":{"id":"item-9","clip_id":"9","title":"React"},"progress":{"completed":0,"total":2,"current_position":1},"reveal_text":"Composition"}""")
        assertEquals("Composition", action.revealText); assertEquals("session-1", action.session.id)
        assertEquals(session.session.window, action.session.window); assertEquals(session.session.snapshotKey, action.session.snapshotKey)
    }

    @Test fun parsesLegacySessionWindowFieldsWhenNestedWindowIsAbsent() {
        val response = RecallJson.parseSession("""{"ok":true,"session":{"id":"session-legacy","status":"active","days":14,"window_start":"2026-06-26T00:00:00Z","window_end":"2026-07-10T12:00:00Z","snapshot_key":"safe-hash"}}""")
        assertEquals(14, response.session.window.days)
        assertEquals("2026-06-26T00:00:00Z", response.session.window.start)
        assertEquals("2026-07-10T12:00:00Z", response.session.window.end)
        assertEquals("safe-hash", response.session.snapshotKey)
    }

    @Test fun parsesNestedWeeklyReviewAndSafeClipFallback() {
        val review = RecallJson.parseWeeklyReview("""{"ok":true,"window":{"days":7},"summary":{"saved_count":5,"recall_count":3,"topic_count":2,"connection_count":4,"summary_text":"本周保存了 5 条闪记，完成 3 次回想，覆盖 2 个主题。"},"top_topics":[{"topic_id":"topic:a","label":"AI","clip_count":2,"recall_count":3,"weight":2}],"most_recalled":[{"clip_id":"9","title":"React","topic_id":"topic:a","topic_label":"AI","recall_count":3}],"suggested_items":[]}""")
        assertEquals(5, review.summary.savedCount); assertEquals("本周保存了 5 条闪记，完成 3 次回想，覆盖 2 个主题。", review.summary.summaryText); assertEquals("AI", review.topTopics.single().label); assertEquals(3, review.topTopics.single().recallCount); assertEquals("9", review.mostRecalled.single().clipId)
        assertEquals("", RecallJson.parseWeeklyReview("""{"ok":true,"summary":{}}""").summary.summaryText)
        val clip = RecallJson.parseClip("""{"ok":true,"clip":{"clip_id":"9","title":"React","safe_text":"safe","tags":["web"]}}""")
        assertEquals("safe", clip.safeText); assertFalse(clip.toString().contains("original_path"))
    }

    @Test fun createsContractedBoundedBodiesWithClientActionId() {
        val sessionBody = JSONObject(RecallJson.createSessionBody(RecallSessionRequest(days = 99, topicId = "topic:abc", limit = 99)))
        val eventBody = JSONObject(RecallJson.createEventBody(RecallEventRequest(RecallEventAction.REVEAL, "action-123")))
        assertEquals(30, sessionBody.getInt("days")); assertEquals(20, sessionBody.getInt("limit")); assertEquals("action-123", eventBody.getString("client_action_id")); assertEquals("reveal", eventBody.getString("action"))
        listOf("original_path", "ragflow_api_key", "authorization", "token", "password").forEach { forbidden -> assertFalse(sessionBody.toString().contains(forbidden, true)); assertFalse(eventBody.toString().contains(forbidden, true)) }
    }
}
