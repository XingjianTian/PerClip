#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RES_DIR="$ROOT_DIR/android/app/src/main/res"
APK_PATH="${1:-$ROOT_DIR/android/app/build/outputs/apk/release/app-release-unsigned.apk}"

fail() {
  echo "Brand icon audit failed: $*" >&2
  exit 1
}

required_files=(
  "$RES_DIR/drawable-nodpi/ic_brand_perclip.png"
  "$RES_DIR/drawable-night-nodpi/ic_brand_perclip.png"
  "$RES_DIR/drawable-nodpi/ic_launcher_foreground_exact.png"
  "$RES_DIR/drawable-night-nodpi/ic_launcher_foreground_exact.png"
  "$RES_DIR/drawable/ic_launcher_background.xml"
  "$RES_DIR/drawable-night/ic_launcher_background.xml"
  "$RES_DIR/drawable/ic_launcher_foreground.xml"
  "$RES_DIR/drawable-night/ic_launcher_foreground.xml"
  "$RES_DIR/drawable/ic_launcher_monochrome.xml"
  "$RES_DIR/drawable/ic_launcher_dev_foreground.xml"
  "$RES_DIR/drawable/ic_shortcut_flash.xml"
  "$RES_DIR/drawable/ic_qs_flash.xml"
  "$RES_DIR/drawable/ic_notification.xml"
  "$RES_DIR/mipmap-anydpi-v26/ic_launcher.xml"
  "$RES_DIR/mipmap-anydpi-v26/ic_launcher_round.xml"
  "$RES_DIR/mipmap-anydpi-v33/ic_launcher.xml"
  "$RES_DIR/mipmap-anydpi-v33/ic_launcher_round.xml"
)
for path in "${required_files[@]}"; do
  [[ -f "$path" ]] || fail "missing ${path#$ROOT_DIR/}"
done

obsolete_files=(
  "$RES_DIR/drawable-nodpi/ic_launcher_foreground_pixel.png"
)
for path in "${obsolete_files[@]}"; do
  [[ ! -e "$path" ]] || fail "obsolete bitmap remains: ${path#$ROOT_DIR/}"
done

SOURCE_MANIFEST="$RES_DIR/../AndroidManifest.xml"
MERGED_RELEASE_MANIFEST="$ROOT_DIR/android/app/build/intermediates/merged_manifest/release/processReleaseMainManifest/AndroidManifest.xml"
grep -q 'android:icon="${launcherIcon}"' "$SOURCE_MANIFEST" || fail "Manifest launcher placeholder is missing"
grep -q 'android:roundIcon="${launcherRoundIcon}"' "$SOURCE_MANIFEST" || fail "Manifest round launcher placeholder is missing"
grep -q 'android:icon="@drawable/ic_qs_flash"' "$SOURCE_MANIFEST" || fail "Quick Settings tile must use the alpha-only icon"
[[ -f "$MERGED_RELEASE_MANIFEST" ]] || fail "merged Release manifest is missing; assemble Release before auditing"
grep -q 'android:icon="@mipmap/ic_launcher"' "$MERGED_RELEASE_MANIFEST" || fail "Release launcher does not resolve to production icon"
grep -q 'android:roundIcon="@mipmap/ic_launcher_round"' "$MERGED_RELEASE_MANIFEST" || fail "Release round launcher does not resolve to production icon"

if grep -q '<monochrome' "$RES_DIR"/mipmap-anydpi-v26/ic_launcher*.xml; then
  fail "monochrome must be isolated to API 33 resources"
fi
for path in "$RES_DIR"/mipmap-anydpi-v33/ic_launcher*.xml; do
  grep -q '<monochrome android:drawable="@drawable/ic_launcher_monochrome"' "$path" ||
    fail "missing shared themed icon in ${path#$ROOT_DIR/}"
done

for path in "$RES_DIR/drawable/ic_launcher_monochrome.xml" "$RES_DIR/drawable/ic_shortcut_flash.xml"; do
  grep -q 'android:viewportWidth="12540"' "$path" || fail "trace grid drift in ${path#$ROOT_DIR/}"
  grep -q 'M7465 10236' "$path" || fail "upper contour drift in ${path#$ROOT_DIR/}"
  grep -q 'M8325 7770' "$path" || fail "right contour drift in ${path#$ROOT_DIR/}"
  grep -q 'M4860 7308' "$path" || fail "left contour drift in ${path#$ROOT_DIR/}"
  ! grep -q 'strokeLineCap' "$path" || fail "${path#$ROOT_DIR/} reconstructed the contour as strokes"
