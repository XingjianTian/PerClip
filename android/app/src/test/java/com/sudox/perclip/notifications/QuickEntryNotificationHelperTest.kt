package com.sudox.perclip.notifications

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Paths
import javax.xml.parsers.DocumentBuilderFactory
import org.w3c.dom.Element
import org.w3c.dom.Node

class QuickEntryNotificationHelperTest {
    @Test
    fun exposesStableNotificationIdentifiers() {
        assertEquals(10_001, QuickEntryNotificationHelper.QUICK_ENTRY_NOTIFICATION_ID)
        assertEquals("perclip_quick_entry_v3", QuickEntryNotificationHelper.CHANNEL_ID)
    }

    @Test
    fun compactNotificationLayoutKeepsCaptureButtonInCollapsedView() {
        val root = document("src/main/res/layout/notification_quick_entry.xml").documentElement
        val title = root.childElements("TextView")
            .single { element -> element.androidAttribute("id") == "@+id/notification_quick_entry_title" }
        val captureButton = root.childElements("TextView")
            .single { element -> element.androidAttribute("id") == "@+id/notification_quick_entry_capture" }

        assertEquals("48dp", root.androidAttribute("layout_height"))
        assertEquals("8dp", root.androidAttribute("paddingStart"))
        assertEquals("8dp", root.androidAttribute("paddingEnd"))
        assertEquals("@color/perclip_notification_title", title.androidAttribute("textColor"))
        assertEquals("76dp", captureButton.androidAttribute("layout_width"))
        assertEquals("闪记", captureButton.androidAttribute("text"))
        assertEquals("闪记", captureButton.androidAttribute("contentDescription"))
        assertEquals("@color/perclip_notification_button_text", captureButton.androidAttribute("textColor"))
    }

    @Test
    fun persistentEntryUsesLowInterruptionNotificationContract() {
        val source = Paths.get(
            "src/main/java/com/sudox/perclip/notifications/QuickEntryNotificationHelper.kt",
        ).toFile().readText()
        val actionBackground = document("src/main/res/drawable/notification_quick_action_bg.xml").documentElement

        assertEquals(
            "@color/perclip_notification_action_background",
            actionBackground.childElements("solid").single().androidAttribute("color"),
        )
        assertTrue(source.contains("NotificationManager.IMPORTANCE_LOW"))
        assertTrue(source.contains(".setSilent(true)"))
        assertTrue(source.contains(".setOngoing(true)"))
        assertTrue(source.contains(".setOnlyAlertOnce(true)"))
        assertTrue(source.contains("setShowBadge(false)"))
        assertTrue(source.contains(".setCategory(NotificationCompat.CATEGORY_SERVICE)"))
        assertTrue(source.contains("R.color.perclip_notification_accent"))
    }

    private fun document(path: String) = DocumentBuilderFactory.newInstance().apply {
        isNamespaceAware = true
    }
        .newDocumentBuilder()
        .parse(Paths.get(path).toFile())

    private fun Element.childElements(tagName: String): List<Element> {
        return getElementsByTagName(tagName).asElements()
    }

    private fun Element.androidAttribute(name: String): String {
        return attributes.getNamedItemNS(ANDROID_NAMESPACE, name).nodeValue
    }

    private fun org.w3c.dom.NodeList.asElements(): List<Element> {
        return (0 until length).mapNotNull { index ->
            item(index).takeIf { node -> node.nodeType == Node.ELEMENT_NODE } as? Element
        }
    }

    companion object {
        private const val ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
    }
}
