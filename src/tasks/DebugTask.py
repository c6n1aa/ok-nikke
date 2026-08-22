from src.tasks.NikkeBaseTask import NikkeBaseTask  # 导入项目基类，所有任务统一继承它。


class DebugTask(NikkeBaseTask):  # 实机调试任务：供「开发工具」tab 按需调用单个调试方法。
    # 用法：GUI 开发工具 tab → Debug Task Function → 选 DebugTask → 输入方法名 → Call。
    # 每个方法执行一个独立动作并返回可读字符串，方便逐项排查实机问题。

    def __init__(self, *args, **kwargs):  # 初始化任务元数据与配置。
        super().__init__(*args, **kwargs)  # 必须先调用父类初始化。
        self.name = "调试"  # 任务显示名称。
        self.description = "实机调试：在开发工具 tab 中按需调用各调试方法。"  # 任务说明。

    def run(self):  # 任务执行入口。
        # 本任务专供「开发工具」tab 逐个调用方法调试，不提供一键 run 编排；
        # 若直接点击运行，仅提示改用开发工具，避免误以为是完整任务。
        self.log_info("调试任务请使用开发工具 tab，在 Debug Task Function 中选 DebugTask 后调用具体方法。")

    # ---- 画面与页面 ----

    def debug_current_screen(self):
        """查看当前页面：返回命中的界面名及所有已注册界面的判定详情。"""
        self.next_frame()  # 刷新一帧，确保基于最新画面。
        current = self.current_screen()  # 命中的第一个界面名。
        details = []
        for name, spec in self.screens.items():  # 遍历注册表逐个判定。
            try:  # 单个界面检测异常不中断。
                hit = self._screen_match(spec)  # 判定是否命中。
            except Exception as e:  # 检测异常。
                hit = f'err:{e}'  # 记录异常。
            details.append(f'{name}={"✓" if hit is True else "✗" if hit is False else hit}')  # 拼接。
        result = f'当前页面: {current or "未知/未注册"}\n'  # 当前页面行。
        result += '界面检测: ' + ' '.join(details)  # 各界面命中详情。
        self.log_info(f'debug_current_screen: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    def debug_resolution(self):
        """查看当前游戏分辨率。"""
        self.next_frame()  # 刷新一帧。
        frame = self.frame  # 取当前帧。
        if frame is None:  # 无可用帧。
            return '无可用画面帧'  # 返回提示。
        height, width = frame.shape[:2]  # 取高宽。
        result = f'游戏分辨率: {width}x{height}'  # 拼接结果。
        self.log_info(f'debug_resolution: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    def debug_screenshot(self):
        """保存当前画面截图到 screenshots/debug/ 并返回保存路径。"""
        self.next_frame()  # 刷新一帧。
        try:  # 截图容错。
            self.screenshot(name='debug/manual')  # 保存截图。
        except Exception as e:  # 截图异常。
            return f'截图失败: {e}'  # 返回失败原因。
        result = '已保存截图到 screenshots/debug/'  # 拼接结果。
        self.log_info(f'debug_screenshot: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    # ---- 弹窗 ----

    def debug_close_popups(self):
        """尝试关闭所有公告/遮罩弹窗，返回关闭结果与残留弹窗判断。"""
        self.next_frame()  # 刷新一帧。
        closed = self.dismiss_all_popups(wait_for_popup=False, time_out=5)  # 统一清理弹窗。
        result = f'弹窗清理: {"已关闭弹窗" if closed else "无弹窗或无需关闭"}'  # 拼接结果。
        self.log_info(f'debug_close_popups: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    def debug_close_notice(self):
        """只关闭公告/活动横幅弹窗（右上角铃铛），返回是否成功关闭。"""
        self.next_frame()  # 刷新一帧。
        closed = self._close_notice_popup()  # 尝试关闭公告横幅。
        result = f'公告弹窗: {"已关闭" if closed else "未检测到"}'  # 拼接结果。
        self.log_info(f'debug_close_notice: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    def debug_check_popup(self):
        """检测当前是否有公告/遮罩弹窗（不关闭），返回检测结果。"""
        self.next_frame()  # 刷新一帧。
        try:  # 检测容错。
            bell = None  # 初始化铃铛匹配结果。
            for template_path in self._NOTICE_BELL_TEMPLATES:  # 依次尝试公告铃铛模板。
                bell = self.find_scaled_template("notice_bell", template_path, threshold=0.75)  # 查找铃铛。
                if bell is not None:  # 命中铃铛。
                    break  # 停止尝试。
            mask = self.ocr(x=1 / 3, y=0.6, to_x=2 / 3, to_y=1, match=["点击领取奖励"])  # 检测遮罩。
        except Exception as e:  # 检测异常。
            return f'检测异常: {e}'  # 返回异常。
        parts = []  # 收集检测结果。
        parts.append(f'公告横幅: {"有" if bell else "无"}')  # 公告结果。
        parts.append(f'领取遮罩: {"有" if mask else "无"}')  # 遮罩结果。
        result = ' '.join(parts)  # 拼接结果。
        self.log_info(f'debug_check_popup: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    # ---- 界面恢复 ----

    def debug_recover_lobby(self):
        """执行失败恢复协议（关弹窗 + 回大厅），返回是否回到大厅。"""
        self.next_frame()  # 刷新一帧。
        ok = self._recover_to_lobby(time_out=20)  # 执行恢复协议。
        result = f'恢复回大厅: {"成功" if ok else "失败"}'  # 拼接结果。
        self.log_info(f'debug_recover_lobby: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    def debug_wait_lobby(self):
        """等待游戏大厅出现（识别 ark 特征），返回等待结果。"""
        ok = self.wait_for_lobby(time_out=15, raise_if_not_found=False)  # 等待大厅。
        result = f'大厅等待: {"已在大厅" if ok else "超时未进入大厅"}'  # 拼接结果。
        self.log_info(f'debug_wait_lobby: {result}')  # 记录日志。
        return result  # 返回给开发工具显示。

    # ---- 特征识别 ----

    def debug_find_feature(self):
        """在当前画面查找所有 coco 特征，返回命中的特征名列表。"""
        self.next_frame()  # 刷新一帧。
        found = []  # 收集命中特征。
        try:  # 遍历注册表里的所有特征名（各界面判定特征并集）。
            names = set()
            for spec in self.screens.values():  # 遍历界面判定描述。
                names.update(spec.get('features', []))  # 收集特征名。
            for name in sorted(names):  # 逐个查找。
                try:  # 单个特征查找异常不中断。
                    if self.find_one(name) is not None:  # 命中。
                        found.append(name)  # 加入命中列表。
                except Exception:  # 查找异常。
                    pass  # 忽略。
        except Exception as e:  # 整体异常。
            return f'特征查找异常: {e}'  # 返回异常。
        result = f'命中特征({len(found)}): {", ".join(found) if found else "无"}'  # 拼接结果。
        self.log_info(f'debug_find_feature: {result}')  # 记录日志。
        return result  # 返回给开发工具显示.