done

for path in "$RES_DIR/drawable/ic_launcher_foreground.xml" "$RES_DIR/drawable-night/ic_launcher_foreground.xml"; do
  grep -q '@drawable/ic_launcher_foreground_exact' "$path" || fail "pixel foreground missing in ${path#$ROOT_DIR/}"
done

grep -q '#FCFBFF' "$RES_DIR/drawable/ic_launcher_background.xml" || fail "light launcher background token drift"
grep -q '#121017' "$RES_DIR/drawable-night/ic_launcher_background.xml" || fail "dark launcher background token drift"
grep -q '@drawable/ic_launcher_monochrome' "$RES_DIR/drawable/ic_qs_flash.xml" || fail "Quick Settings icon does not reuse the extracted alpha-only contour"
grep -q 'android:width="24dp"' "$RES_DIR/drawable/ic_notification.xml" || fail "notification icon must use a dedicated 24dp canvas"
grep -q 'android:viewportWidth="12540"' "$RES_DIR/drawable/ic_notification.xml" || fail "notification center fold must preserve the source trace grid"
grep -q 'M7465 10236' "$RES_DIR/drawable/ic_notification.xml" || fail "notification icon is missing the exact brand center fold"
! grep -q 'M8325 7770' "$RES_DIR/drawable/ic_notification.xml" || fail "notification icon must omit the right orbit at 24dp"
! grep -q 'M4860 7308' "$RES_DIR/drawable/ic_notification.xml" || fail "notification icon must omit the left orbit at 24dp"
! grep -q '@drawable/ic_launcher_monochrome' "$RES_DIR/drawable/ic_notification.xml" || fail "notification icon must not squeeze the full brand mark into the status bar"
for path in "$RES_DIR/drawable/ic_notification.xml" "$RES_DIR/drawable/ic_qs_flash.xml"; do
  if grep -Eq '#(B683F2|C195F7|FCFBFF|121017)' "$path"; then
    fail "${path##*/} embeds full-color palette"
  fi
done
grep -q 'B683F2' "$RES_DIR/drawable/ic_shortcut_flash.xml" || fail "shortcut does not use lavender brand token"

grep -q 'PerClipBrandMark' "$ROOT_DIR/android/app/src/main/java/com/sudox/perclip/ui/screens/FlashNoteScreen.kt" || fail "Flash header does not use shared brand mark"
grep -q 'PerClipBrandMark' "$ROOT_DIR/android/app/src/main/java/com/sudox/perclip/ui/screens/SettingsSecondaryScreens.kt" || fail "System Information does not use shared brand mark"
grep -q 'Icons.Rounded.Bolt' "$ROOT_DIR/android/app/src/main/java/com/sudox/perclip/ui/PerClipApp.kt" || fail "functional Flash navigation icon was unexpectedly replaced"

density_specs=(mdpi:48 hdpi:72 xhdpi:96 xxhdpi:144 xxxhdpi:192)
for spec in "${density_specs[@]}"; do
  density="${spec%%:*}"
  expected_size="${spec##*:}"
  for folder in "mipmap-$density" "mipmap-night-$density"; do
    for name in ic_launcher.png ic_launcher_round.png; do
      path="$RES_DIR/$folder/$name"
      [[ -f "$path" ]] || fail "missing legacy fallback ${path#$ROOT_DIR/}"
      dimensions="$(file "$path")"
      [[ "$dimensions" == *"$expected_size x $expected_size"* ]] || fail "unexpected dimensions for ${path#$ROOT_DIR/}: $dimensions"
    done
  done
done

[[ -f "$APK_PATH" ]] || fail "APK not found: $APK_PATH"
if unzip -l "$APK_PATH" | grep -Eiq 'stage21\.10|mockup|reference|watermark|play-store-512'; then
  fail "release APK contains design evidence"
fi

echo "Brand icon audit passed: supplied pixel masters, extracted contour, themed/system icons and legacy fallbacks are complete."
