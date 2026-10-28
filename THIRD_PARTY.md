# 开源来源与改动

本项目明确声明复用及借鉴以下开源项目，感谢原作者及贡献者。原版权和许可证保留；完整声明见 [NOTICE.md](NOTICE.md)。前两个项目的初次适配日期为 2026-10-23，其余日期单独注明。

## Samueli924/chaoxing

- 来源：https://github.com/Samueli924/chaoxing
- 固定版本：`45d2106b16764231c2de2038fb042e71b23d878f`
- 许可证：GPL-3.0，保留在 `vendor/chaoxing/LICENSE` 与 `licenses/chaoxing-GPL-3.0.txt`；该部分保持原许可。
- 源码：`vendor/chaoxing/`，由上述版本导出，随新项目一起提供，运行时不依赖子模块下载。
- 本地修改：`api/cxsecret_font.py` 的非打包资源路径改为引擎目录，支持分账户任务在独立工作目录运行。
- 本地修改：`api/decode.py` 与 `api/base.py` 新增可选的已完成媒体解析；默认 CLI 行为不变。
- 已完成卡片兼容：平台会移除已完成视频的 `job` 标记；重看模式同时绕过已通过过滤和非任务卡片过滤，保留视频。新增附件数量与解析数量日志用于排查。
- 本地修改：`main.py` 为 Web 的按时长模式增加已完成章节内媒体重看和重复卡片过滤；已完成章节的测验不会重交。
- 适配层：`server/worker.py` 使用内存 Cookies 与配置、结构化日志及网页输入桥接，按课程并行、课程内章节顺序处理，并重新读取平台章节进度确认完成状态。
- 计时适配：`server/media.py` 参考上游 `api/base.py` 的媒体上报接口；取消提前上报终点的探测，按真实经过时间推进位置，直到本轮计时结束才接受完成结果。

## Yink-Design/chaoxing-sign-cli

- 来源：https://github.com/Yink-Design/chaoxing-sign-cli
- 参考版本：`4084545e2f00e5297693776ac5c8fccc809c07ca`
- 许可证：MIT，保留于 `licenses/chaoxing-sign-cli-MIT.txt`。
- 参考内容：课程签到活动读取、签到类型与参数流程。新项目的 Python 签到适配器在 `server/chaoxing.py` 中实现，统一使用每账户的 HTTPS 会话，并检查活动归属、时效与平台成功响应。

新项目没有依赖上述仓库的 Git 历史，也没有复制之前独立 GUI / EXE 草稿。上游作者与已有文件中的版权、许可证及其他来源声明保留原样。

## cozmo/jsQR（2026-10-24 集成）

- 来源：https://github.com/cozmo/jsQR；固定 npm 包 `jsqr@1.4.0`。
- 许可证：Apache-2.0，完整原文保留于 `licenses/jsqr-Apache-2.0.txt`。
- 原始发行文件 `dist/jsQR.js` 原样复制为 `web/vendor/jsqr-1.4.0.js`；SHA-256：`bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859`。
- npm 包 integrity：`sha512-dxLob7q65Xg2DvstYkRpkYtmKm2sPJ9oFhrhmudT1dZvNFFTlroai3AWSpLey/w5vMcLBXRgOJsbXpdN9HzU/A==`。
- 用途：`web/sign-qr-worker.js` 在浏览器本地解码图片；`web/sign-qr.js` 提取二维码内容、enc 和活动编号。不额外拦截活动编号不一致或疑似过期的二维码，提交后仍由后台 / 平台返回结果。

## Leaflet / coordtransform / OpenStreetMap（2026-10-24 集成）

