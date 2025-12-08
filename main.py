# main.py
# -*- coding: utf-8 -*-
import customtkinter as ctk
import logging
import sys
import os
from langchain.globals import set_verbose

# 关闭 langchain 的 verbose 日志
set_verbose(False)

# 全局禁用 chromadb 的遥测功能，防止报错
os.environ["ANONYMIZED_TELEMETRY"] = "false"


# --- 路径修复 ---
# 兼容 PyInstaller 打包后的环境
if getattr(sys, 'frozen', False):
    # 如果是打包后的 .exe 文件，根目录是 sys._MEIPASS
    application_path = os.path.dirname(sys.executable)
    sys.path.insert(0, sys._MEIPASS)
else:
    # 如果是直接运行 .py 文件，根目录是此文件所在目录
    application_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, application_path)


from ui import NovelGeneratorGUI

class StreamToLogger:
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.level, line.rstrip())

    def flush(self):
        pass

def main():
    # 基本日志配置 (在UI日志处理器接管前)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # 重定向 stdout 和 stderr 到日志记录器
    stdout_logger = logging.getLogger('STDOUT')
    sl_out = StreamToLogger(stdout_logger, logging.INFO)
    sys.stdout = sl_out

    stderr_logger = logging.getLogger('STDERR')
    sl_err = StreamToLogger(stderr_logger, logging.ERROR)
    sys.stderr = sl_err

    app = ctk.CTk()
    gui = NovelGeneratorGUI(app)

    def on_closing():
        """处理窗口关闭事件"""
        if hasattr(gui, 'file_observer') and gui.file_observer:
            gui.file_observer.stop()
            gui.file_observer.join()
        logging.info("正在关闭应用程序...")
        app.destroy()
        os._exit(0)

    app.protocol("WM_DELETE_WINDOW", on_closing)
    app.mainloop()

if __name__ == "__main__":
    main()
