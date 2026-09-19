"""任务日志字段取值词表（单一数据源）。

日志统一写成空格分隔的 key=value 字段：字段键名（step/event/reason/result/key/period
等）在调用点就近写出，取值词表固定在本模块，保证全项目可 grep、可被日志系统按字段解析。

约定：
- 任务身份由 logger 前缀（类名）承担，不写进字段；
- 步骤名由 try_step 绑定到 self._active_step，调用点直接引用，不另定字面量；
- 事件词、结果词与跨任务通用原因词固定在本表，任务私有原因（如 no_reward）就近书写。
"""

# event= 取值：步骤/子流程的生命周期与选择决策。
# 点击动作不在此列：框架 click/click_box/wait_click_feature 在传入 name 时自动记 `left_click <name> (x, y)`，
# 调用点无需另记；仅 click_relative(无 name)/mouse_down/move 等框架无日志的手势若属关键动作才需自记。
EVENT_START = "start"  # 开始。
EVENT_END = "end"  # 正常结束。
EVENT_SKIP = "skip"  # 跳过（无需执行/无可用内容）。
EVENT_FAIL = "fail"  # 一次尝试失败。
EVENT_ABORT = "abort"  # 中止（放弃重试/配置非法/前置失败）。
EVENT_ROUND = "round"  # 循环轮次。
EVENT_SELECT = "select"  # 选择决策（选中目标/对手/栏目等，框架不记录判定依据）。

# result= 取值：步骤/任务的结果。
RESULT_SUCCESS = "success"  # 成功。
RESULT_FAILED = "failed"  # 失败。

# reason= 取值：跨任务通用原因；任务私有原因就近书写。
REASON_ALREADY_DONE = "already_done"  # 本周期已完成。
REASON_DISABLED = "disabled"  # 配置未开启。
REASON_LOBBY_NOT_FOUND = "lobby_not_found"  # 未能就位大厅。
REASON_IN_LOBBY = "in_lobby"  # 已在大厅，无需就位。
REASON_RETRIES_EXHAUSTED = "retries_exhausted"  # 重试耗尽。
REASON_RECOVER_FAILED = "recover_failed"  # 恢复回大厅失败。
REASON_ENTRY_MISSING = "entry_missing"  # 入口缺失/未找到入口。
REASON_SEASON_ENDED = "season_ended"  # 休赛期/赛季已结束。
REASON_TIMEOUT = "timeout"  # 等待超时。
REASON_CONFIG_CONFLICT = "config_conflict"  # 配置冲突或非法。
REASON_CAPPED = "capped"  # 达到次数/轮次上限。
REASON_NOT_FOUND = "not_found"  # 未找到目标特征/界面。
REASON_FAILED = "failed"  # 子流程/操作失败。
REASON_BATTLE_FAILED = "battle_failed"  # 战斗失败。
REASON_NO_REWARD = "no_reward"  # 无可领取奖励。
REASON_BOX_MISSING = "box_missing"  # 所需区域特征缺失。
REASON_LIST_BOTTOM = "list_bottom"  # 列表已滚动到底。
