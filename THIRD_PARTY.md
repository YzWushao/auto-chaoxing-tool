# 开源来源与改动

本项目明确声明复用及借鉴以下两个开源项目，感谢原作者及贡献者。原版权和许可证保留；完整声明见 [NOTICE.md](NOTICE.md)。以下修改日期均为 2026-10-23。

## Samueli924/chaoxing

- 来源：https://github.com/Samueli924/chaoxing
- 固定版本：`45d2106b16764231c2de2038fb042e71b23d878f`
- 许可证：GPL-3.0，保留在 `vendor/chaoxing/LICENSE` 与根目录 `LICENSE`。
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

- 来源：[高德开放平台](https://lbs.amap.com/api/javascript-api-v2/getting-started)。通过官方 `https://webapi.amap.com/maps` 按需加载 SDK，仓库不复制或再分发其 SDK / 底图，服务不因本项目 GPLv3 许可而变成开源组件；其使用须遵循高德的条款、额度及许可。
- `web/amap-frame.js` 使用官方 Map、Marker、Circle、Scale、ToolBar、PlaceSearch 接口。官方地图署名保留，不使用未公开瓦片接口、示例共享 Key 或他人 Key。
- 安全密钥按 [官方代理方式](https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode) 接入：`server/map_config.py` 只代理固定服务路径并注入服务器密钥，不向网页返回安全密钥。`web/amap-picker.js` 验证同源页面消息的来源和窗口，统一转换 GCJ-02 / WGS84 与现有点位兼容。
