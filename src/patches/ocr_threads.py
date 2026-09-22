"""OCR 线程配置补丁：把 onnxruntime 会话固定为 4 线程、关闭线程自旋。

onnxruntime 默认按物理核数开 intra-op 线程池（det / rec 各一个）且默认开启自旋等待。
"""

from ok import Logger

logger = Logger.get_logger(__name__)

_INTRA_OP_THREADS = 4  # onnxruntime 默认等于物理核数
_INTER_OP_THREADS = 1  # 顺序执行模型，inter-op 线程池保持 1
_ALLOW_SPINNING = '0'  # 关闭线程自旋

_patched = False  # 包装只做一次


def _patch_inference_session():
    """包装 onnxruntime.InferenceSession，给每个会话注入线程与自旋配置。"""
    global _patched
    if _patched:
        return
    import onnxruntime

    original_inference_session = onnxruntime.InferenceSession

    class CappedInferenceSession:  # 代理真实会话，其余属性透传。
        def __init__(self, path_or_bytes, sess_options=None, providers=None, **kwargs):
            options = sess_options if sess_options is not None else onnxruntime.SessionOptions()
            options.intra_op_num_threads = _INTRA_OP_THREADS
            options.inter_op_num_threads = _INTER_OP_THREADS
            options.add_session_config_entry('session.intra_op.allow_spinning', _ALLOW_SPINNING)
            self._session = original_inference_session(
                path_or_bytes, sess_options=options, providers=providers, **kwargs)

        def __getattr__(self, name):
            return getattr(self._session, name)

    onnxruntime.InferenceSession = CappedInferenceSession
    _patched = True
    logger.info(f'capped onnxruntime sessions: intra_op={_INTRA_OP_THREADS} threads, '
                f'inter_op={_INTER_OP_THREADS}, spinning={_ALLOW_SPINNING}')


def apply():
    # 在引擎创建前打补丁：onnxruntime 只在首次建引擎时导入（默认初始化跑在 DefaultOCRInit 线程）。
    from ok.task.TaskExecutor import TaskExecutor

    original_create_ocr_lib = TaskExecutor._create_ocr_lib

    def create_ocr_lib(self, name):
        _patch_inference_session()
        return original_create_ocr_lib(self, name)

    TaskExecutor._create_ocr_lib = create_ocr_lib
    logger.info('patched TaskExecutor._create_ocr_lib to cap onnxruntime OCR threads')
