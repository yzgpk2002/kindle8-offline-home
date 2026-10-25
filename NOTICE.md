# 来源、许可与公开范围

本仓库公开的是本次设备改造的文档与项目自编适配源码。尚未为全部原创内容授予统一的额外开源许可；公开可读不等于任意再许可。第三方项目遵循各自许可证，不因这里的引用而改变。

## 参考项目

- [KT3 原始恢复入口讨论](https://www.mobileread.com/forums/showthread.php?t=327055)：板型原图来源。
- [Popcorn 硬件恢复教程](https://www.mobileread.com/forums/showthread.php?t=345655)：SDP 入口与机型区别。
- [KUAL Booklet](https://github.com/NiLuJe/KUAL_Booklet)：书库应用入口基础；不附其 JAR。
- [Google Bumble](https://github.com/google/bumble)：HFP/RFCOMM/SCO 协议实现；不附第三方运行库。
- [minimp3](https://github.com/lieff/minimp3)：MP3 解码依赖；包装源码中的 include 需自行取得上游头文件。
- [DeepSeek API 文档](https://api-docs.deepseek.com/)：待 Key 的文本接口配置。

原厂 Mesquite、LIPC、蓝牙服务和固件属于其权利人；仓库描述其调用和行为，不分发提取后的专有代码、库或固件。KUAL 变换工具只包含项目自己的变换逻辑，不包含上游 class 内容。

## 没有发布的内容

设备完整备份、引导分区、RAM 恢复镜像、SSH/蓝牙密钥、主机指纹清单、真实 API 配置、个人录音、书籍、浏览器账号数据、私人服务器信息、原始含身份的日志和整板标识照片。

`assets/homepage-device.png` 为本次项目的实际界面截图，已检查不含私人备忘或账号。本文提到的 Kindle、AirPods、QQ 音乐、DeepSeek 等名称用于说明测试对象，不表示官方支持或背书。

## 工程状态

这是单台设备的可审查研究快照，不附完整重建工具链或一键安装器。测试覆盖纯逻辑，不保证其他固件可用。文档中明确区分实测、推断、历史失败和待验证事项。
