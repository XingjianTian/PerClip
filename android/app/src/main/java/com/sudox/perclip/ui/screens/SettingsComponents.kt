package com.sudox.perclip.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.sudox.perclip.design.ColorTokens
import com.sudox.perclip.design.perClipAccentColor
import com.sudox.perclip.design.perClipAccentSoftColor

internal object KimiSettingsColors {
    val Connection = Color(0xFF7862F2)
    val Capture = Color(0xFF5B8DEF)
    val KnowledgeBase = Color(0xFF1FAD7A)
    val Planet = Color(0xFF9B5CF6)
    val Theme = Color(0xFFE15A8C)
    val NeutralRowLight = Color(0xFF6F7891)
    val NeutralRowDark = Color(0xFF9AA3BC)
    val CardLight = Color(0xFFFFFFFF)
    val CardDark = Color(0xFF251D31)
    val CardBorderLight = Color(0xFFEEEAFB)
    val DividerLight = Color(0xFFF1EEFA)
    val TextPrimaryLight = Color(0xFF18172D)
    val TextSecondaryLight = Color(0xFF69647D)
    val TextTertiaryLight = Color(0xFF8D879F)
    val TextPrimaryDark = Color(0xFFF4F0FC)
    val TextSecondaryDark = Color(0xFFC4B7CA)
    val TextTertiaryDark = Color(0xFF99899F)
    val SwitchTrackLight = Color(0xFFDDD6F0)
    val SwitchTrackDark = Color(0xFF3A3148)
    val SwitchCheckedLight = Color(0xFF7862F2)
    val SwitchCheckedDark = Color(0xFF917AFF)
    val PageBackgroundLight = Color(0xFFF8F6FE)
    val PageBackgroundDark = Color(0xFF1A141E)

    fun neutralRow(isDark: Boolean): Color = if (isDark) NeutralRowDark else NeutralRowLight

    fun divider(isDark: Boolean): Color = if (isDark) Color(0x0FFFFFFF) else DividerLight

    fun cardBorder(isDark: Boolean): Color = if (isDark) Color(0x12FFFFFF) else CardBorderLight

    fun iconTileBackground(tint: Color, isDark: Boolean): Color =
        if (isDark) Color(0x14FFFFFF) else Color(
            red = tint.red, green = tint.green, blue = tint.blue, alpha = 31 / 255f,
        )

    fun cardColor(isDark: Boolean, surface: Color): Color = if (isDark) CardDark else CardLight

    fun pageBackground(isDark: Boolean): Color = if (isDark) PageBackgroundDark else PageBackgroundLight

    fun titleText(isDark: Boolean, onSurface: Color): Color = if (isDark) TextPrimaryDark else TextPrimaryLight

    fun summaryText(isDark: Boolean, onSurfaceVariant: Color): Color = if (isDark) TextSecondaryDark else TextSecondaryLight

    fun tertiaryText(isDark: Boolean): Color = if (isDark) TextTertiaryDark else TextTertiaryLight

    fun switchTrack(checked: Boolean = false, isDark: Boolean): Color = when {
        checked && isDark -> SwitchCheckedDark
        checked -> SwitchCheckedLight
        isDark -> SwitchTrackDark
        else -> SwitchTrackLight
    }
}

/** Shared semantic type ramp for Settings Home and every Settings destination. */
internal object PerClipSettingsTypography {
    val PageTitle = TextStyle(fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.Black)
    val RowTitle = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold)
    val Supporting = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, fontWeight = FontWeight.Normal)
}

@Composable
internal fun settingsPrimaryTextColor(): Color =
    KimiSettingsColors.titleText(isDarkSettingsBackground(), MaterialTheme.colorScheme.onSurface)

@Composable
internal fun settingsSecondaryTextColor(): Color =
    KimiSettingsColors.summaryText(isDarkSettingsBackground(), MaterialTheme.colorScheme.onSurfaceVariant)

@Composable
internal fun settingsTertiaryTextColor(): Color =
    KimiSettingsColors.tertiaryText(isDarkSettingsBackground())

@Composable
internal fun isDarkSettingsBackground(): Boolean =
    MaterialTheme.colorScheme.background.luminance() < .5f

@Composable
internal fun settingsPageBackgroundColor(): Color =
    if (MaterialTheme.colorScheme.background.luminance() < .5f) {
        MaterialTheme.colorScheme.background
    } else {
        ColorTokens.FlashBackground
    }

@Composable
internal fun SettingsGroupTitle(title: String, modifier: Modifier = Modifier) {
    Text(title, modifier.padding(start = 4.dp, top = 6.dp, bottom = 2.dp), style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor(), fontWeight = FontWeight.SemiBold)
}

@Composable
internal fun SettingsIcon(
    icon: ImageVector,
    tint: Color? = null,
    containerSize: Dp = 36.dp,
    iconSize: Dp = 19.dp,
) {
    val iconTint = tint ?: perClipAccentColor()
    val soft = perClipAccentSoftColor()
    Surface(Modifier.size(containerSize), RoundedCornerShape(10.dp), color = soft) {
        Box(contentAlignment = Alignment.Center) { Icon(icon, null, Modifier.size(iconSize), tint = iconTint) }
    }
}

// ---- KIMI 首页专用组件（仅供 Settings Home 显式使用，不影响共享默认值）----

@Composable
internal fun KimiSettingsGroupTitle(title: String, modifier: Modifier = Modifier) {
    Text(title, modifier.padding(start = 4.dp, top = 6.dp, bottom = 2.dp), style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor(), fontWeight = FontWeight.SemiBold)
}

