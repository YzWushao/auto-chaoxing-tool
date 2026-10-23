# 开源来源与改动

## Samueli924/chaoxing

- 来源：https://github.com/Samueli924/chaoxing
- 固定版本：`45d2106b16764231c2de2038fb042e71b23d878f`
- 许可证：GPL-3.0，保留在 `vendor/chaoxing/LICENSE` 与根目录 `LICENSE`。
- 源码：`vendor/chaoxing/`，由上述版本导出，随新项目一起提供，运行时不依赖子模块下载。
- 本地修改：`api/cxsecret_font.py` 的非打包资源路径改为引擎目录，支持分账户任务在独立工作目录运行。
- 适配层：`server/worker.py` 使用内存 Cookies 与配置、结构化日志及网页输入桥接，按课程并行、课程内章节顺序处理，并重新读取平台章节进度确认完成状态。

## Yink-Design/chaoxing-sign-cli

- 来源：https://github.com/Yink-Design/chaoxing-sign-cli
- 参考版本：`4084545e2f00e5297693776ac5c8fccc809c07ca`
- 许可证：MIT，保留于 `licenses/chaoxing-sign-cli-MIT.txt`。
- 参考内容：课程签到活动读取、签到类型与参数流程。新项目的 Python 签到适配器在 `server/chaoxing.py` 中实现，统一使用每账户的 HTTPS 会话，并检查活动归属、时效与平台成功响应。

新项目没有依赖上述仓库的 Git 历史，也没有复制之前独立 GUI / EXE 草稿。上游作者与已有文件中的版权、许可证及其他来源声明保留原样。
