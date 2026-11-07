# auto-chaoxing-tool

超星多账户 Web 控制台（初期开发快照）。管理员独立登录后，以手机号 / 密码或学习通扫码连接多个超星账户，集中管理**刷课**、**签到**和**配置**；另提供 Android 客户端、QQ（NapCat）私聊签到与开放 API。

**当前版本：** 后台 v0.19.1 / 安卓 v0.12.1 · [更新日志](CHANGELOG.md)

## 目录

- [快速开始](#快速开始)
- [功能概览](#功能概览)
- [配置说明](#配置说明)
- [数据与安全](#数据与安全)
- [部署](#部署)
- [文档索引](#文档索引)
- [测试](#测试)
- [当前限制与计划](#当前限制与计划)
- [开源来源与许可](#开源来源与许可)

## 快速开始

需要 Python 3.12 或更高版本。在项目目录执行：

**Windows（PowerShell）**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

浏览器访问 <http://127.0.0.1:8765>，`Ctrl+C` 停止服务。可用 `--host`、`--port` 修改监听地址，默认仅监听本机。

> [!WARNING]
> 首次登录使用默认管理员账号 **`admin` / `admin`**。请先在“设置 → 管理员账号与密码”中修改（新密码至少 8 位，保存后所有管理员会话失效），**不要用默认密码开放局域网或公网访问**。

- 关闭网页后后台任务仍会运行；关闭服务会停止任务，重启后中断的任务不会自动恢复。
- 管理员登录、添加 / 重新登录超星账户都使用小窗，可点右上角、取消按钮或 `Esc` 关闭。关闭超星窗口会停止二维码轮询，不影响已有后台任务。

## 功能概览

### 账户与控制台

- **管理员认证与超星身份分离**：管理员密码以 scrypt 哈希保存；会话令牌哈希存于 SQLite，30 天有效，支持退出撤销、改密后全部撤销。
- **超星登录**：支持手机号 + 密码、学习通扫码确认。超星密码只用于本次认证，**不保存**。
- **多账户**：每个账户独立保存 Cookies、目标课程、学习参数与题库 / API 设置，也可继承全局配置。
- **用户称呼**：手机尾号、姓氏＋星号、完整姓名、星号＋名字、姓氏＋尾号，网页与 QQ 共用，不改动平台真实姓名。
- **[设备码绑定](docs/device-codes.md)**：每个账户自动生成并沿用独立设备码，支持逐个绑定、统一设置、读取本浏览器标识或扫描分享二维码获取。
- **本地事件**：登录成功 / 失效、刷课结果、签到成功。

### 刷课

- 课程与班级分别选择，独立参数页；支持启动、停止、日志、进度和手动答题输入。每个账户一个独立工作进程。
- 复用内置刷课引擎，处理视频 / 音频、文档、阅读、章节检测等。并发单位为课程，同一课程内章节顺序执行。
- 视频计时规则见 [视频计时与观看时长](#视频计时与观看时长)，题库配置见 [题库](#题库)。

### 签到

| 类型 | 说明 |
| --- | --- |
| 普通 / 手势 / 签到码 | 读取有效课程活动后直接提交；手势按数字填写 |
| 二维码 | 手动填 enc；或选本地图片（PNG / JPEG / WebP，≤ 8 MB）在浏览器本地解码，图片不上传；或用摄像头连续扫码 |
| 位置 | 地图拾取坐标、预设点位或设备定位，详见 [位置与地图](#位置与地图) |
| 拍照 | 目前需已上传图片的 objectId，尚不支持网页直接上传 |
| 签退 / 本人照片 | 识别独立签退活动，支持本人拍摄确认发送；需官方活体 / 设备校验时可转官方完成 |

- **[多用户批量签到](docs/batch-sign.md)**：签到中心提供二维码、定位、手势 / 签到码、普通四个入口，可全选用户、刷新各自活动、选共同活动后一键提交，逐人查看结果、停止剩余任务或重试失败用户。
- **[摄像头连续扫码](docs/camera-sign.md)**：手机上传连续 JPEG，服务器用 ZXing-C++ 识别。可配置并发（1～20，默认 5）与识别间隔（默认 0.1 秒）；本轮第 11 次失败移到队尾，成功退出队列；支持 1×–5× 数字放大、相册选图、补光 / 变焦（视设备能力）。离开页面、切到后台或全部完成时释放摄像头。局域网 / P2P 访问需 HTTPS，本机 localhost 可直接使用。
- **[签到流程对齐](docs/sign-parity.md)**：活动要求、POST 预签到、analysis / analysis2、validate / enc2 后续提交。
- **滑块验证**：使用 ChaoxingSignFaker 原项目模型在本机识别，失败时回退手动滑块；平台确认通过后才继续，不保证全部自动通过。设置页可查看模型加载状态，详见 [模型说明](models/chaoxing-captcha/README.md)。
- 仅处理课程活动，群聊签到已于 v0.14.2 取消。
- [签退与本人照片](docs/signout-face.md)：仍不保证所有 Android 专用验证都能在网页完成。

### 位置与地图

- **地图选点**：放大地图后点击或拖动标记，回填 6 位小数经纬度；支持“使用地图中心”“按已填坐标定位”，可查询并回填地址说明。
- **设备定位**：“使用设备位置上报”全端可用。安卓优先原生定位；浏览器需 HTTPS（或本机 localhost）并在手动点击后才请求权限，显示误差半径。
- **坐标系**：默认回填百度 BD-09，可切换高德 / 腾讯 GCJ-02 或 WGS84。转换在本地执行，切换只转换地图选点，不改写手填值。
- **地图来源**：默认免费的 OpenStreetMap（无需 Key）；可在“设置 → 地图服务”配置[高德 Web 端（JS API）Key](docs/amap-setup.md)。高德安全密钥由后台代理注入，不下发浏览器；凭据加密保存，接口只返回掩码。
- **地点搜索**：使用 Nominatim 公共服务，仅在点击 / 回车时发送，不做自动补全或批量搜索；全局串行、间隔 ≥ 1.1 秒、缓存 24 小时。可用环境变量切换或关闭，见 [环境变量](#环境变量)。
- **预设点位**：学校（父级）→ 点位（子级）两层结构，数量不限。学校设置统一的“学校位置”文字用于上报；点位只保存名称、坐标、坐标系，加密存于 SQLite。支持增删改、JSON 导入 / 导出（单文件 ≤ 8 MB），格式见 `web/examples/location-presets.example.json`。保存、应用、导入都不会触发签到。

> [!NOTE]
> 公开转换算法、底图和定位都可能有误差，6 位小数不代表实地精度。请核对实际位置与位置说明，**不要用于伪造出勤**。免费地图与 Nominatim 需遵守 [OSM 瓦片政策](https://operations.osmfoundation.org/policies/tiles/) 与 [Nominatim 政策](https://operations.osmfoundation.org/policies/nominatim/)，公开部署应改用自有或商业服务。

### QQ 私聊签到（NapCat）

详见 [QQ 签到文档](docs/napcat-sign.md)。仅授权 QQ 可用，不开放控制台、账户凭据或刷课控制，不接收群指令；设置独立加密保存。

- 回复 **“签到”**：检查全部用户的签到信息，按涉及人数降序列出活动与昵称，不会自动签到。
- 回复 **“扫码签到”**：获取固定 `/scan` 地址和 8 位数字验证码（5 分钟有效，验证后绑定当前浏览器），网页里勾选用户后开始摄像头扫描。
- 支持多选用户 / 活动：`1,3,5`、`1-5`、`全选`。
- 可选**模型介入**：配置 OpenAI 兼容接口后，把口语回复匹配到当前会话（默认关闭，口语全选需确认）。

### 开放 API

见 [开放 API / QQ 机器人插件](docs/plugin-api.md)。默认关闭；开启后可创建按权限授权的独立 Bearer 密钥，`/api/v1` 覆盖全部网页业务操作，提供 OpenAPI、function tools 定义与 Python 插件适配器（示例 `examples/qq_api_client.py`）。

### Android 客户端

见 [安卓说明](docs/android.md)。支持 Android 8.0+，Maven 构建；CameraX + ML Kit 本机连续识别二维码（智能取景 / 手动倍率与对焦），原生定位，服务器端管理签到队列。连接服务器后可检查并安装新版 APK。客户端不预置部署地址或凭据。

## 配置说明

### 全局与账户配置

- “设置”中配置全局 API；“刷课中心 → 刷课参数”中为当前账户单独配置，或选择继承全局。
- 修改配置对**下一次新任务**生效。

### 题库

- 未配置时默认不启用题库；自动提交章节检测默认**关闭**。
- 多个题库用英文逗号组合按顺序回退，例如 `TikuHai,TikuManual`。
- **题库海 `TikuHai`**：可选“卡密”或“个人 API Key”，凭证分别加密保存。使用官方精确搜题接口，支持单选、多选、判断、填空，默认查询间隔 1 秒，按题库海规则计费。见 [题库海文档](https://search.tikuhai.com/docs)。
- **最低题库命中率**：填 0～100%，默认 90%。只填完整匹配的答案，未命中或有歧义的题留空，不随机猜测；低于阈值时只保存不提交。命中率不等于正确率。插件 API 的 `cover_rate` 仍用 0～1 比例字符串（如 `"0.9"`）。

### 视频计时与观看时长

默认“按时长学习”，并开启“从头计时，包含已完成的视频”，每个账户可在“刷课参数”中单独修改。

- 按单调时钟推进媒体位置，定期调用进度上报接口；平台提前返回任务点通过也不会提前结束计时。1 倍速时 20 分钟视频约需 20 分钟，2 倍速约 10 分钟。
- 重看已完成章节时只重看媒体，不重复提交已完成的章节测验；关闭“从头计时”则按平台已有位置续接。
- “仅完成任务点”保留上游的完成即跳过与快速完成逻辑，可能很快结束。
- 停止任务保留已记录进度，不会补满时间；未实际完成媒体计时的任务不会显示为全部成功。

> [!IMPORTANT]
> 后台计时使用进度接口，并非在浏览器中播放画面，**不等同于平台已入账的观看时长**，请在官方页面核对。

### 环境变量

| 变量 | 作用 |
| --- | --- |
| `AUTO_CHAOXING_DATA_DIR` | 数据目录，默认 `data/` |
| `AUTO_CHAOXING_ALLOWED_HOSTS` | 允许的主机名，逗号分隔 |
| `AUTO_CHAOXING_HTTPS` | HTTPS 反向代理部署时设为 `1` |
| `AUTO_CHAOXING_GEOCODER_URL` | 兼容 Nominatim 的 HTTPS 搜索服务；设为空可关闭地点搜索 |
| `AUTO_CHAOXING_REVERSE_GEOCODER_URL` | 选点地址查询（反向地理编码）服务 |
| `AUTO_CHAOXING_ANDROID_RELEASE_DIR` | 安卓更新包目录，默认 `releases/`，见 [安卓说明](docs/android.md) |

## 数据与安全

- 运行数据位于 `data/`：`console.sqlite3` 保存账户、加密的平台凭据、管理员密码哈希和会话令牌哈希；`secret.key` 是数据加密与 Cookie 签名密钥，**备份时必须一起保存**。
- Cookies、API 配置、地图凭据、预设点位均加密保存；点位 JSON 导出不含账号、Cookies 或 API 配置，但可能包含你保存的位置。
- **不要**把运行数据、密钥、数据库、Cookies、日志或个人配置提交到 GitHub。
- 升级前请先停止服务并备份完整 `data/` 目录；换代码后须**重启后端**才生效（刷新网页不够）。旧版工作空间会自动授权给本机管理员，原有账户、配置、任务与签到记录保持不变。

## 部署

默认面向本机使用，尚未完成公网多租户部署验收。

[Linux 虚拟机部署说明](docs/deployment.md) 介绍普通服务用户、数据迁移、开机自启，以及不开放 80 / 443 时的 HTTPS 配置；示例文件位于 `deploy/`（systemd、Nginx、环境变量、宝塔启动脚本）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/batch-sign.md](docs/batch-sign.md) | 多用户批量签到 |
| [docs/camera-sign.md](docs/camera-sign.md) | 服务器摄像头扫码签到 |
| [docs/sign-parity.md](docs/sign-parity.md) | 签到流程对齐（预签到、滑块、validate） |
| [docs/signout-face.md](docs/signout-face.md) | 签退与本人照片验证 |
| [docs/device-codes.md](docs/device-codes.md) | 设备码绑定 |
| [docs/napcat-sign.md](docs/napcat-sign.md) | QQ（NapCat）私聊签到 |
| [docs/plugin-api.md](docs/plugin-api.md) | 开放 API / QQ 机器人插件 |
| [docs/amap-setup.md](docs/amap-setup.md) | 高德 Key 申请与选点地址配置 |
| [docs/android.md](docs/android.md) | Android 客户端构建与发布 |
| [docs/deployment.md](docs/deployment.md) | Linux 虚拟机部署 |
| [models/chaoxing-captcha/README.md](models/chaoxing-captcha/README.md) | 滑块模型来源、哈希与重建 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |

## 测试

```bash
# Windows 将 .venv/bin/python 换成 .\.venv\Scripts\python.exe
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

- `tests/` 使用离线平台响应与子进程夹具，不会发起真实签到或刷课请求。
- 二维码回归测试使用 `qrcode` / Pillow 生成虚构二维码；装有 Node.js 时会额外运行 jsQR 解码测试（正常使用不需要 Node.js）。
- `python -m tests.preview`：离线页面预览（端口 8766），正式入口始终是 `run.py`。
- `python -m tests.make_sign_qr_fixtures --output work/qr-ui-fixtures`：生成离线验收用的二维码图片。

## 当前限制与计划

**限制**

- 真实登录二维码的获取与等待扫码已验证；尚未用真实账户完成整套刷课和所有签到类型的端到端验收。超星接口变化、验证码、二次验证或课程规则可能需要进一步适配。
- 网页拍照签到需已上传图片的 objectId，尚不支持直接上传图片。
- OCR 可按需安装 `ddddocr`；未安装时使用引擎的无 OCR 处理方式。

**计划**

- [x] NapCat：授权 QQ 私聊选择用户、选择课程活动、二维码图片识别与预设位置签到
- [ ] NapCat：辅助登录
- [ ] NapCat / 第三方推送：登录失效、刷课完成、签到结果通知
- [ ] 完整真实账户联调与更多签到流程适配
- [ ] 网页直接上传签到图片

## 开源来源与许可

本项目直接复用、借鉴以下开源项目，感谢原作者与贡献者：

| 项目 | 用途 | 许可 | 固定版本 |
| --- | --- | --- | --- |
| [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) | 刷课引擎与资源 | GPL-3.0 | `45d2106b16764231c2de2038fb042e71b23d878f` |
| [Yink-Design/chaoxing-sign-cli](https://github.com/Yink-Design/chaoxing-sign-cli) | 签到流程与参数参考（原版权 `Copyright (c) 2021 miaochenxi`） | MIT | `4084545e2f00e5297693776ac5c8fccc809c07ca` |
| [aquamarine5/ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker) | 连续扫码交互、验证协议参考；直接复用滑块模型并适配 Python 推理 | AGPL-3.0 | `0346adf72dde1d3fea5600232c575ad2211641c3` |
| [cozmo/jsQR](https://github.com/cozmo/jsQR) 1.4.0 | 浏览器本地二维码解码（未修改发行文件，随源码提供，不依赖 CDN） | Apache-2.0 | — |

- 自 v0.7.0 引入上述模型及推理适配后，整合项目新增代码按 **AGPL-3.0** 发布，见 [LICENSE](LICENSE)；内置刷课引擎保持 GPL-3.0（[原文](licenses/chaoxing-GPL-3.0.txt)），其他组件保留各自许可。
- 通过网络部署修改版本时，应向使用者提供运行版本的完整对应源码，并更新页面中的源码链接。
- [NOTICE.md](NOTICE.md) 为版权与引用声明，[THIRD_PARTY.md](THIRD_PARTY.md) 记录具体来源、用途与修改；网页“设置 → 开源来源与致谢”提供相同入口。