@Composable
internal fun KimiSettingsIcon(
    icon: ImageVector,
    tint: Color,
) {
    val isDark = isDarkSettingsBackground()
    Surface(Modifier.size(36.dp), RoundedCornerShape(12.dp), color = KimiSettingsColors.iconTileBackground(tint, isDark)) {
        Box(contentAlignment = Alignment.Center) { Icon(icon, null, Modifier.size(20.dp), tint = tint) }
    }
}

@Composable
internal fun KimiSettingsGroupCard(content: @Composable () -> Unit) {
    val isDark = isDarkSettingsBackground()
    val shape = RoundedCornerShape(22.dp)
    val cardModifier = if (isDark) {
        Modifier.fillMaxWidth()
    } else {
        Modifier.fillMaxWidth().shadow(
            elevation = 12.dp,
            shape = shape,
            ambientColor = Color(0xFF7A6CC9),
            spotColor = Color(0xFF7A6CC9),
        )
    }
    Surface(
        cardModifier,
        shape,
        color = KimiSettingsColors.cardColor(isDark, MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, KimiSettingsColors.cardBorder(isDark)),
    ) {
        Column { content() }
    }
}

@Composable
internal fun KimiSettingsCardDivider() {
    val isDark = isDarkSettingsBackground()
    Box(
        Modifier
            .fillMaxWidth()
            .padding(start = 66.dp, end = 16.dp)
            .heightIn(min = 1.dp)
            .background(KimiSettingsColors.divider(isDark)),
    )
}

@Composable
internal fun KimiSettingsRow(
    title: String,
    summary: String,
    icon: ImageVector,
    iconTint: Color,
    onClick: (() -> Unit)? = null,
    checked: Boolean? = null,
    onCheckedChange: ((Boolean) -> Unit)? = null,
    enabled: Boolean = true,
) {
    val action = onClick ?: if (checked != null && onCheckedChange != null) ({ onCheckedChange(!checked) }) else null
    val isDark = isDarkSettingsBackground()
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .then(if (action != null) Modifier.clickable(enabled = enabled, onClick = action) else Modifier)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        KimiSettingsIcon(icon, iconTint)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = PerClipSettingsTypography.RowTitle,
                color = KimiSettingsColors.titleText(isDark, MaterialTheme.colorScheme.onSurface),
            )
            Text(
                summary,
                style = PerClipSettingsTypography.Supporting,
                color = KimiSettingsColors.summaryText(isDark, MaterialTheme.colorScheme.onSurfaceVariant),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (checked != null && onCheckedChange != null) {
            KimiSettingsSwitch(checked = checked, onCheckedChange = onCheckedChange, enabled = enabled)
        } else if (action != null) {
            Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null, tint = KimiSettingsColors.summaryText(isDark, MaterialTheme.colorScheme.onSurfaceVariant))
        }
    }
}

/**
 * KIMI 首页专用开关（figma-spec：track 44x26 r13、thumb 22 白、
 * unchecked track light #DDD6F0 / dark #3A3148）。
 * 局部实现，不修改共享 SettingsRow 的 Material3 Switch。
 */
@Composable
internal fun KimiSettingsSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    enabled: Boolean = true,
) {
    val isDark = isDarkSettingsBackground()
    val interactionSource = remember { MutableInteractionSource() }
    Box(
        Modifier
            .size(width = 44.dp, height = 26.dp)
            .toggleable(
                value = checked,
                enabled = enabled,
                role = Role.Switch,
                interactionSource = interactionSource,
                indication = null,
                onValueChange = onCheckedChange,
            )
            .background(KimiSettingsColors.switchTrack(checked, isDark), RoundedCornerShape(13.dp)),
        contentAlignment = if (checked) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(
            Modifier
                .padding(horizontal = 2.dp)
                .size(22.dp)
                .shadow(1.dp, RoundedCornerShape(11.dp))
                .background(Color.White, RoundedCornerShape(11.dp)),
        )
    }
}

// ---- 共享 SettingsRow（恢复 T-20260809-001 前默认视觉；二级页保持不变）----

@Composable
internal fun SettingsRow(
    title: String,
    summary: String,
    icon: ImageVector,
    onClick: (() -> Unit)? = null,
    checked: Boolean? = null,
    onCheckedChange: ((Boolean) -> Unit)? = null,
    enabled: Boolean = true,
    danger: Boolean = false,
) {
    val action = onClick ?: if (checked != null && onCheckedChange != null) ({ onCheckedChange(!checked) }) else null
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp)
            .then(if (action != null) Modifier.clickable(enabled = enabled, onClick = action) else Modifier)
            .padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsIcon(icon, if (danger) MaterialTheme.colorScheme.error else perClipAccentColor())
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = PerClipSettingsTypography.RowTitle, color = if (danger) MaterialTheme.colorScheme.error else settingsPrimaryTextColor())
            Text(summary, style = PerClipSettingsTypography.Supporting, color = settingsSecondaryTextColor(), maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        if (checked != null && onCheckedChange != null) {
            PerClipSettingsSwitch(checked, onCheckedChange, enabled)
        } else if (action != null) {
            Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null, tint = if (danger) MaterialTheme.colorScheme.error else perClipAccentColor())
        }
    }
}

@Composable
internal fun PerClipSettingsSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    enabled: Boolean = true,
) {
    val isDark = isDarkSettingsBackground()
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        enabled = enabled,
        colors = SwitchDefaults.colors(
            checkedThumbColor = Color.White,
            checkedTrackColor = perClipAccentColor(),
            checkedBorderColor = Color.Transparent,
            uncheckedThumbColor = if (isDark) ColorTokens.DarkPlumSecondary else Color.White,
            uncheckedTrackColor = if (isDark) ColorTokens.DarkPlumRaised else KimiSettingsColors.SwitchTrackLight,
            uncheckedBorderColor = if (isDark) ColorTokens.DarkPlumBorderSoft else Color(0xFFCEC6E2),
        ),
    )
}
