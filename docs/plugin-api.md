# 开放 API / QQ 机器人插件（v0.16.0）

机器人插件负责 QQ 白名单、自然语言理解和用户交互，本系统负责账户、课程、签到、刷课及配置操作。使用独立 Bearer API Key 调用 `/api/v1`，不需要模拟浏览器登录，不需要 CSRF；原有网页和安卓登录方式不变。

## 配置

1. 管理员进入网页“设置 → 开放 API · 机器人插件”，启用 API。
2. 创建一个具名密钥，选择操作权限、有效期（1～365 天，默认 90）和每分钟请求上限（10～6000，默认 600）。默认只选读取与签到；需要其他功能时明确勾选相应权限。
3. 立即复制密钥，它仅显示一次，服务端只保存 SHA-256 摘要。把项目根地址和密钥配置在机器人插件的私密设置中。
4. 每次请求携带 `Authorization: Bearer <API Key>`；JSON 写操作另带 `Content-Type: application/json`。远程使用 HTTPS，开发机 localhost 可以 HTTP。不要将 Key 放进 URL、QQ 回复、模型提示词、公开配置或仓库。

API 默认关闭。关闭开关立即阻止所有 Key，重新开启后未过期、未撤销的 Key 可继续使用。撤销 Key 或更改管理员名称/密码后旧 Key 失效；改管理员凭据仍必须提供当前密码。API Key 的创建、撤销和总开关只允许通过管理员网页会话管理，API 不能给自己扩权或生成新密钥。浏览器登录/退出不属于插件业务操作，API 身份通过 `/me` 检查。

每个 Key 的管理范围与创建它的控制台管理员相同，可以操作该控制台管理的全部超星账户。API 的 `read` 权限包含用户显示昵称、账户 ID、脱敏配置、点位坐标、设备码、任务及日志；请按实际用途授权。API 不提供原始平台 Cookies、管理员密码、已有 API Key 原文或已保存的第三方密钥。网页、QQ 共用全局昵称设置。

## 权限

| scope | 可用操作 |
| --- | --- |
| `read` | 用户、课程、活动、任务、日志、点位及脱敏设置查询；地图搜索和地址查询 |
| `sign:write` | 签到、签退、平台验证、本人照片、二维码识别队列；为已授权 QQ 获取扫码验证码 |
| `study:write` | 目标课程及刷课配置、启动/停止刷课、任务交互输入 |
| `accounts:write` | 手机号/密码或扫码添加、重新登录、删除超星账户 |
| `settings:write` | 全局题库、设备码、显示、扫码、地图、学校点位、NapCat/模型配置与连接测试 |
| `admin:write` | 修改管理员凭据，仍需当前管理员密码，并撤销全部会话与 Key |

开始扫码、上传画面/识别内容、查看及停止扫码队列均需要 `sign:write`。扫码队列和超星登录二维码按 API Key 隔离，另一 Key 或网页登录不能接管。撤销 Key、关闭 API、过期或改密后后台扫码队列会检查到授权失效并结束；已经发往平台的请求无法撤回。刷课任务与网页相同，启动后独立运行，撤销 Key 不会中断已有刷课任务，仍可在网页停止。

## 接口发现与模型工具

