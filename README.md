# PerClip

PerClip 是面向自托管的 Android 内容收集与 Core Memory 工具：分享或闪记 →
本地上传队列 → Server 持久接收 → Worker 处理 → 知识列表、标题搜索与详情。
RAGFlow 是可选的服务端索引，不是保存、列表和标题搜索的前提。

唯一维护仓库：https://github.com/XingjianTian/PerClip 。旧历史与私人运维资料保留在
私有归档中；不要把旧分支或旧 `.git` 合并回本仓库。

## 本地开发

需要 Python 3.11+、uv；完整测试及提交检查需要 Gitleaks 8.25+。
Android 构建另需 JDK 17 和对应 Android SDK。

```sh
cp .env.example .env
chmod 600 .env
# 将 PERCLIP_INGEST_TOKEN 替换为本机生成的随机值，再按需填写地址与路径。
make setup
make privacy-setup
make api
# 另开一个终端，同一目录执行：
make worker
```

API 和 Worker 通过 `scripts/with_env.sh` 显式加载根目录 `.env`，不把 `.env`
当 Shell 脚本执行。数据目录相对仓库根目录解析。默认仅监听回环地址；如需其他设备
访问，请在私有配置中设置监听地址、实际 HTTPS 服务地址及网络访问控制。

Android 的设置页配置移动端 API 地址和 mobile ingest token。RAGFlow、ASR、embedding、
connector 的服务端密钥不能填进 Android，也不会编译进 APK。调试设备配置助手需由
操作者明确调用；本项目克隆、构建和测试不会自动修改手机配置。

环境变量、网关生成与部署边界见 [环境配置](docs/ENVIRONMENT.md)，API 与 Worker
合同见 [Server 说明](server/README.md)。系统服务模板中的标准路径是部署示例，实际
数据路径与凭证仍由私有环境文件提供。迁移源码不意味着生产服务已部署或完成验收。

## 验证

```sh
make test
cd android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

Server 测试使用隔离临时存储和模拟外部依赖。公开 URL 矩阵使用虚构标题、作者与
`.invalid` 地址；它验证离线合同，不证明真实平台采集成功。合成质量语料的来源与许可
见 [fixture licenses](tests/fixtures/quality/LICENSES.md)。历史 Stage 24/25 现场验收脚本及其依赖测试留在私有归档，不作为公开测试通过项。
旧的现场录屏、登录后信息流
样本、验收截图和生产记录没有随代码公开。

## 提交前隐私检查

新克隆需安装 Gitleaks，设置 GitHub noreply 邮箱，并运行 `make privacy-setup`。
`make privacy-check` 检查完整暂存内容、私有文件路径、本地敏感值和 Gitleaks 默认规则；
缺少扫描器会阻止提交。每台机器可在忽略的 `.privacy.local.json` 中配置自己的私人
字面量；不要把真实内容写入公共文档。详见 [隐私检查](docs/PRIVACY.md)。

模式扫描和 hooks 不能保证所有未来提交都没有隐私，请审阅文字、图片和二进制内容。
本次公开没有为项目自身代码擅自选择开源许可证；第三方依赖仍遵循各自许可证。
