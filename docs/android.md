# Android 客户端

从 v0.11.0 开始，`android/` 提供独立 Android 客户端，支持 Android 8.0 及以上。

界面使用现有服务器控制台，原生底部导航为总览、刷课、签到、用户、设置。
签到中心中的摄像头扫码入口在 App 内自动使用 CameraX + 捆绑版 ML Kit QR 模型。
模型随 APK 安装，不依赖首次下载 Google Play 扫码模型。手机完成识别和描框，
仅把二维码文本或空心跳发送到当前服务器。多用户队列、并发、平台验证和签到请求由服务器执行。
普通浏览器沿用连续 JPEG 的服务器识别方案。

## 使用

1. 安装 APK，在原生登录页填写服务器地址、用户名、密码。地址需为自己部署的 HTTPS 地址，可带端口。
2. 可选勾选“记住我”保留登录会话及地址、用户名；不保存密码。不勾选时再次启动需重新登录。
   登录使用项目控制台管理员账号，成功后使用底部导航切换页面。
3. 在签到中心打开摄像头扫码，选择用户和可选预设点位，点击开始，允许相机权限。
4. 画面上方显示原生预览和二维码边框，下方显示服务器结果。支持点击对焦和双指缩放。
5. 停止、切换页面、切后台或退出会关闭相机；已经发出的平台请求仍可能返回结果。

右上角菜单可更改服务器、刷新、退出控制台，或粘贴当前服务器签发的 QQ 一次性扫码链接。
链接的单次领取、账号和活动范围、有效期及结果隔离仍在服务器验证。

本客户端不内置部署域名、管理员密码、超星 Cookie 或 NapCat 配置。
仅勾选记住我时将连接地址、用户名和会话保存在本机应用私有存储；禁用应用备份。
仅信任配置的 HTTPS 源，WebMessageListener 校验来源和主框架，且只接受控制台或扫码页面。
外部页面使用系统浏览器；文件访问和混合内容关闭，不忽略证书错误。

## 构建

需要 JDK 17、Apache Maven 3.10、Python 3.10+、Android SDK Platform 35、Build Tools 35.0.0 和 platform-tools。
首次构建需要联网从官方 Google Maven、Maven Central 下载依赖。

Windows 建议将工具放到项目主目录的同级 `android-toolchain/` 中：

```text
android-toolchain/
  jdk/bin/java.exe
  apache-maven-3.10.0/bin/mvn.cmd
  sdk/platforms/android-35/
  sdk/build-tools/35.0.0/
```

```powershell
./android/build.ps1 -ToolchainRoot 'D:/你的工具目录/android-toolchain'
```

脚本会把 Maven、Android、Java 用户缓存及临时目录放在指定工具目录；首次创建本地发布签名，
以后沿用该签名以支持覆盖安装。签名文件和随机密码存于该目录的 `signing/`，仅授权当前 Windows 用户。
请自行备份整个签名目录，不能提交到 GitHub。源码仓库不含签名密钥或构建缓存。

成功后产物在 `dist/auto-chaoxing-tool-0.11.0-release.apk`。
`android/pom.xml` 是唯一构建入口。Maven 解析官方 AAR / JAR 依赖，调用 `build_apk.py`：
使用官方 Manifest Merger 合并清单、AAPT2 编译资源并生成 R 类、javac 编译 Java、D8 转换 DEX，
最后用 zipalign 和 apksigner 对齐及签名。此流程不调用 Gradle。
可通过 `-PythonExecutable` 指定 Python 路径，构建脚本仅使用 Python 标准库。

扫码速度取决于相机、对焦、二维码尺寸和设备性能；签到结果仍受平台、会话与网络影响。
构建和自动检查不能替代安卓真机相机验证。

## 参考与许可

原生扫码交互参考 [ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker) 的
CameraX + ML Kit 方案，本模块使用 Java 重新实现，继续遵循本项目 AGPL-3.0 许可和现有引用声明。
相机与扫码库通过官方依赖使用，各自许可见对应库；ML Kit 不属于本项目 AGPL 代码。
