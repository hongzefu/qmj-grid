# commit5 可复现记录

## 用户指令原文

> 在不修改`Q2_Agent.getAction(gameState)`这个封装的前提下 尽可能提高成功率
>
> 注意你可以跑两组 一组是明确使用 `-f` 固定 seed
> 另一组假设线上评测使用尽可能多的普适性的seed情况下 尽可能做到效果好
> 不要修改地图设置 在现有的12张上面优化
>
> 在你穷尽所有方案前不要停止 可以加入各种rule base对各个场景的规则 可以读源代码了解sim的交互设置
> 但是`Q2_Agent.getAction(gameState)`的输入输出不可以改动 只能拿现有已知信息 源代码了解sim的交互设置只能作为stong prior
> 因为只能在在现有的12张上面优化 20 个隐藏实例未知 因此要注意不要过拟合 要做到普适性

此前用户还要求把迭代结果写入报告；本次继续维护 `docs/q2-report.md`。

## 形式化计划

1. 审计当前代码、模拟器计分、ghost 采样、碰撞、scared timer、合法动作和整局 timeout。
2. 建立两组独立基准：课程 `-f` 固定 seed；预先确定的多个整数 seed。
3. 所有候选只修改 `commits/agents/q2Agent.py`，不修改地图、模拟器或 ghost。
4. 依次测试行为等价性能优化、fallback、maze distance、风险权重、胶囊、残局、expectimax 安全门、走廊、cycle guard、搜索深度和复杂度规则。
5. 每个候选先做小规模哨兵测试；出现已有胜图回归即提前停止并撤销。
6. 最终候选跑官方 evaluator、固定 seed 三次重复、10 seeds × 12 图泛化测试、Ruff、Python 3.9 和合法动作不变量。
7. 更新报告，记录所有成功、失败和主动中止，不选择性隐藏退化结果。
8. 每次文件变化后运行 `uv lock`；提交前检查修改范围、缓存、凭据和 private 远程。

## 权威模拟器事实

- food +10；最后一颗 food 另 +500 并 win；每次 Pac-Man 动作 -1。
- capsule 无直接分数，但令所有 ghost scared timer=40。
- 吃 scared ghost +200；active ghost 碰撞 -500 并 lose；碰撞阈值0.7。
- ghost 不能 STOP；非死路不能立即反向；scared ghost 速度0.5。
- 本地默认 RandomGhost 在合法动作间均匀采样。
- `--timeout=30` 是 Agent 整局累计计算时间，而非每回合30秒。

## 基准工具

使用 `/tmp/q2_benchmark.py` 临时脚本，不纳入仓库：

- 每个 case 创建新 Q2 Agent、重新设置 seed、运行一张原始布局。
- 记录 score、win/lose、remaining food、Pac-Man 回合数、Agent 内部时间、墙钟时间、timeout 和 error。
- 固定组使用字符串 seed `cs188`，与 `-f` 等价。
- 泛化组使用预先固定的整数 seeds 0–9，不读取或预测 RNG 状态。

首次运行临时脚本失败：

```text
ModuleNotFoundError: No module named 'pacman'
```

原因是脚本位于 `/tmp`。随后显式设置只读 `PYTHONPATH=/data/hongzefu/qmj-grid/commits`，成功复现 `q2_testClassic=524/胜`。

## 初始基线

提交前版本：

- 官方 evaluator：7/12 胜，总分15386，平均1282.17。
- seeds 0–2：17/36 胜，47.22%；平均849.75；0 timeout/error。

## 候选实验与决策

### 保留

1. **等价 ghost 排序与 evaluation cache**
   - 254组真实 ghost sibling 与完整评估排序完全一致。
   - 固定均分约1224.58→1332.00；多 seed 17→18胜。
2. **后继缓存**
   - 每次 `getAction` 缓存 `(GameState, agentIndex)` 后继，减少迭代加深重复生成。
