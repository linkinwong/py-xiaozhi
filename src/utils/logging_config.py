import logging
import os
from logging.handlers import TimedRotatingFileHandler
from colorlog import ColoredFormatter


# 创建一个自定义过滤器，允许特定模块使用DEBUG级别
class ModuleFilter(logging.Filter):
    """自定义过滤器，允许指定模块的DEBUG级别日志通过"""
    
    def __init__(self, debug_modules=None):
        super().__init__()
        self.debug_modules = debug_modules or []
    
    def filter(self, record):
        # 如果日志级别不是DEBUG，则始终通过
        if record.levelno != logging.DEBUG:
            return True
        
        # 如果是DEBUG级别，则检查模块名是否在允许列表中
        # 支持多种匹配方式
        logger_name = record.name
        for module_name in self.debug_modules:
            # 完全匹配
            if logger_name == module_name:
                return True
            # 前缀匹配
            if logger_name.startswith(module_name):
                return True
            # 包含匹配
            if module_name in logger_name:
                return True
            # 文件名匹配 (如vad_detector)
            if module_name.split('.')[-1] == logger_name.split('.')[-1]:
                return True
        
        # 其他DEBUG级别的日志将被过滤掉
        return False


def setup_logging(debug_modules=None):
    """
    配置日志系统
    
    Args:
        debug_modules: 允许DEBUG级别日志的模块名列表
    """
    # 默认值
    debug_modules = debug_modules or ["src.audio_processing.vad_detector"]
    
    # 创建logs目录（如果不存在）
    log_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        '..', 
        '..', 
        'logs'
    )
    os.makedirs(log_dir, exist_ok=True)
    
    # 日志文件路径
    log_file = os.path.join(log_dir, 'app.log')
    
    # 创建根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # 设置根日志级别为DEBUG，确保DEBUG级别的消息可以通过
    
    # 清除已有的处理器（避免重复添加）
    if root_logger.handlers:
        root_logger.handlers.clear()
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)  # 允许DEBUG级别通过
    
    # 添加模块过滤器
    module_filter = ModuleFilter(debug_modules)
    console_handler.addFilter(module_filter)
    
    # 创建按天切割的文件处理器
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='midnight',  # 每天午夜切割
        interval=1,       # 每1天
        backupCount=30,   # 保留30天的日志
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.suffix = "%Y-%m-%d.log"  # 日志文件后缀格式
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s[%(name)s] - %(levelname)s - %(message)s - %(threadName)s'
    )
    
    # 控制台颜色格式化器
    color_formatter = ColoredFormatter(
        '%(green)s%(asctime)s%(reset)s[%(blue)s%(name)s%(reset)s] - '
        '%(log_color)s%(levelname)s%(reset)s - %(green)s%(message)s%(reset)s - '
        '%(cyan)s%(threadName)s%(reset)s',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'white',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={
            'asctime': {'green': 'green'},
            'name': {'blue': 'blue'}
        }
    )
    console_handler.setFormatter(color_formatter)
    file_handler.setFormatter(formatter)
    
    # 添加处理器到根日志记录器
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # 输出日志配置信息
    logging.info("日志系统已初始化，日志文件: %s", log_file)
    logging.info("DEBUG级别启用的模块: %s", debug_modules)
    
    return log_file


def get_logger(name):
    """
    获取统一配置的日志记录器
    
    Args:
        name: 日志记录器名称，通常是模块名
        
    Returns:
        logging.Logger: 配置好的日志记录器
    
    示例:
        logger = get_logger(__name__)
        logger.info("这是一条信息")
        logger.error("出错了: %s", error_msg)
    """
    logger = logging.getLogger(name)
    
    # 打印一些诊断信息
    print(f"创建日志记录器: {name}, 有效级别: {logging.getLevelName(logger.getEffectiveLevel())}")
    
    # 添加一些辅助方法
    def log_error_with_exc(msg, *args, **kwargs):
        """记录错误并自动包含异常堆栈"""
        kwargs['exc_info'] = True
        logger.error(msg, *args, **kwargs)
    # 添加到日志记录器
    logger.error_exc = log_error_with_exc
    return logger