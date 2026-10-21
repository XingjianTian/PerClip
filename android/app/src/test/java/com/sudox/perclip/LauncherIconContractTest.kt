package com.sudox.perclip

import java.nio.file.Files
import java.nio.file.Paths
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element
import org.w3c.dom.Node

class LauncherIconContractTest {
    @Test
    fun adaptiveIconsDeclareForegroundBackgroundAndMonochromeLayers() {
        listOf(
            "src/main/res/mipmap-anydpi-v26/ic_launcher.xml",
            "src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml",
        ).forEach { path ->
            val adaptiveIcon = document(path).documentElement

            assertEquals("@drawable/ic_launcher_background", adaptiveIcon.singleChild("background").androidAttribute("drawable"))
            assertEquals("@drawable/ic_launcher_foreground", adaptiveIcon.singleChild("foreground").androidAttribute("drawable"))
            assertEquals(0, adaptiveIcon.getElementsByTagName("monochrome").length)
        }

        listOf(
            "src/main/res/mipmap-anydpi-v33/ic_launcher.xml",
            "src/main/res/mipmap-anydpi-v33/ic_launcher_round.xml",
        ).forEach { path ->
            val adaptiveIcon = document(path).documentElement

            assertEquals("@drawable/ic_launcher_background", adaptiveIcon.singleChild("background").androidAttribute("drawable"))
            assertEquals("@drawable/ic_launcher_foreground", adaptiveIcon.singleChild("foreground").androidAttribute("drawable"))
            assertEquals("@drawable/ic_launcher_monochrome", adaptiveIcon.singleChild("monochrome").androidAttribute("drawable"))
        }
    }

    @Test
    fun launcherDrawableResourcesExist() {
        listOf(
            "src/main/res/drawable-nodpi/ic_brand_perclip.png",
            "src/main/res/drawable-night-nodpi/ic_brand_perclip.png",
            "src/main/res/drawable-nodpi/ic_launcher_foreground_exact.png",
            "src/main/res/drawable-night-nodpi/ic_launcher_foreground_exact.png",
            "src/main/res/drawable/ic_launcher_background.xml",
            "src/main/res/drawable-night/ic_launcher_background.xml",
            "src/main/res/drawable/ic_launcher_foreground.xml",
            "src/main/res/drawable-night/ic_launcher_foreground.xml",
            "src/main/res/drawable/ic_launcher_monochrome.xml",
            "src/main/res/drawable/ic_notification.xml",
            "src/main/res/drawable/ic_qs_flash.xml",
        ).forEach { path ->
            assertTrue("$path should exist", Files.exists(Paths.get(path)))
        }
    }

    @Test
    fun suppliedPixelMastersAreRetainedAtSourceResolution() {
        listOf(
            "src/main/res/drawable-nodpi/ic_brand_perclip.png",
            "src/main/res/drawable-night-nodpi/ic_brand_perclip.png",
            "src/main/res/drawable-nodpi/ic_launcher_foreground_exact.png",
            "src/main/res/drawable-night-nodpi/ic_launcher_foreground_exact.png",
        ).forEach { path ->
            assertTrue("$path should exist", Files.exists(Paths.get(path)))
            assertTrue("$path should not be an empty placeholder", Files.size(Paths.get(path)) > 100_000)
        }
    }

    @Test
    fun alphaOnlyVectorsReuseTheExtracted1254PixelContour() {
        val sourcePaths = listOf(
            "src/main/res/drawable/ic_launcher_monochrome.xml",
            "src/main/res/drawable/ic_shortcut_flash.xml",
        )

        sourcePaths.forEach { path ->
            val xml = String(Files.readAllBytes(Paths.get(path)))
            assertTrue("$path should use the 12540 trace grid", xml.contains("android:viewportWidth=\"12540\""))
            assertTrue("$path should contain the traced upper endpoint", xml.contains("M7465 10236"))
            assertTrue("$path should contain the traced right orbit", xml.contains("M8325 7770"))
            assertTrue("$path should contain the traced left orbit", xml.contains("M4860 7308"))
            assertTrue("$path should be a filled contour, not a reconstructed stroke", !xml.contains("strokeLineCap"))
        }
    }

    @Test
    fun notificationUsesExactBrandCenterFoldWithoutOrbit() {
        val xml = String(Files.readAllBytes(Paths.get("src/main/res/drawable/ic_notification.xml")))

        assertTrue(xml.contains("android:width=\"24dp\""))
        assertTrue(xml.contains("android:height=\"24dp\""))
        assertTrue(xml.contains("android:viewportWidth=\"12540\""))
        assertTrue(xml.contains("M7465 10236"))
        assertTrue(!xml.contains("ic_launcher_monochrome"))
        assertTrue(!xml.contains("M8325 7770"))
        assertTrue(!xml.contains("M4860 7308"))
    }

    private fun document(path: String) = DocumentBuilderFactory.newInstance().apply {
        isNamespaceAware = true
    }
        .newDocumentBuilder()
        .parse(Paths.get(path).toFile())

    private fun Element.singleChild(tagName: String): Element {
        return getElementsByTagName(tagName)
            .asElements()
            .single()
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