3. **forced-loss expectimax**
   - 正常选择仍为严格 alpha-beta；仅当完整值≤-900000时触发。
   - trapped 固定 -501/负→532/胜；20 seeds 获得8胜。
4. **reactive fallback**
   - 不削减24秒深搜索预算；预算耗尽后、总内部时间<28秒时，每回合最多3ms检查一步 ghost 回复。
   - 固定 tricky 曾由负转为3040/胜；多 seed 大图平均分提高。
5. **安全走廊快捷规则**
   - 直走廊、active ghost距离>6时保持方向，节约决策预算。
   - 固定 original 转胜；3-seed成功率显著增加。
6. **cycle guard**
   - 记录自上次吃豆后的访问位置；重复时恢复搜索，预算耗尽时偏好较少访问的安全后继。
7. **每局一次复杂度深度**
   - 仅在 `registerInitialState` 计算联合分支；>64时最大depth=2，否则depth=3。

### 淘汰

- 削减深搜索到22.5秒换strong fallback：medium2固定1994→1415。
- 全局maze distance：contest、danger、medium2、open均下降；测试主动Ctrl-C中止。
- `dangerScale=2.0`：成功数不增，tricky均分下降；`1.5`令open由胜转负。
- 全局胶囊加倍：capsule提高，但medium2固定1994→478。
- active ghost近时胶囊加倍：capsule无净增，medium2仍回归。
- 提前endgame权重：open出现3258回合循环并由胜转负。
- 纯expectimax：trapped转胜，但medium/open由胜转负。
- mean/min混合0.25：仍丢medium/open，主动中止。
- fallback最近食物优先：open循环1757→1816回合，撤销。
- 全局depth2：成功率与depth3相同，固定均分下降。
- 每回合分支自适应：额外开销使open/original固定转负，撤销。

所有主动中止均通过向评估PTY发送Ctrl-C完成，输出 `KeyboardInterrupt`；它们是已知退化候选，不是最终代码失败。

## 最终结果

### 官方 evaluator

- 10/12胜，成功率83.33%。
- 总分16991，平均1415.92。
- 仅danger、medium2失败。
- 退出码0；0 timeout/crash/Traceback。

### 固定 seed

- 发布安全版两次独立完整运行分别为9/12和10/12胜。
- 发布硬化前曾三次重复得到28/36胜，用于估计时钟方差，不作为最终发布口径。
- 所有运行均为0 timeout/error。

### 发布安全版5-seed泛化

- seeds 0–4，每个完整覆盖12图，共60局。
- 37/60胜，61.67%。
- 平均分1161.12。
- 0 timeout/error。
- 在paired seeds0–2中：17/36→23/36胜，平均849.75→1178.42。

每图5-seed胜数：capsule 3、contest 4、danger 0、medium 5、medium2 0、minimax 5、open 5、original 1、small 5、test 5、trapped 2、tricky 2。

发布硬化前的最优候选还完成了seeds0–9共120局，得到77/120胜、64.17%、平均约1165.07；该数据只作为跨10 seeds过拟合检查，不冒充最终发布版统计。

### 发布审查硬化

- scaredTimer≤1的ghost按active处理，避免timer归零回合误判安全。
- 安全走廊规则先完成depth1 alpha-beta；只在非终局级必败时采用rule override。
- reactive非O(1)内部上限从28秒收紧到27秒；达到上限后只返回已知合法动作。

## 补丁与环境失败记录

- 多次 `apply_patch` 因执行环境 `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` 失败；失败未修改文件，随后使用自动生成、行数校验的统一补丁。
- 一次 `functions.exec` 编排因 JavaScript 字符串/括号错误返回 SyntaxError，任何 shell 命令执行前即终止；修正后成功。
- 多个明确退化的长基准由Ctrl-C主动中止并保留 `KeyboardInterrupt` 输出。
- 每次正式源码或报告变化后均运行 `uv lock` 成功；依赖未变化。

最终提交前检查、提交与推送结果保留在Git提交正文和后续Git历史中。
