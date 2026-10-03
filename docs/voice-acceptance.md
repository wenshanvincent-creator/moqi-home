# 语音层软件验收 · v0.4

对应完整方案第 7 节及第 8.2 节。先完成不依赖麦克风的软件，实际模型和音频链保留为明确的现场关卡。

## 当前实现

`moqi.voice.LocalCorrectionParser`：明确规则先解析；EdgeJev 仅回退解析预定义选项。模型独有的约束作为待 App 确认候选，不能直接写永久约束或放宽安全规则。拒绝缺字段、陌生设备、非法概率、NaN/Inf 和布尔概率；推理 RuntimeError 返回 unknown。

`moqi.speech_policy.reserve`：在播放前对实际音频时长和实时占用输入做确定性审查：

- 当地 23:00–07:00，所有语音禁止，包括主动播报和用户回答。
- 房间必须在配置内；可靠占用为 True，观察不早于 60 秒，也不能来自未来。普通运动传感器不能独自提供这种占用证明。60 秒新鲜度是工程参数，实机需核验。
- 主动语音只接受 new_habit 或 safety，每户每天最多两次。
- 新习惯只在首次 acknowledged 执行后 60 秒内可播报一次；不以影子预测冒充执行。60 秒窗口是工程参数。
- explanation / memory_changes / correction / question 只在已确认的用户会话内播放；问题每天最多一个。
- 传入在内存中合成后测量的音频时长，必须大于零且不超过八秒；不能用字数假装实测。
- SQLite 独立连接取得写锁后原子检查/预留次数；重启、重复请求和时钟后退不能绕过计数。拒绝未提交的观察事务。
- 预留后播放失败仍占用次数，这是保守工程选择，避免崩溃重试重复打扰。计数不随记忆回滚重置。
- 仅保存请求 ID、时刻、房间、类型、习惯 ID、时长；不保存音频或说话文本。它不生成设备执行许可。

此模块是播放前策略接口，尚未接入音频播放器；目前软件不会发声。可靠会话检测和占用适配器也需实际输入。

## 开发机离线测试

```bash
python -m unittest discover -s tests -p test_voice.py -v
python -m unittest discover -s tests -p test_speech_policy.py -v
python -m unittest discover -s tests -v
```

伪模型只测试接口和故障响应，不证明 EdgeJev 的中文分类准确率。

## 真实 EdgeJev 模型关卡

需要作者 EdgeJev runtime 和本地模型目录中的 model.onnx、tokenizer.json、edgejev.json。
作者构建流程见 https://github.com/yzfly/edgejev 。构建需下载权重并安装构建依赖；运行只需部署转换后的模型和运行库。当前源代码包没有包含这些内容。

Python 3.11+ 且已安装运行库的环境下，示例命令如下；路径是示例，要替换为实际模型位置：

```bash
python -m moqi.voice_benchmark --model /path/to/jev-int8 --output data/voice-report-01.json
```

不直接用 Ubuntu 22.04 默认 Python 执行项目；部署工具容器提供 Python 3.13，但默认镜像尚不安装 optional EdgeJev runtime。

报告包含 12 条固定中文文本、预期字段、每次结果、通过数量、加载时长、首次调用及重复调用中位/最大耗时。分别标出模型参与的样本，避免把规则耗时当模型速度。固定小样本是接受检查，不是方案第 11.3 节真实家庭数据的校准或五引擎对照实验。

输出文件必须是新文件；缺模型会写 status=blocked，不会制造通过率。不会连接 HA 或控制设备。

## 仍未完成

中文唤醒词 → Silero VAD → SenseVoice-Small INT8 → 文本解析 → sherpa-onnx 中文 TTS；内存音频处理、用户会话、打断、USB 硬件回声消除和 ITX 实测延迟仍待接入。3.7G 实际内存上的共存峰值也待实测，当前不声称完整语音已可用。

方案的高风险永远播报与夜间静默仍有冲突，独立安全审查仍拒绝学习产生的夜间动作。每日两次主动预算也不能保证每个安全事件都有语音；当前没有自动执行器，不绕过预算或静默时段执行需要强制播报的动作。进入真实执行前必须明确这两个策略之间的优先关系。