- Leaflet 来源：https://github.com/Leaflet/Leaflet，固定 npm 包 `leaflet@1.9.4`，BSD-2-Clause。原始 `dist/leaflet.js`、`dist/leaflet.css` 和 `dist/images/` 原样复制到 `web/vendor/leaflet-1.9.4/`；许可证见 `licenses/leaflet-BSD-2-Clause.txt`。
- Leaflet JS SHA-256：`db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a`；CSS SHA-256：`a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6`。
- Leaflet npm integrity：`sha512-nxS1ynzJOmOlHp+iL3FyWqK89GtNL8U8rvlMOsQdTTssxZwCXh8N2NB3GDQOL+YR3XnWyZAxwQixURb+FA74PA==`。
- coordtransform 来源：https://github.com/wandergis/coordtransform，固定 npm 包 `coordtransform@2.1.2`，MIT，Copyright (c) 2015 记忆的残骸。原始 `index.js` 原样复制为 `web/vendor/coordtransform-2.1.2.js`；许可证见 `licenses/coordtransform-MIT.txt`。
- coordtransform JS SHA-256：`6037d92d149615c8557985ec5d025052dafda804cee8464b1e5ad7bf1915c89d`；npm integrity：`sha512-0xLJApBlrUP+clyLJWIaqg4GXE5JTbAJb5d/CDMqebIksAMMze8eAyO6YfHEIxWJ+c42mXoMHBzWTeUrG7RFhw==`。
- `web/sign-map.js` 封装地图选点与本地 WGS84 / GCJ-02 / BD-09 转换；GCJ 反向转换使用迭代逼近，不能据此承诺测量精度。默认 BD-09 沿用签到参考项目 README 的百度拾取流程，不代表平台永远要求该坐标系。
- 底图由 https://tile.openstreetmap.org 在线提供，数据版权 © OpenStreetMap contributors（[ODbL](https://www.openstreetmap.org/copyright)），不随仓库打包地图数据；显示可点击署名，遵守 [瓦片使用政策](https://operations.osmfoundation.org/policies/tiles/)。仅在用户展开地图时加载视野瓦片，不预抓取、不禁用缓存；跨站 Referer 仅发送站点来源，不含页面路径或查询串。
- 手动公开地名查询默认使用 [Nominatim Search API](https://nominatim.org/release-docs/latest/api/Search/)，遵守 [使用政策](https://operations.osmfoundation.org/policies/nominatim/)。独立后端请求、标识应用、全局串行限流（间隔 1.1 秒）、同词缓存 24 小时；无自动补全、批量查询、定时查询或逆地理编码。仅供本机小规模点位工具，部署者须负责合规及总流量限制；环境变量可替换 / 关闭服务，见 README。

## 可选地图服务：高德 JS API 2.0（2026-10-24 接入）

- 来源：[高德开放平台](https://lbs.amap.com/api/javascript-api-v2/getting-started)。通过官方 `https://webapi.amap.com/maps` 按需加载 SDK，仓库不复制或再分发其 SDK / 底图，服务不因本项目开源许可而变成开源组件；其使用须遵循高德的条款、额度及许可。
- `web/amap-frame.js` 使用官方 Map、Marker、Circle、Scale、ToolBar、PlaceSearch 接口。官方地图署名保留，不使用未公开瓦片接口、示例共享 Key 或他人 Key。
- 安全密钥按 [官方代理方式](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode) 接入：`server/map_config.py` 只代理固定服务路径并注入服务器密钥，不向网页返回安全密钥。`web/amap-picker.js` 验证同源页面消息的来源和窗口，统一转换 GCJ-02 / WGS84 与现有点位兼容。

## QQ 签到运行时依赖（2026-10-27）

- NapCat / OneBot 11：[NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ)、[网络配置](https://napneko.github.io/config/basic)。只对接已部署的服务，不复制、捆绑或再分发 NapCat 程序；按 OneBot 11 消息段与 echo 协议实现私聊会话。
- [python-websockets/websockets](https://github.com/python-websockets/websockets)，BSD-3-Clause，使用同步 WebSocket 客户端；由 requirements 安装，不将第三方源码复制进仓库。
- [zxing-cpp/zxing-cpp](https://github.com/zxing-cpp/zxing-cpp)，Apache-2.0，使用 Python 绑定在本机解码 QQ 上传的二维码图片；[Pillow](https://github.com/python-pillow/Pillow)，用于读取和缩放图片，许可依所安装发行包为准（本机验证 12.3.0 为 MIT-CMU；旧版本亦有 HPND / Pillow 许可声明）。均为单独安装的运行时依赖，原发行包内许可证保留。
- `server/sign_coordinates.py` 是既有 coordtransform 公式的 Python 适配，保留 Copyright (c) 2015 记忆的残骸 与 MIT 声明（`licenses/coordtransform-MIT.txt`）；不修改原始第三方 JS。

## 群聊与图片协议调研（2026-10-27）

- 图片流按 NapCat 的[文件处理文档](https://napneko.github.io/develop/file)实现 `download_file_stream`，只使用已收到图片的文件标识、分片大小与 echo；独立实现有界分片重组与 PNG 归一化，不复制 NapCat 实现。
- 群组接口参考环信的[群组 REST 文档](https://doc.easemob.com/document/server-side/group_obtain_detail.html)；旧服务停用及消息接口迁移参考协议维护者的[公开说明](https://github.com/aquamarine5/ChaoxingSignFaker/issues/188)。`server/group_sign.py` 是根据请求字段与实测响应独立编写的 Python 适配，只提取签到附件 JSON；没有复制 protobuf 定义或 Android 组件。后续 v0.7.0 直接复用了该项目模型，许可调整见下文。

## 摄像头连续扫码交互参考（2026-10-27）

- 参考项目：[aquamarine5/ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker)，查阅版本 `0346adf72dde1d3fea5600232c575ad2211641c3`，原项目按 AGPL-3.0 发布。参考范围为摄像头连续识别、多账户处理交互以及 URL / `SIGNIN:` 二维码字段约定，感谢作者与贡献者。
- 网页实现 `web/camera-sign.js`、队列 `web/camera-queue.js` 和请求适配 `server/camera_sign.py` 独立编写；沿用已有 jsQR 发行文件及其 Apache-2.0 声明，没有复制原项目的 Kotlin、Android 组件、图片资源或签到实现，不随项目捆绑该 APK。
- 浏览器摄像头采用标准 [MediaDevices.getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)，只请求视频；画面在浏览器 Worker 内处理，不上传第三方。

## 签到校验与验证协议参考（2026-10-28）

- 继续查阅上述 ChaoxingSignFaker 版本中的预签到、analysis / analysis2、活动要求字段、滑块 HTTP 请求 / 响应格式与 enc2 / validate 后续流程。`server/sign_protocol.py`、`server/sign_captcha.py` 和网页验证交互是 Python / 浏览器实现；v0.6.0 使用颜色区域规则，v0.7.0 按用户要求改为原项目模型推理，来源与改动见下文。
- 人工验证图片为超星验证服务当次生成的临时内容，不随仓库再分发；测试拼图由本项目生成，不使用第三方图片。补光 / 变焦使用浏览器标准 [getCapabilities](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getCapabilities) 与 [applyConstraints](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/applyConstraints)，不捆绑第三方 SDK。

## 签退与照片上下文（2026-10-28）

- 继续参考上述版本的活动关联字段、超星云盘上传字段与照片验证上下文接口。`server/sign_details.py`、`server/sign_faces.py` 与 `web/sign-face.js` 独立实现，未复制 Android 照片组件、已登记肖像提取逻辑、图像变换或官方设备证明生成代码。模型单独按下述来源引入。
- 本项目只提交用户确认的当前照片，不将拍照等同于活体成功；人脸匹配及最终出勤结果由超星确认。离线 UI 与测试图片由本项目生成，不使用真实肖像。

## 直接复用 ChaoxingSignFaker 模型（v0.7.0，2026-10-28）

- 版权：Copyright (c) 2026 aquamarine5 / Brainspark。固定来源版本仍为 `0346adf72dde1d3fea5600232c575ad2211641c3`；许可证 AGPL-3.0，完整原文保留于 `licenses/ChaoxingSignFaker-AGPL-3.0.txt`。
- `models/chaoxing-captcha/captcha.ort` 从上游 `app/src/main/assets/captcha.ort` 原样复制。Python 推理适配 `server/captcha_model.py` 依据上游 `ChaoxingCaptchaPredictor.kt`，保留预处理、阈值、NMS 和偏移规则。
- 部分 CPU 不支持原模型 FP16 MatMul。`captcha-cpu.onnx` 由公开的 `build_cpu.py` 将同一权重与图中的 FP16 扩展为 FP32，不重新训练，不替换其他模型；数值结果不承诺与 Android 逐位相同。文件哈希、构建依赖和具体步骤见 [模型说明](models/chaoxing-captcha/README.md)。
- 运行时依赖 [ONNX Runtime](https://github.com/microsoft/onnxruntime)（MIT）、[NumPy](https://github.com/numpy/numpy)（BSD-3-Clause），由 requirements 安装，保留发行包自带许可证；ONNX 仅用于重建兼容模型，不是正常运行依赖。
- 新增代码与模型适配随整合项目按 AGPL-3.0 发布，根目录 `LICENSE` 更新为 AGPLv3；GPLv3 刷课引擎保留原许可及其完整正文。网页提供无需登录的源码与许可入口；部署者修改版本后须同步更新为所运行版本的对应源码。
