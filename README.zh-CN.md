# 默契 Moqi

**面向智能家居 Agent 的可审计记忆与学习框架。**

[English](README.md) · [架构与接口](docs/framework.md) · [Playground](docs/playground.md) · [贡献指南](CONTRIBUTING.md)

系统从能观测、能归因的行为中学习家庭习惯，保留每条理解背后的证据。住户可以纠正、限制动作，或恢复以前的理解；恢复记忆不会删掉已经发生的事情。

目前是 **初期开发者预览版，尚未到 1.0**。没有开放真实设备执行；家庭数据、节能效果、模型准确率和工控机性能仍待验收。许可证尚未确定，当前没有附带开源许可授权。

## 先体验，不用硬件

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
- 独立确定性安全审查、持久化说话预算；不发送控制命令。

四次已验证行为只能形成候选，不等于允许执行。未知动作不当作人操作；人体传感器停止触发不能证明无人。安全规则不由模型置信度放宽。

## 接入自己的设备

使用 `HomeMemory` 与 `Observation`，参照 [Python 示例](examples/adapter.py) 和 [JSON 格式](examples/observation.json)。已有 Home Assistant 只读 WebSocket 适配器；其他协议可提供同样的状态、证据和连接覆盖。

归因为 human 的动作必须有证据，断档必须保留。框架无法替贡献者验证物理按钮是否真的被按下。没有硬件也可先贡献接口测试；有设备后再附去掉隐私的验收记录。

## EdgeJev 的位置

它用于语言到类型化纠正；时间、数值、习惯置信度和安全判断由结构化代码处理。模型独有的解释目前只是待确认候选。浏览器没有模型，不会用预设回答伪装推理。

有运行库和本地模型后执行：

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report.json
```

模型按作者 [EdgeJev 文档](https://github.com/yzfly/edgejev) 准备，不包含在仓库中。小样本文本验收不能代替家庭校准和五引擎对照实验。

## 验收与限制

```bash
python -m unittest discover -s tests -v
```

CI 配置已准备，尚无 GitHub CI 运行结果。完整音频链、真实硬件、实际模型推理与性能、节能实验未验收；静默和播报预算仍与强制播报有冲突。

浏览器输入只在本机会话处理；运行库从 CDN 下载。重新加载清空沙盒，本地部署才持久保存 SQLite 与 Git。公开仓库不包含住户数据库、令牌、密码、音频或权重。
