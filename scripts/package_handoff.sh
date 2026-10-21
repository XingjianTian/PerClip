#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="${PERCLIP_PACKAGE_STAMP:-$(date +%Y%m%d-%H%M%S)}"
DIST_DIR="$ROOT_DIR/dist"
PACKAGE_NAME="PerClip-handoff-${STAMP}"
PACKAGE_DIR="$DIST_DIR/$PACKAGE_NAME"
APK_SOURCE="$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
APK_METADATA_SOURCE="$ROOT_DIR/android/app/build/outputs/apk/debug/output-metadata.json"
APK_TARGET_NAME="PerClip-debug.apk"

export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"

step() {
  printf '\n==> %s\n' "$1"
}

copy_dir() {
  local source="$1"
  local target="$2"
  mkdir -p "$(dirname "$target")"
  rsync -a \
    --exclude '.DS_Store' \
    --exclude '._*' \
    --exclude '.env' \
    --exclude '/data/' \
    --exclude '.gradle/' \
    --exclude '.kotlin/' \
    --exclude 'build/' \
    --exclude 'local.properties' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '*.egg-info/' \
    --exclude '*.jks' \
    --exclude '*.keystore' \
    --exclude '*.pem' \
    --exclude '*.p12' \
    --exclude '*.pyc' \
    "$source" "$target"
}

step "Build debug APK if needed"
if [[ ! -f "$APK_SOURCE" || ! -f "$APK_METADATA_SOURCE" ]]; then
  (cd "$ROOT_DIR/android" && ./gradlew assembleDebug)
fi

step "Audit APK"
"$ROOT_DIR/scripts/audit_android_apk.sh" "$APK_SOURCE"

step "Create handoff package"
rm -rf "$PACKAGE_DIR" "$DIST_DIR/$PACKAGE_NAME.zip"
mkdir -p "$PACKAGE_DIR/apk" "$PACKAGE_DIR/android" "$PACKAGE_DIR/server" "$PACKAGE_DIR/scripts" "$PACKAGE_DIR/docs" "$PACKAGE_DIR/deploy"

cp "$APK_SOURCE" "$PACKAGE_DIR/apk/$APK_TARGET_NAME"
if [[ -f "$APK_METADATA_SOURCE" ]]; then
  cp "$APK_METADATA_SOURCE" "$PACKAGE_DIR/apk/output-metadata.json"
fi
cp "$ROOT_DIR/plan.md" "$PACKAGE_DIR/plan.md"
cp "$ROOT_DIR/docs/e2e-verification.md" "$PACKAGE_DIR/docs/e2e-verification.md"
cp "$ROOT_DIR/docs/real-device-runbook.md" "$PACKAGE_DIR/docs/real-device-runbook.md"
copy_dir "$ROOT_DIR/android/" "$PACKAGE_DIR/android/"
cp "$ROOT_DIR/server/README.md" "$PACKAGE_DIR/server/README.md"
cp "$ROOT_DIR/server/.env.example" "$PACKAGE_DIR/server/.env.example"
cp "$ROOT_DIR/server/pyproject.toml" "$PACKAGE_DIR/server/pyproject.toml"
copy_dir "$ROOT_DIR/server/perclip_ingest/" "$PACKAGE_DIR/server/perclip_ingest/"
copy_dir "$ROOT_DIR/scripts/" "$PACKAGE_DIR/scripts/"
copy_dir "$ROOT_DIR/deploy/" "$PACKAGE_DIR/deploy/"

cat > "$PACKAGE_DIR/README.md" <<'EOF'
# PerClip 交付包

这个包用于真机和 NAS/RAGFlow 验收，不包含真实 token、RAGFlow API Key 或 `server/.env`。

## 内容

- `apk/PerClip-debug.apk`：可安装的 debug APK。
- `BUILD_INFO.txt`：APK 包名、版本、大小、SHA-256 和交付包时间戳。
- `android/`：可重建 Android 工程源码、Gradle wrapper 和测试；不包含 `.gradle/`、`build/`、`local.properties` 或签名文件。
- `ANDROID_SOURCE_MANIFEST.txt`：交付包内 Android 源码文件的 SHA-256 清单。
- `server/`：NAS ingest API 源码、依赖声明和 `.env.example`。
- `deploy/`：可选 systemd 持久化部署模板和 NAS 部署说明。
- `scripts/`：安装、配置、启动、smoke、readiness 和本地验证脚本。
- `docs/e2e-verification.md`：端到端验收清单。
- `docs/real-device-runbook.md`：真机/NAS/RAGFlow 验收执行顺序和记录模板。
- `plan.md`：当前产品计划和开发状态。
- `SHA256SUMS.txt`：关键交付文件校验和。

## 推荐顺序

