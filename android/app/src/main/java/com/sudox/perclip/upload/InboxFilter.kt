package com.sudox.perclip.upload

import com.sudox.perclip.ClipKind

enum class InboxFilter(val label: String) {
    All("全部"),
    Urls("链接"),
    Texts("文字"),
    Images("图片"),
    Files("文件"),
    ;

    fun matches(record: UploadRecord): Boolean {
        return when (this) {
            All -> true
            Urls -> record.clip.kind == ClipKind.Url
            Texts -> record.clip.kind == ClipKind.Text || record.clip.kind == ClipKind.ScreenClip
            Images -> record.clip.kind == ClipKind.Image
            Files -> record.clip.kind == ClipKind.File || record.clip.kind == ClipKind.Multiple
        }
    }
}
