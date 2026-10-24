# 版权、引用与修改声明

`auto-chaoxing-tool` 是基于开源组件构建的整合项目。新增 Web 界面、账户与任务管理适配层由本项目维护，不能将内置上游代码表述为本项目独立原创。

新增代码 Copyright (c) 2026 YzWushao，按 GNU GPL version 3 授权。

## 复用：Samueli924/chaoxing

- 项目：[Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)
- 固定版本：[45d2106b16764231c2de2038fb042e71b23d878f](https://github.com/Samueli924/chaoxing/tree/45d2106b16764231c2de2038fb042e71b23d878f)
- 用途：直接复用刷课引擎、课程及任务解析、音视频进度上报、章节检测等处理与字体资源。
- 许可：GNU GPLv3。原代码、原有署名和许可证保留于 `vendor/chaoxing/`；根目录 `LICENSE` 为完整 GPLv3 正文。
- 修改日期：2026-10-23。资源路径适配独立工作目录；加入可选的已完成媒体解析和重看；新增 Web 侧的真实时间计时与周期上报适配。

## 借鉴：Yink-Design/chaoxing-sign-cli

- 项目：[Yink-Design/chaoxing-sign-cli](https://github.com/Yink-Design/chaoxing-sign-cli)
- 参考版本：[4084545e2f00e5297693776ac5c8fccc809c07ca](https://github.com/Yink-Design/chaoxing-sign-cli/tree/4084545e2f00e5297693776ac5c8fccc809c07ca)
- 用途：参考课程签到活动查询、签到类型与接口参数流程，并在新项目中进行 Python / HTTPS 会话适配。
- 原版权声明：Copyright (c) 2021 miaochenxi。
- 许可：MIT。完整版权和许可声明保留于 `licenses/chaoxing-sign-cli-MIT.txt`。
- 适配日期：2026-10-23。新增多账户会话隔离、全部有效活动筛选、活动归属与时效验证、结果检查。

## 组件：cozmo/jsQR

- 项目：[cozmo/jsQR](https://github.com/cozmo/jsQR)，npm 包 `jsqr@1.4.0`。
- 用途：浏览器 Web Worker 内的本地二维码图片识别；不向第三方发送图片。
- 许可：Apache License 2.0，原始发行文件未修改，完整许可证见 `licenses/jsqr-Apache-2.0.txt`。
- 集成日期：2026-10-24。

## 地图组件（2026-10-24）

- [Leaflet](https://github.com/Leaflet/Leaflet) 1.9.4：BSD-2-Clause，原始发行文件未修改，完整许可证见 `licenses/leaflet-BSD-2-Clause.txt`。
- [coordtransform](https://github.com/wandergis/coordtransform) 2.1.2：MIT，Copyright (c) 2015 记忆的残骸；原始发行文件未修改，完整许可证见 `licenses/coordtransform-MIT.txt`。
- 在线底图：© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)，数据遵循 ODbL；地图数据不随源码分发，遵守 OSM 瓦片服务政策。

更详细的文件级来源和修改清单见 `THIRD_PARTY.md`。软件按原样提供，不附带担保，具体条款以随附的许可证为准。网页“设置 → 开源来源与致谢”提供上述项目和许可正文的入口。
