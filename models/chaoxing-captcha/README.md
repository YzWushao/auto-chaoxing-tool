# 超星滑块模型与 CPU 兼容版本

来源：[aquamarine5/ChaoxingSignFaker](https://github.com/aquamarine5/ChaoxingSignFaker)，固定版本 [0346adf72dde1d3fea5600232c575ad2211641c3](https://github.com/aquamarine5/ChaoxingSignFaker/tree/0346adf72dde1d3fea5600232c575ad2211641c3)。原作者 aquamarine5 / Brainspark，原版权声明与 AGPL-3.0 正文见 `licenses/ChaoxingSignFaker-AGPL-3.0.txt`。

- `captcha.ort`：原项目 `app/src/main/assets/captcha.ort`，逐字节保留，5,716,040 字节。SHA-256：`ce9623e1f58b46bc5e7485dffc6449d36255af5e9e2d877bb4db94e8c8b21ee7`。
- `captcha-cpu.onnx`：本项目 2026-10-28 从上述文件生成的 CPU 兼容版本，10,720,337 字节。SHA-256：`e1c8930a83389e7f10d456944d37c007fb8d9fbfc26e8326a06f2ffc23e091a5`。原文件中的部分 FP16 MatMul 在 Windows CPU ONNX Runtime 1.31.1 上不可用，因此将原图内 FP16 常量、类型及 Cast 目标扩展为 FP32。保留同一组权重与网络结构，没有重新训练或替换为其他识别模型；浮点运算精度变化可能造成预测差异，不承诺与 Android 逐位相同。
- `build_cpu.py`：公开完整转换步骤，只接受上述原模型哈希；使用已安装 ONNX Runtime 提供的 MIT FlatBuffers schema 读取器。转换不访问网络、不使用图片或训练数据。
- 推理适配：`server/captcha_model.py`。参考原 [ChaoxingCaptchaPredictor.kt](https://github.com/aquamarine5/ChaoxingSignFaker/blob/0346adf72dde1d3fea5600232c575ad2211641c3/app/src/main/java/org/aquamarine5/brainspark/chaoxingsignfaker/api/ChaoxingCaptchaPredictor.kt)，保留左上对齐黑色方形补边、640×640 RGB、float32 / 255、NCHW 输入、0.25 评分阈值、0.45 NMS 和 4 像素偏移修正，增加输出形状、有限数及坐标边界检查。

运行时先尝试原始 ORT 文件；CPU 不支持时加载经过哈希校验的同权重兼容版本。模型缺失、校验失败、依赖缺失、低分或推理失败时回到人工滑块，不使用旧颜色规则假装模型识别。设置页显示实际模型状态及运行格式。最多自动向平台校验两次，只有平台返回有效 validate 才继续后续请求；本地预测不代表验证通过。

正常使用只需根目录 `requirements.txt`；首次加载不自动下载任何模型。重建兼容文件：

```powershell
python -m pip install -r models/chaoxing-captcha/requirements-build.txt
python models/chaoxing-captcha/build_cpu.py
```

上游公开的模型发行物为 ORT 文件；本项目不声称拥有其训练数据或训练源码，也不声称上述转换能重新训练模型。

本整合版本新增代码及模型适配按 AGPL-3.0 发布。刷课引擎保留原 GPL-3.0；其余第三方组件保留各自许可证。完整整合源码、原模型、转换脚本及运行说明可从 [auto-chaoxing-tool 源码仓库](https://github.com/YzWushao/auto-chaoxing-tool) 获取。部署修改版本时，请向网络用户提供正在运行版本的完整对应源码，并将页面源码链接更新为自己的版本。
