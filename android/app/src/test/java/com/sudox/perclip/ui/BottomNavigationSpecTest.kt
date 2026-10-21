package com.sudox.perclip.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BottomNavigationSpecTest {
    @Test
    fun approvedD_keepsFixedIconAlignmentAndBottomUnderline() {
        assertEquals(80, BottomNavigationSpec.NAVIGATION_HEIGHT_DP)
        assertEquals(30, BottomNavigationSpec.ICON_SLOT_DP)
        assertEquals(24, BottomNavigationSpec.STANDARD_ICON_DP)
        assertEquals(28, BottomNavigationSpec.FLASH_ICON_DP)
        assertEquals(30, BottomNavigationSpec.MEMORY_PLANET_ICON_DP)
        assertEquals(30, BottomNavigationSpec.SELECTED_UNDERLINE_WIDTH_DP)
        assertEquals(3, BottomNavigationSpec.SELECTED_UNDERLINE_HEIGHT_DP)
        assertEquals(4, BottomNavigationSpec.SELECTED_UNDERLINE_BOTTOM_INSET_DP)
        assertTrue(
            BottomNavigationSpec.MEMORY_PLANET_ICON_DP >
                BottomNavigationSpec.STANDARD_ICON_DP,
        )
        assertTrue(
            BottomNavigationSpec.FLASH_ICON_DP >
                BottomNavigationSpec.STANDARD_ICON_DP,
        )
    }
}