- `GET /api/v1/me`：Key 名称、权限、到期时间与限流配置。
- `GET /api/v1/openapi.json`：仅列出当前 Key 允许调用的 [OpenAPI 3.1 文档](https://spec.openapis.org/oas/v3.1.0.html)。
- `GET /api/v1/tools`：相同权限范围内的 Chat Completions function tools，包含 `name`、`description`、`parameters`。参数分成 `path`、`query`、`body`；JPEG 二进制上传不作为文本模型工具。
- 设置页可以下载完整 OpenAPI 和工具定义，文档只使用相对路径，不包含实际部署地址或凭据。

所有业务接口与网页使用相同处理函数、参数验证和用户归属检查。OpenAPI 为完整的操作清单和请求参数契约；返回 JSON 沿用网页结构。可先查询用户/活动，再调用明确的用户 ID、活动 ID，不能把自然语言直接当作接口路径或请求体。

| 功能 | 常用方法与路径（以 `/api/v1` 为前缀） |
| --- | --- |
| 初始化、用户 | `GET /bootstrap`、`GET /accounts`、`GET /accounts/{account_id}` |
| 超星登录 | `POST /auth/password`；`POST /auth/qr` → `POST /auth/qr/{token}/poll` / `cancel` |
| 课程与配置 | `GET /accounts/{account_id}/courses`；`PUT /accounts/{account_id}/config` |
| 刷课任务 | `POST /accounts/{account_id}/study`；`GET /jobs`；`GET /jobs/{job_id}/logs?after=0`；`POST /jobs/{job_id}/stop` / `input` |
| 签到与签退 | `GET /accounts/{account_id}/activities?source=course`；`POST /accounts/{account_id}/sign` |
| 要求、签退阶段、核对 | `GET /accounts/{account_id}/activities/{activity_id}/requirements`；`POST …/related`（`relation: in/out`）及 `…/confirm` |
| 平台验证、照片 | `POST /accounts/{account_id}/verification/{nonce}`（`action: check/refresh/cancel`，检查时带 `x`）；`POST /accounts/{account_id}/face` 及 `/face/{nonce}/cancel` |
| 直接扫码 | `POST /accounts/{account_id}/camera-sign`，传已解码的 `qr` 和可选学校点位 |
| 连续扫码 | `POST /camera-stream`；`GET /camera-stream/{run_id}`；`POST …/frame` / `…/qr` / `…/stop` |
| QQ 网页扫码入口 | `POST /scan-entry`（`qq` 为已授权号码字符串），返回 `url`、8 位数字 `code`、`expires_in`，由插件发送给该用户 |
| 全局配置 | `GET/PUT /settings`、`GET/PUT /preferences`、`GET /devices`、`PUT /devices/global`、`PUT /accounts/{account_id}/device` |
| 学校点位 | `GET/POST /location-presets`、`GET /location-presets/export`、`PUT/DELETE /location-presets/school` / `point` |
| 地图 | `GET/PUT /map/settings`；`POST /map/search` / `reverse`；可选地图 JS 参数 `GET /map/runtime` 需要 `settings:write` |
| NapCat/模型 | `GET/PUT /napcat/settings`；`POST /napcat/test`、`POST /napcat/intent/test` |
| 管理凭据 | `PUT /admin/credentials` |

普通/位置/手势/签到码/照片签到沿用当前平台条件；二维码提交需有效参数。签退使用独立活动 ID，可先通过 requirements/related 获取，不把“签到成功”等同于签退。平台验证码与人脸流程沿用现有实现，仍需官方处理的验证会明确报错。群聊签到已取消，API 同样不支持。

位置签到可以只提供 `location_preset: {"school":"学校名","name":"点位名"}`，服务器读取实际点位、转换为 BD-09，并使用父级“学校位置”上报；不采用客户端伪造的点位说明。手动经纬度仍按网页协议提供。学校点位 JSON 的坐标系为 `wgs84`、`gcj02`、`bd09`。

## 调用示例

示例地址为占位符，请从插件的安全配置读取实际地址和 Key。先查询账户及活动，不要从模糊姓名猜测内部 ID：

```http
GET /api/v1/accounts HTTP/1.1
Authorization: Bearer <API Key>
```

```http
GET /api/v1/accounts/<account_id>/activities?source=course HTTP/1.1
Authorization: Bearer <API Key>
```

对用户明确选择的活动提交签到：

```http
POST /api/v1/accounts/<account_id>/sign HTTP/1.1
Authorization: Bearer <API Key>
Content-Type: application/json
Idempotency-Key: qq-message-123-tool-1

{"activity_id":"<activity_id>","source":"course"}
```

位置签到增加 `location_preset`，二维码签到增加 `qr`。首次获取或过期后重新查询活动；接口不会自动假定某个用户参加了任意活动。

连续 JPEG 扫描：先 `POST /camera-stream`，JSON 为 `{"account_ids":["<id>"],"input":"jpeg"}`；获得 `id` 后向 `/camera-stream/{id}/frame` 发送 `Content-Type: image/jpeg` 二进制，每帧最多 768 KB、最大边 1920 像素。查询队列查看结果，结束时 `POST …/stop`。服务器保留最新一帧，仍受全局并发上限 5、采样间隔、账户锁和断流停止约束。API 不读取 QQ 机器人设备的摄像头；可由前端/设备上传，或通过 `/scan-entry` 请用户在网页扫描。

部署时使用新版 `deploy/nginx-https.conf.example` 的专用 frame location，它同时覆盖 `/api/camera-stream`、`/api/v1/camera-stream` 和 `/scan-api`，关闭请求落盘缓存，避免 API 上传画面走普通代理缓冲。

## 机器人插件的模型调用链

仓库提供 [Python 传输适配器](../examples/qq_api_client.py)，依赖现有 `requests`，不绑定 QQ 框架或模型供应商：

```python
from examples.qq_api_client import ChaoxingAPI

# 从插件私密配置读取；不要写入模型对话。
api = ChaoxingAPI(plugin_settings.server_url, plugin_settings.api_key)
tools = api.discover()
# 将 tools 和已授权用户的文字交给你选择的模型。
# 收到 function name + JSON arguments 后，插件验证 QQ 身份并执行：
result = api.call(tool_name, tool_arguments,
                  request_id=f"qq:{message_id}:tool:{tool_call_index}")
# 仅将完成用户交互所需的结果回复 QQ；不要回显配置、照片或密钥。
```

读取操作允许不传 `request_id`；写操作适配器要求插件提供稳定 ID。多个工具调用使用不同序号，重试同一次调用沿用同一 ID，避免自然语言模型重新推理后重复操作。适配器仅调用服务端发现且 Key 已授权的固定操作，不执行模型提供的任意网址/代码，不自动跟随重定向或重试。

推荐插件先验证发起 QQ 是否有权控制本系统；姓名重名、目标不明确时要求选择具体用户，删除账户、改变配置或批量操作先向发起者展示识别出的操作与目标。自然语言回复不是密钥，模型只负责形成结构化意图，HTTP 认证和权限判断由插件与服务端完成。本次提供 API/工具契约及适配器，不代替外部 QQ 框架的消息收发、模型配置或白名单实现；原 NapCat 指令流程保留。

## 去重、状态与日志

JSON 写操作可带 `Idempotency-Key`（1～128 位字母、数字或 `._:-`）。同一 Key 下，相同方法、路径、查询串和请求体在 24 小时内只执行一次；重试返回原始 JSON/状态码，带 `Idempotency-Replayed: true`。同一 ID 换参数返回 409。正在执行或进程中断而未确认结果也返回 409，先查询任务/活动结果，不自动重做。响应加密持久保存，原始请求体及去重 ID 不落盘；JPEG 帧不去重。无此请求头时使用原有网页行为。

每次响应带 `X-Request-ID`，设置页可查看最近 100 条调用记录；数据库最多保留 5000 条审计元数据。仅记录 Key ID、操作名、状态、时间、耗时和请求编号，不记录路径中的账户 ID、请求/响应正文、密码、QR 内容或模型原文。审计并不表示平台已确认成功，实际结果以操作响应和学习通记录为准。

常见状态：200 成功；201 创建 Key（仅控制台）；202 后台任务/画面已接收；400 参数错误；401 API 关闭或 Key 无效；403 权限不足；404 记录不存在/不属于当前范围；409 平台验证或请求去重冲突；422 平台需额外处理；429 限流（通常附 `Retry-After`）；502 平台请求未确认。网络断开或 5xx 后先查结果，避免用新 ID 盲目重复提交。与平台有关的原有限流仍会独立生效。