1. 在源码项目根目录先运行 `scripts/verify_local.sh`。
2. 对交付包运行 `scripts/verify_handoff_package.sh dist/PerClip-handoff-*.zip`；需要从包内源码重建时设置 `PERCLIP_VERIFY_REBUILD=1`。
3. 在真机/NAS 验收前运行 `scripts/check_e2e_readiness.sh`。
4. 运行 `scripts/collect_real_device_evidence.sh` 生成不含密钥的验收报告；真机和 NAS 都就绪后可设置 `PERCLIP_RUN_DEVICE_SMOKES=1 PERCLIP_RUN_SERVER_SMOKE=1`。
5. 连接模拟器或真机后，运行 `scripts/adb_local_e2e_smoke.sh` 验证 Android App -> 本机 local ingest 的上传链路。
6. 运行 `scripts/adb_clip_library_smoke.sh` 验证本地 `闪记库` 列表、搜索、筛选、详情和返回。
7. 用 `scripts/install_debug_apk.sh` 或手动 `adb install -r apk/PerClip-debug.apk` 安装。
8. 在 NAS 侧复制 `server/.env.example` 为 `server/.env`，用 `scripts/generate_mobile_token.sh --env` 生成真实 mobile token，只在服务端填写 PersonalClips 路径、dataset id 和 RAGFlow API Key；需要持久化服务时参考 `deploy/nas-systemd.md`。
9. 运行 `scripts/run_server_clip_to_ragflow.sh`。
10. 按 `docs/real-device-runbook.md` 执行真机/NAS 验收，并用 `docs/e2e-verification.md` 补充详细证据矩阵。

Android App 只需要 NAS API 地址和 mobile ingest token；不要把 RAGFlow API Key 填进 App 或 APK。

如需从交付包源码重建 APK：

```bash
cd android
./gradlew testDebugUnitTest assembleDebug lintDebug
```
EOF

step "Write build info"
(
  cd "$PACKAGE_DIR"
  python3 - "$APK_TARGET_NAME" "$STAMP" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

apk_name = sys.argv[1]
stamp = sys.argv[2]
apk_path = Path("apk") / apk_name
metadata_path = Path("apk/output-metadata.json")

metadata = {}
if metadata_path.exists():
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    element = payload.get("elements", [{}])[0]
    metadata = {
        "application_id": payload.get("applicationId", ""),
        "variant": payload.get("variantName", ""),
        "version_code": element.get("versionCode", ""),
        "version_name": element.get("versionName", ""),
        "min_sdk_for_dexing": payload.get("minSdkVersionForDexing", ""),
    }

sha256 = hashlib.sha256(apk_path.read_bytes()).hexdigest()
size_bytes = apk_path.stat().st_size

lines = [
    "# PerClip Build Info",
    "",
    f"handoff_stamp: {stamp}",
    f"apk: {apk_path.as_posix()}",
    f"apk_size_bytes: {size_bytes}",
    f"apk_sha256: {sha256}",
    f"application_id: {metadata.get('application_id', 'com.sudox.perclip')}",
    f"variant: {metadata.get('variant', 'debug')}",
    f"version_name: {metadata.get('version_name', '')}",
    f"version_code: {metadata.get('version_code', '')}",
    f"min_sdk_for_dexing: {metadata.get('min_sdk_for_dexing', '')}",
    "",
    "verification_entrypoints:",
    "- scripts/verify_local.sh",
    "- scripts/verify_handoff_package.sh",
    "- scripts/generate_mobile_token.sh",
    "- scripts/check_e2e_readiness.sh",
    "- scripts/collect_real_device_evidence.sh",
    "- scripts/adb_entrypoint_smoke.sh",
    "- scripts/adb_notification_entry_smoke.sh",
    "- scripts/adb_qs_tile_smoke.sh",
    "- scripts/adb_local_e2e_smoke.sh",
    "- scripts/adb_clip_library_smoke.sh",
    "",
    "security_boundary:",
    "- Android APK contains no RAGFlow API key.",
    "- Fill server/.env only on the NAS/server side.",
]
Path("BUILD_INFO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
)

step "Write Android source manifest"
(
  cd "$PACKAGE_DIR"
  find android -type f -print | LC_ALL=C sort | while IFS= read -r file; do
    shasum -a 256 "$file"
  done > ANDROID_SOURCE_MANIFEST.txt
)

step "Write checksums"
(
  cd "$PACKAGE_DIR"
  shasum -a 256 \
    "apk/$APK_TARGET_NAME" \
    "apk/output-metadata.json" \
    "BUILD_INFO.txt" \
    "ANDROID_SOURCE_MANIFEST.txt" \
    "scripts/verify_handoff_package.sh" \
    "scripts/generate_mobile_token.sh" \
    "scripts/collect_real_device_evidence.sh" \
    "deploy/nas-systemd.md" \
    "deploy/perclip-ingest.service" \
    "server/.env.example" \
    "server/pyproject.toml" \
    "docs/e2e-verification.md" \
    "docs/real-device-runbook.md" \
    "plan.md" \
    > SHA256SUMS.txt
)

step "Create zip"
(
  cd "$DIST_DIR"
  zip -qr "$PACKAGE_NAME.zip" "$PACKAGE_NAME"
)

printf '\nHandoff package created:\n'
printf '  %s\n' "$PACKAGE_DIR"
printf '  %s\n' "$DIST_DIR/$PACKAGE_NAME.zip"
