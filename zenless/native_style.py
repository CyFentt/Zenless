UI_WINDOW_CONTROL = 22


def stylesheet(state=None) -> str:
    state = state or {}
    pad = 2 if str(state.get('density', 'COMPACT')).upper() == 'COMPACT' else 4
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10px; outline: none; }}
    QMainWindow, QDialog, QWidget {{ background: #050505; color: #d8d8d8; }}
    #windowRoot {{ background: #050505; border: 1px solid #202020; }}
    #mainSurface {{ background: #050505; }}
    #titleBar {{ background: #030303; border-bottom: 1px solid #181818; }}
    #header {{ background: #060606; border-bottom: 1px solid #1b1b1b; }}
    #headerDivider {{ background: #202020; }}
    #workspaceStrip {{ background: transparent; border: none; }}
    QTabBar#workspaceTabs {{ background: transparent; border: none; }}
    QTabBar#workspaceTabs::tab {{ background: #070707; color: #737373; border: 1px solid #202020; border-bottom: none; border-radius: 0px; min-width: 74px; max-width: 150px; height: 22px; padding: 0px 5px 0px 8px; margin-right: 2px; font-family: 'Consolas'; font-size: 9px; font-weight: 700; letter-spacing: .5px; }}
    QTabBar#workspaceTabs::tab:hover {{ color: #d8d8d8; border-color: #383838; background: #0b0b0b; }}
    QTabBar#workspaceTabs::tab:selected {{ color: #f0f0f0; background: #0b0b0b; border-color: #505050; border-top: 1px solid #d8d8d8; }}
    QToolButton#tabCloseButton {{ min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; border: none; background: transparent; padding: 0; }}
    QToolButton#tabCloseButton:hover {{ background: #171717; border: none; }}
    #sidebar {{ background: #060606; border-right: 1px solid #1a1a1a; }}
    #settingsTop {{ background: #060606; border-bottom: 1px solid #202020; }}
    #settingsFooter {{ background: #060606; border-top: 1px solid #202020; }}
    #settingsScroll {{ background: #050505; border: none; }}
    #brand {{ font-family: 'Consolas'; font-size: 9px; font-weight: 800; color: #b8b8b8; letter-spacing: 1px; }}
    #chatTitle {{ font-family: 'Consolas'; font-size: 10px; font-weight: 800; color: #eeeeee; letter-spacing: .7px; }}
    #sectionTitle {{ font-family: 'Consolas'; color: #999999; font-size: 8px; font-weight: 800; letter-spacing: .8px; }}
    #usage {{ background: #070707; border: 1px solid #242424; border-radius: 0px; padding: 2px 5px; color: #a0a0a0; font-family: 'Consolas'; font-size: 8px; }}
    #usage:hover {{ border-color: #4a4a4a; color: #ededed; }}
    #contextUsage {{ color: #707070; font-family: 'Consolas'; font-size: 8px; padding: 0 2px; }}
    #muted, #footer {{ color: #686868; font-size: 8px; }}
    #mapSelection {{ color: #777777; font-family: 'Consolas'; font-size: 8px; padding: 2px 3px; }}
    #queueStatus {{ color: #dedede; font-family: 'Consolas'; font-size: 8px; font-weight: 700; padding: 2px 5px; border: 1px solid #292929; border-radius: 0px; background: #070707; }}
    #thinkingPulse {{ color: #d8d8d8; background: #080808; border: 1px solid #2a2a2a; padding: 2px 6px; font-family: 'Consolas'; font-size: 8px; font-weight: 800; letter-spacing: .8px; }}
    #composerFrame {{ background: #070707; border: 1px solid #272727; border-radius: 1px; }}
    #composerFrame[focused="true"] {{ border: 1px solid #6e6e6e; }}
    #transcript {{ background: transparent; border: none; }}
    #projectGraph {{ background: #050505; border: 1px solid #202020; border-radius: 0px; }}
    #petBubble, #petQuick, #toastFrame {{ background: #070707; border: 1px solid #303030; border-radius: 1px; }}
    #toastIndicator {{ background: #ffffff; border: none; }}
    QGroupBox {{ border: 1px solid #202020; border-radius: 0px; margin-top: 8px; padding-top: 8px; color: #b7b7b7; font-weight: 650; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 7px; padding: 0 4px; color: #858585; font-family: 'Consolas'; font-size: 8px; font-weight: 800; letter-spacing: .7px; }}
    QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QComboBox, QSpinBox {{ background: #070707; color: #e0e0e0; border: 1px solid #252525; border-radius: 0px; padding: {pad}px; selection-background-color: #303030; }}
    QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QComboBox:focus, QSpinBox:focus {{ border-color: #686868; }}
    QPlainTextEdit#composer {{ border: none; background: transparent; padding: 1px; }}
    QPushButton, QToolButton {{ background: #080808; color: #c2c2c2; border: 1px solid #292929; border-radius: 0px; padding: 2px 6px; }}
    QPushButton:hover, QToolButton:hover {{ background: #101010; border-color: #505050; color: #f0f0f0; }}
    QPushButton:pressed, QToolButton:pressed {{ background: #d8d8d8; border-color: #eeeeee; color: #050505; }}
    QPushButton:disabled, QToolButton:disabled {{ color: #404040; border-color: #171717; background: #060606; }}
    #primaryButton {{ background: #dedede; color: #050505; border-color: #ededed; font-weight: 800; }}
    #primaryButton:hover {{ background: #ffffff; color: #000000; }}
    #danger {{ color: #e06767; border-color: #512525; }}
    #ghostButton {{ font-family: 'Consolas'; font-size: 8px; font-weight: 700; letter-spacing: .4px; }}
    #windowButton, #windowCloseButton {{ min-width: {UI_WINDOW_CONTROL}px; max-width: {UI_WINDOW_CONTROL}px; min-height: {UI_WINDOW_CONTROL}px; max-height: {UI_WINDOW_CONTROL}px; border: 0px; background: transparent; padding: 0; margin: 0; }}
    #windowButton:hover {{ background: #121212; }}
    #windowCloseButton:hover {{ background: #762020; }}
    #linkState {{ color: #777777; background: transparent; border-color: #242424; font-family: 'Consolas'; font-size: 8px; font-weight: 800; }}
    #linkState[linked="true"] {{ color: #67d88b; border-color: #28513a; background: #071009; }}
    #petQuickToggle:checked {{ background: #11100c; border-color: #d6a349; }}
    #queueStripButton {{ text-align: left; color: #737373; background: #070707; border: 1px solid #1d1d1d; padding-left: 7px; font-family: 'Consolas'; font-size: 8px; }}
    #queueStripButton:hover {{ color: #e0e0e0; border-color: #3b3b3b; }}
    #queueStripButton[active="true"] {{ color: #eeeeee; border-color: #464646; background: #0a0a0a; }}
    QListWidget::item {{ padding: 4px 5px; margin: 0; border-radius: 0px; color: #a0a0a0; }}
    QListWidget::item:hover {{ background: #0e0e0e; color: #e9e9e9; }}
    QListWidget::item:selected {{ background: #121212; color: #ffffff; border-left: 2px solid #d8d8d8; }}
    QComboBox::drop-down {{ border: none; width: 15px; }}
    QMenu {{ background: #070707; color: #d5d5d5; border: 1px solid #2c2c2c; padding: 2px; }}
    QMenu::item {{ padding: 4px 16px; border-radius: 0px; }}
    QMenu::item:selected {{ background: #d8d8d8; color: #050505; }}
    QCheckBox {{ color: #b0b0b0; spacing: 5px; }}
    QCheckBox::indicator {{ width: 11px; height: 11px; border: 1px solid #3a3a3a; border-radius: 0px; background: #070707; }}
    QCheckBox::indicator:checked {{ background: #dcdcdc; border-color: #f0f0f0; }}
    QToolTip {{ background: #080808; color: #eeeeee; border: 1px solid #3b3b3b; padding: 3px; border-radius: 0px; }}
    QScrollBar:vertical {{ background: #050505; width: 5px; }}
    QScrollBar::handle:vertical {{ background: #303030; min-height: 22px; border-radius: 0px; }}
    QScrollBar::handle:vertical:hover {{ background: #5e5e5e; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """

