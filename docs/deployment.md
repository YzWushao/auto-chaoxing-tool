# Linux 虚拟机部署

后端仍为 Python / Waitress，网页与 API 由同一个站点提供。建议在独立虚拟机使用系统 Python 的 venv、systemd 与 HTTPS 反向代理；项目不要求安装 Docker。`deploy/` 提供服务、环境文件和 Nginx 示例，不包含实际服务器地址、密钥或部署数据。

## 路径与运行用户

- `/opt/auto-chaoxing-tool`：代码与 `.venv`；独立 systemd 部署可由管理员安装并让服务用户只读。宝塔会按项目运行用户调整目录所有权。
- `autochaoxing`：无交互式登录的服务用户。
- `/var/lib/auto-chaoxing-tool`：SQLite、加密密钥和任务目录，只有服务用户及管理员访问。
- `/etc/auto-chaoxing-tool/environment`：部署环境变量，参考 `deploy/environment.example`。
- `/etc/systemd/system/auto-chaoxing-tool.service`：参考 `deploy/systemd/auto-chaoxing-tool.service`。

安装 Python venv、Git、CA 证书等系统依赖后，将源码放到代码目录，在目录中创建 venv 并安装根目录 `requirements.txt`。服务用户不需要 sudo。安装环境文件、创建并授权数据目录后，运行 `systemctl daemon-reload` 和 `systemctl enable --now auto-chaoxing-tool`。

服务仅监听 `127.0.0.1:8765`。使用 `curl http://127.0.0.1:8765/api/health` 检查健康状态；使用 `systemctl status auto-chaoxing-tool` 和 `journalctl -u auto-chaoxing-tool` 检查进程与日志。健康接口不代表超星会话、NapCat 或真实签到已经验证成功。

## 使用宝塔管理项目

如使用宝塔，应由宝塔的“网站 → Python 项目”统一管理项目启动和依赖，不再同时启用上面的 systemd 项目服务。宝塔面板自身的 Python 与项目 Python 是两套环境；不要把项目 requirements 安装到面板自身环境。

已有 `/opt/auto-chaoxing-tool/.venv` 可以先检查后复用。项目目录指定 `/opt/auto-chaoxing-tool`，项目解释器明确指定该 venv 的 `bin/python`，启动方式使用自定义命令运行 `run.py`；`deploy/baota-start.sh` 提供相应启动包装。运行用户设为 `autochaoxing`，环境文件为 `root:autochaoxing`、0640，以便包装脚本读取。模块安装界面也必须使用项目同一解释器。

部分面板版本只允许选择 UID 不小于 1000 的项目用户。创建独立普通用户即可，保持密码锁定、无交互式 shell，不需要授予 sudo。面板安装与启动时使用正常的 `umask 022`；私密安装日志单独设为 0600，避免面板继承 `umask 077` 后生成运行用户无法进入的启动目录。数据目录仍保持 0700、数据库和加密密钥保持 0600。

安装完成后使用项目解释器执行 `python -m pip check`。面板可能自动附加 WSGI / ASGI 服务器及其依赖，应按项目 requirements 的约束解决冲突。部分面板版本会将 requirements 的范围约束误当作固定版本；复用环境时可先按根目录 requirements 正常安装、验证，再用 `python -m pip freeze` 生成部署专用锁定文件供面板读取。更新后重新生成该文件，实际部署锁定文件保存在服务器配置目录。

保留单个后台进程，由现有 Waitress 处理线程并发。现有 `run.py` 同时负责启动 NapCat 和注册任务退出处理；仅让通用 WSGI 启动器导入 Flask 工厂，不等于完整运行了这些服务。多个独立后台进程也会产生各自的任务与 NapCat 管理器，因此不应直接改成多 worker 部署。

在宝塔为项目绑定域名并建立反向代理，后端保持 `127.0.0.1:8765`。外部 SSL 监听端口可设为 8443，再由网关映射所需外网端口。面板管理端口与项目端口应单独映射。证书由面板管理时，以面板实际证书路径为准；下方 Nginx 示例使用独立证书路径，不能同时作为第二套站点重复监听。

面板的自动配置生成器通常按 443 添加 SSL 监听和强制跳转。使用非标准 HTTPS 端口时，保存域名、证书或映射设置后，应重新检查 Nginx 实际监听端口和跳转地址。仅监听 TLS 的 8443 站点无需额外开启按 443 判断的强制 HTTPS 跳转。临时自签名证书只用于部署检查，正式浏览器使用前应在面板替换为受信任证书。

如果面板自身通过 HTTP 访问，并在使用代理的浏览器中出现登录后 404，可检查是否收到绝对形式的 HTTP 请求目标，或包含 `/http://主机/路径` 的异常 URI。可以让 Nginx 保留原外部管理端口，将面板服务放到另一内部端口，统一转发为普通路径；保留原始 Host，正确传递客户端地址，并配置 WebSocket Upgrade 供终端使用。面板仍使用原账号密码和安全入口。绑定内部地址、权限切换等面板兼容修复应单独备份，面板升级后重新验收。

## 不开放 80 / 443 的 HTTPS

HTTPS 可以监听非标准端口。示例 Nginx 只监听 8443；如路由器将公网 7959 转发到虚拟机 8443，用户访问 `https://tool.example.com:7959`。普通 DNS 记录不会替浏览器指定端口，直接访问时需要写出外网端口。

证书可以使用覆盖该域名的现有有效证书，或使用 [Let's Encrypt DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge) 验证申请。DNS-01 通过 DNS TXT 记录验证域名控制权，不依赖 Web 服务器的 80 / 443。HTTP-01 必须使用 80，TLS-ALPN-01 使用 443，因此不适用于这里的端口条件。

证书中的域名应匹配用户访问的域名，提供完整证书链。将证书、私钥分别安装到 Nginx 示例的路径，再运行 `nginx -t` 并启用 / 重载服务。更新证书后也需要重载 Nginx。自动续期取决于 DNS 提供商的 API 或现有证书同步流程；手动添加 TXT 并不等于已经实现自动续期。

将访问域名加入 `AUTO_CHAOXING_ALLOWED_HOSTS`，HTTPS 部署启用 `AUTO_CHAOXING_HTTPS=1`。Nginx 必须保留 `$http_host`，包括外网端口，避免外网非标准端口下的 Origin / CSRF 校验失败。端口转发需要使用 TCP 透传；上游若也终止 TLS，需要按实际代理层级保持同源 Host。HTTPS 验收应检查登录、Cookie、扫码摄像头、照片、地图和 JSON 导入导出，不能只查看健康接口。

## 迁移现有数据

先确认原实例没有正在运行的任务。SQLite 应在停服时复制，或使用 SQLite 的一致性备份接口；不能在写入时只复制主数据库而遗漏 WAL。数据库和 `secret.key` 必须配套迁移，否则已加密的超星 Cookies、API 与点位配置无法解密。会话迁移不保证平台继续接受原 Cookies，跨设备 / 出口变化后可能需要重新登录。

新服务应在迁移完成后再启动。原实例与新实例同时连接同一个 NapCat 或处理同一批任务可能产生重复操作，切换时只保留一个工作实例。迁移副本、密钥、证书、日志和数据库均不应进入 Git；备份目录权限应与数据目录相同。首次开放远程入口前，在设置页确认管理员凭据。

## 更新与回退

记录部署 Git 提交号，更新前备份完整数据目录，检查活动任务后停止服务。更新代码、安装依赖、启动服务并检查模型和 API。回退时将代码切回已记录的提交；若新版本更改数据库结构，须使用升级前的数据备份，不应盲目用旧代码打开已迁移的数据库。

模型文件随源码提供，Linux 同样优先加载原项目模型，CPU 不兼容时使用同权重 FP32 兼容文件；安装依赖后应实际检查模型状态。网络部署的源码提供义务见根目录 LICENSE、NOTICE 和模型目录说明；如修改部署版本，应更新页面源码入口。
