import re  # 正则模块，用于结算 ESC 确认文字的部分匹配。
import time  # 时间模块，处理战斗结束等待与超时。

from ok.feature.Box import find_boxes_by_name  # 按名过滤 OCR 框，复刻 ocr(match=...) 的过滤语义。
from ok.task.exceptions import TaskDisabledException  # 战斗等待中被用户停止时需原样传播的中断异常。

from src.screens import INTERRUPTS  # 中断哨兵清单（断线/维护/登录过期弹窗特征）。
from src.tasks.base._exceptions import InterruptedByDialogException  # 长等待命中致命中断弹窗时抛出。


class BattleMixin:
    """战斗结束等待与自动战斗开启：节流轮询、只检测不点击、中断哨兵快速失败。"""

    _BATTLE_FINISH_ESC_PATTERN = re.compile(r"\bESC\b", re.IGNORECASE)  # 结算界面 ESC 确认文字（OCR 部分匹配，忽略大小写）。
    _BATTLE_AUTO_BOXES = ("box_battle_auto_aim", "box_battle_auto_burst")  # 自动瞄准/自动爆裂按钮区域（coco 区域；彩色=已开启，灰白=已关闭）。

    def wait_battle_finish(self, time_out=240, check_interval=3, settle_time=2):
        """节流轮询等待自动战斗结束，返回 (结果, 确认按钮框)，不自动点击。

        战斗时长不确定（约10秒~3分钟）：每 check_interval 秒才刷新一帧做单次
        检测；命中结算界面后先等待 settle_time 秒让结算入场动画收尾，再刷新
        一帧复识别确认仍在结算界面并返回——结算界面刚出现时直接返回会让调用方
        在动画期间误操作。超时返回 (None, None)。避免用 wait_feature 等
        忙轮询长时间对游戏窗口持续抓帧/匹配，与游戏抢 CPU。

        正常结束：对 box_battle_finish_text 区域 OCR 识别 ESC 确认文字
        （区域框随分辨率等比缩放，比图标模板跨分辨率更可靠）。OCR 未命中时在
        box_battle_finish_bottom_right 区查找 battle_finish_statistics 兜底判定
        胜利。两条胜利路径返回的可点击框统一为 box_battle_finish_text 区域框。
        战斗失败：同时识别 battle_finish_failed 与 battle_finish_failed_back。

        此处只检测不点击——战斗结束后的动作由调用方决定（连续战斗的胜利界面
        可能有"下一关"等其它按钮），返回值带上了识别到的确认按钮框，调用方
        需要点击时可直接用它。

        进入战斗界面时附带一次性开启自动瞄准/自动爆裂：轮询中一旦识别到
        battle_pause（暂停按钮只在战斗界面出现）即认为已进入自动战斗界面，
        调用 _enable_battle_auto_once 把两个灰白的自动按钮点成彩色，之后置位
        标记不再重复触发（按钮是开关，重复点会关掉）。快速战斗等不进入战斗
        界面的流程结算界面先被识别到而直接返回，不会触发该流程。

        Returns:
            ("success", text_box) 正常结束，text_box 为 box_battle_finish_text 区域框；
            ("failed", failed_back_box) 战斗失败，failed_back_box 为返回按钮框；
            (None, None) 超时。
        """
        deadline = time.time() + time_out  # 记录整体超时时刻。
        polls = 0  # 轮询计数，用于 debug 日志观察节流间隔。
        auto_checked = False  # 自动按钮只开启一次：放开会导致每轮轮询重复点击（按钮是开关，点第二次就关掉了）。
        while time.time() < deadline:  # 节流循环直到超时。
            self.sleep(check_interval)  # 轻量等待，不抓帧不匹配。
            self.next_frame()  # 刷新一帧，避免使用旧帧。
            polls += 1  # 轮询次数加一。
            self.log_debug(f"战斗轮询第 {polls} 次（每 {check_interval} 秒一帧），已耗时 {time.time() - (deadline - time_out):.0f} 秒。")  # debug 日志确认轮询节奏。
            if self._hit_interrupt() is not None:  # 先查中断哨兵：断线/维护/登录过期弹窗会让后续匹配全部落空，快速失败优于空转等满超时。
                self.save_failure_screenshot("interrupt")  # 保存中断现场截图便于排查。
                self.log_warning("检测到致命中断弹窗，中止长等待。")  # 记录中断原因。
                raise InterruptedByDialogException("long wait interrupted by dialog")  # 由 try_step 按等待失败恢复。
            # 胜利判定主路径：对 box_battle_finish_text 区域 OCR 识别 ESC 确认文字。
            text_box = self._battle_finish_text_box()  # 获取结算文字区域框（coco 坐标区域，按当前分辨率缩放；特征缺失为 None）。
            if text_box is not None and self._esc_visible(text_box):  # 该区域命中 ESC 文字，判定正常结束。
                confirm = self._stabilize_battle_finish_box(text_box, settle_time=settle_time)  # 等结算动画收尾后复识别确认仍在结算界面，返回统一可点击区域框。
                self.log_info("检测到战斗胜利结算界面。")  # 记录正常结束。
                return "success", confirm  # 返回结果与确认按钮框，由调用方决定后续动作。
            # OCR 未命中兜底：在结算右下区查找 battle_finish_statistics，命中即判胜利。
            # 返回的可点击框仍统一为 box_battle_finish_text 区域：statistics 仅做检测，不做可点击框。
            statistics = self.find_one("battle_finish_statistics", box="box_battle_finish_bottom_right")  # 限定在右下角结算信息区匹配统计文字特征，避免全屏误命中。
            if statistics is not None:  # OCR 未命中但 statistics 兜底命中，判定为战斗胜利。
                confirm = self._stabilize_battle_finish_box(text_box if text_box is not None else statistics, settle_time=settle_time)  # 等结算动画收尾后复识别确认，返回统一可点击区域框。
                self.log_info("检测到战斗胜利结算界面（statistics 兜底）。")  # 记录经兜底判定的正常结束。
                return "success", confirm  # 返回结果与确认按钮框，由调用方决定后续动作。
            failed = self.find_one("battle_finish_failed")  # 单帧匹配战斗失败特征。
            failed_back = self.find_one("battle_finish_failed_back")  # 单帧匹配失败返回按钮特征。
            if failed is not None and failed_back is not None:  # 战斗失败。
                failed_back = self._stabilize_battle_finish_box(failed_back, failed=True, settle_time=settle_time)  # 同样等稳定后重新定位失败返回按钮。
                self.log_info("检测到战斗失败结算界面。")  # 记录失败结束。
                return "failed", failed_back  # 返回结果与返回按钮框，由调用方决定后续动作。
            if not auto_checked and self._in_battle_page():  # 结算判定都未命中且识别到暂停按钮=确已进入自动战斗界面（快速战斗无战斗界面，不会走到这里）。
                auto_checked = True  # 置位标记：整个等待流程内只开启一次。
                self._enable_battle_auto_once()  # 开启自动瞄准/自动爆裂（内部吞异常，失败也不影响继续等待战斗结束）。
        self.save_failure_screenshot("wait_battle_finish")  # 超时保存现场截图便于排查。
        self.log_warning(f"等待战斗结束超时（{time_out}秒）。")  # 记录超时原因。
        return None, None  # 返回超时结果。

    def _in_battle_page(self) -> bool:
        """是否处于自动战斗界面：单帧匹配 battle_pause（战斗内暂停按钮）特征。

        暂停按钮只出现在战斗界面，命中即认为已进入自动战斗界面；快速战斗等
        不进入战斗界面的流程不会命中。匹配异常一律按未命中处理，不影响等待
        战斗结束的主流程；用户主动停止（TaskDisabledException）必须传播。
        """
        try:  # 特征缺失/匹配异常都不应影响等待战斗结束。
            return self.find_one("battle_pause") is not None  # 命中暂停按钮即视为在战斗界面。
        except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
            raise  # 重新抛出，交由执行器结束任务。
        except Exception as e:  # 特征缺失等其它异常。
            self.log_debug(f"battle_pause 匹配失败，按未进入战斗界面处理: {e}")  # 记录原因。
            return False  # 返回未命中。

    def _enable_battle_auto_once(self, max_attempts=3, after_sleep=1):
        """进入自动战斗界面后一次性开启自动瞄准/自动爆裂：区域灰白（关闭）则点击，直到判定为已开启或试满次数。

        逐个区域判态：is_feature_enabled 为 True（彩色高亮）即已开启；为 False
        （灰白）则点击切换，刷新帧后复判，最多 max_attempts 次——点击后必须刷新
        帧，因为 click 内部的 reset_scene 会把当前帧置空，无帧时 is_feature_enabled
        会保守判为已开启而漏点。

        全程吞掉异常只记日志：自动按钮开启失败不得影响后续等待战斗结束；
        用户主动停止（TaskDisabledException）必须原样向上传播，否则无法中断任务。
        """
        for name in self._BATTLE_AUTO_BOXES:  # 逐个处理两个自动按钮区域。
            try:  # coco 区域缺失等异常不应影响另一个区域与后续等待。
                box = self.get_box_by_name(name)  # 按当前分辨率解析区域框。
            except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                raise  # 重新抛出，交由执行器结束任务。
            except Exception as e:  # 特征缺失等异常。
                self.log_debug(f"{name} 区域不可用，跳过开启: {e}")  # 记录跳过原因。
                continue  # 处理下一个区域。
            if box is None:  # 区域无效。
                continue  # 跳过该区域。
            for attempt in range(max_attempts):  # 点击后复判，直到开启或试满次数。
                try:  # 点击/取帧异常不应中断等待战斗结束。
                    if self.frame is None:  # 当前帧被清空（上一次点击的 reset_scene）。
                        self.next_frame()  # 先取帧，避免无帧时判态失真。
                    if self.is_feature_enabled(box):  # 彩色高亮=已开启。
                        break  # 该区域已开启，处理下一个。
                    self.log_info(f"点击开启 {name}（第 {attempt + 1} 次）。")  # 记录点击动作。
                    self.click_box(box, after_sleep=after_sleep)  # 点击切换为开启态并等待界面响应。
                    self.next_frame()  # 刷新一帧，复判时读的是点击后的画面。
                except TaskDisabledException:  # 任务已被用户停止，必须让中断异常继续向上传播。
                    raise  # 重新抛出，交由执行器结束任务。
                except Exception as e:  # 点击/取帧失败等异常。
                    self.log_warning(f"开启 {name} 失败，跳过: {e}")  # 记录失败原因。
                    break  # 放弃该区域，处理下一个。

    def _battle_finish_text_box(self):
        """获取 box_battle_finish_text 结算文字区域框（coco 坐标区域，按当前分辨率缩放）。

        该区域固定不随结算动画漂移，同时用作胜利结算的 OCR 检测区与统一返回的
        可点击框；特征缺失（coco 未标注）时返回 None，由调用方跳过主路径。
        """
        try:  # 特征可能尚未标注进 coco。
            return self.get_box_by_name("box_battle_finish_text")  # 按当前分辨率解析区域框。
        except ValueError:  # 特征缺失视为区域不可用。
            return None  # 返回 None。

    def _esc_visible(self, text_box) -> bool:
        """在 box_battle_finish_text 区域 OCR 识别 ESC 确认文字，命中返回 True。

        走帧级缓存：同一帧内重复判定只真正 OCR 一次。
        """
        boxes = self._region_ocr_cached(self._ocr_box_key(text_box), text_box)  # 区域 OCR（同帧缓存）。
        return bool(find_boxes_by_name(boxes, self.fix_match_regex(self._BATTLE_FINISH_ESC_PATTERN)))  # 与 ocr(match=...) 相同的部分匹配过滤。

    def _victory_settle_still_visible(self) -> bool:
        """结算稳定化后的复识别：OCR box_battle_finish_text 命中 ESC，或
        box_battle_finish_bottom_right 内 statistics 兜底命中，即认为仍在胜利结算界面。

        任一判据命中即视为仍在结算界面（防止动画一帧误命中后界面已跳走）。
        """
        text_box = self._battle_finish_text_box()  # 获取结算文字区域框。
        if text_box is not None and self._esc_visible(text_box):  # 主判据仍命中。
            return True  # 仍在胜利结算界面。
        try:  # 主判据失配时查兜底判据。
            return self.find_one("battle_finish_statistics", box="box_battle_finish_bottom_right") is not None  # statistics 兜底仍在。
        except ValueError:  # 特征缺失视为未命中。
            return False  # 返回 False。

    def _stabilize_battle_finish_box(self, box, failed=False, settle_time=2):
        """结算界面命中后的稳定化：等待 settle_time 秒让入场动画收尾，刷新一帧复识别确认仍在结算界面。

        胜利结算：复识别（OCR box_battle_finish_text 命中 ESC 或 statistics 兜底命中）
        确认仍在结算界面后返回 box_battle_finish_text 区域框——该区域固定不随动画
        漂移，两条胜利路径统一用它作可点击框；复识别未命中（界面已自动跳转等异常）
        时退回原检测框，交由调用方的后续动作兜底。
        失败结算：先复核 failed 特征仍在前台，再重新定位 failed_back 返回按钮。

        Args:
            box: 初次命中的检测框（胜利路径为 text_box 区域框，失败路径为 failed_back 按钮框）。
            failed: 是否为失败结算分支。
            settle_time: 稳定化等待秒数。
        Returns:
            稳定后的可点击框；复识别未命中时为原框。
        """
        self.sleep(settle_time)  # 等待结算入场动画收尾（时长见 wait_battle_finish 的 settle_time 参数）。
        self.next_frame()  # 刷新一帧获取稳定后的结算画面。
        if failed:  # 失败结算：先复核 failed 特征仍在前台。
            if self.find_one("battle_finish_failed") is None:  # 失败界面已不在。
                return box  # 退回原检测框兜底。
            stable = self.find_one("battle_finish_failed_back")  # 重新定位失败返回按钮。
            return stable if stable is not None else box  # 复识别命中则采用稳定坐标，否则退回原框。
        if not self._victory_settle_still_visible():  # 胜利结算：复识别确认仍在结算界面。
            return box  # 界面已跳走，退回原检测框兜底。
        text_box = self._battle_finish_text_box()  # 复识别通过，取统一可点击区域框。
        return text_box if text_box is not None else box  # 区域可取则返回区域框，否则退回原框。

    def _hit_interrupt(self):
        """检查当前帧是否命中致命中断弹窗特征（src/screens.py 的 INTERRUPTS 清单）。

        返回命中的 Box，未命中返回 None。清单为空 = 哨兵未激活，零开销直接跳过；
        复用 P1.2 帧级缓存路径，检测不新增抓帧频率。特征未标注进 coco（ValueError）
        时按未命中处理。
        """
        for name in INTERRUPTS.get("features", ()):  # 遍历中断特征清单。
            try:  # 特征可能尚未标注进 coco。
                box = self._find_feature_cached(name)  # 同帧只匹配一次。
            except ValueError:  # 未标注视为未命中。
                continue
            if box is not None:  # 命中断线/维护/登录过期等弹窗。
                return box
        return None