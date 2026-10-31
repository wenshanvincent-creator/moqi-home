# 默契 Moqi

**面向智能家居 Agent 的可审计记忆与学习（Home Assistant）— 尚未到 1.0，默认影子模式。**

[![Core and package checks](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml/badge.svg)](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml)

[English](README.md) · [架构与接口](docs/framework.md) · [Playground](docs/playground.md) · [贡献指南](CONTRIBUTING.md)

系统从能观测、能归因的行为中学习家庭习惯，保留每条理解背后的证据。住户可以纠正、限制动作，或恢复以前的理解；恢复记忆不会删掉已经发生的事情。

目前是 **软件准备版本，尚未到 1.0**。整合运行器默认影子模式，HA 管理设备选择和最终执行边界；家庭数据、节能效果、模型准确率、实际音频和工控机性能仍待验收。许可证尚未确定，当前没有附带开源许可授权。

习惯来自 Home Assistant 观测和本地学习，不来自 EdgeJev。数值和时间先由确定性代码处理；可选的本地 EdgeJev 只处理代码无法解释的受支持语义。可选的夜间 DeepSeek 反思可以在每月估算 US$1 预算内提出后台更新，`reflection.enabled` 默认关闭。可选交互使用语音，23:00–07:00 完全静默，不要求住户在网页教学或批准普通习惯。显式打开执行且 HA 也选中设备时，当前实况派发只覆盖已获得信任的低风险灯；空调等其他设备可以学习和影子运行，不在此范围内自动执行。

## 两分钟试用

需要 Python 3.11 或更新版本。在本仓库检出目录：

```bash
python -m pip install -e .
python -m moqi.scenarios --directory data/software-replay-001
python -m tools.build_playground --output dist/playground/index.html
```

场景命令只回放按时序的合成行为，不连接模型、云、Home Assistant 或音频。打开 `dist/playground/index.html` 即可看录制走查，不需要服务器。只有在想用 Pyodide 于浏览器里跑同一学习核心时，才点 Start live sandbox（首次加载需要联网；浏览器兼容验收尚未完成）。

欢迎把一段 Playground 短 GIF 放在 `docs/media/playground.gif`。仓库里目前还没有这个文件。

可选的合成系统演示。请使用新目录，不要指向住户数据库：

```bash
python -m moqi.demo --output data/system-demo
```

## 先完成软件准备

```bash
python -m pip install -e .
python -m moqi.scenarios --directory data/software-replay-001
```

这会运行合成的按时序行为回放，不连接 HA、不运行模型或音频；信任和计数从行为流计算。继续查看[验收台账](docs/jev-memory-acceptance.md)、[软件接口](docs/software-preparation.md)、[Ubuntu 步骤](docs/ubuntu-software-install.md)和[服务器模型/音频准备](docs/model-and-audio-setup.md)。源码包不含 HA 镜像或模型权重。

## 开发者 Playground

```bash
python -m pip install -e .
python -m tools.build_playground --output dist/playground/index.html
```

打开生成的 HTML。Recorded walkthrough 展示同一真实引擎算出的十个模拟状态，不需要服务器。点击 Start live sandbox 则尝试用 Pyodide 在浏览器内运行 Python 和 SQLite，第一轮加载需要联网。浏览器兼容验收尚未完成，失败时会显示错误并保留有标签的回放。

你可以让模拟住户连续几天按时开灯、某天漏做、加入未知来源事件、模拟撤销，再输入 `不要自动开餐厅灯` 并恢复先前理解。界面展示证据、情境层级、信任和日记。所有数据均为 synthetic，不冒充真实住户。

## 已实现的机制

- SQLite 事件、情节、情境习惯、问题清单和世界模型。
- 情境暴露式遗忘、季节休眠、影子反馈、撤销/修正和信任升级。
- 可编辑 Markdown/YAML、独立 Git 记忆历史和回滚。
- 有界规则解析、可选本地 EdgeJev 适配和真实模型验收脚本。
- 独立确定性复核、HA 设备范围、执行 ID 预留及状态回读，默认影子运行。
- 完整条目的 JEV 上下文预算、后台候选验证/影子发布/回退、实际 token 和缓存账本。
- 内存中的唤醒/VAD/ASR/TTS 接口、语音确认和持久播报预算；真实音频待验。

四次已验证行为只能形成候选，不等于允许执行。未知动作不当作人操作；人体传感器停止触发不能证明无人。安全规则不由模型置信度放宽。

## 接入自己的设备

使用 `HomeMemory` 与 `Observation`，参照 [Python 示例](examples/adapter.py) 和 [JSON 格式](examples/observation.json)。HA 事件通过只读 WebSocket 采集，所选设备的执行由独立 HA 集成处理；其他协议可提供同样的状态、证据和连接覆盖。

归因为 human 的动作必须有证据，断档必须保留。框架无法替贡献者验证物理按钮是否真的被按下。没有硬件也可先贡献接口测试；有设备后再附去掉隐私的验收记录。

## EdgeJev 的位置

它用于语言到类型化纠正；时间、数值、习惯置信度和安全判断由结构化代码处理。模型独有的修改通过语音确认，普通行为学习无需教学。浏览器没有模型，不会用预设回答伪装推理。

有运行库和本地模型后执行：

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
```

模型按作者 [EdgeJev 文档](https://github.com/yzfly/edgejev) 准备，不包含在仓库中。小样本文本验收不能代替家庭校准和五引擎对照实验。

## 验收与限制

```bash
python -m unittest discover -s tests -v
```

托管工作流 [Core and package checks](https://github.com/wenshanvincent-creator/moqi-home/actions/workflows/tests.yml)（`.github/workflows/tests.yml`）已在 `main` 上成功运行，包括 2026-10-03 与 2026-10-22 的推送。它覆盖 Python 3.11–3.14、单元测试、Playground 构建和打包。页首徽章反映默认分支，不能代替后续提交或 pull request 自己的结果。真实硬件、实际模型/音频、性能和节能实验未验收。首播条件无法满足时保持影子；夜间静默和预算不能被强制播报绕过。

浏览器输入只在本机会话处理；运行库从 CDN 下载。重新加载清空沙盒，本地部署才持久保存 SQLite 与 Git。公开仓库不包含住户数据库、令牌、密码、音频或权重。
