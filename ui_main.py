# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_main.ui'
##
## Created by: Qt User Interface Compiler version 6.11.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QLabel, QMainWindow,
    QPushButton, QSizePolicy, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(513, 97)
        MainWindow.setMinimumSize(QSize(513, 97))
        MainWindow.setMaximumSize(QSize(513, 97))
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.path_label = QLabel(self.centralwidget)
        self.path_label.setObjectName(u"path_label")
        self.path_label.setGeometry(QRect(9, 9, 495, 18))
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label_account = QLabel(self.centralwidget)
        self.label_account.setObjectName(u"label_account")
        self.label_account.setGeometry(QRect(9, 38, 44, 20))
        self.account_combo = QComboBox(self.centralwidget)
        self.account_combo.setObjectName(u"account_combo")
        self.account_combo.setGeometry(QRect(45, 36, 80, 24))
        self.label_char = QLabel(self.centralwidget)
        self.label_char.setObjectName(u"label_char")
        self.label_char.setGeometry(QRect(133, 38, 44, 20))
        self.char_combo = QComboBox(self.centralwidget)
        self.char_combo.setObjectName(u"char_combo")
        self.char_combo.setGeometry(QRect(168, 36, 170, 24))
        self.relief_btn = QPushButton(self.centralwidget)
        self.relief_btn.setObjectName(u"relief_btn")
        self.relief_btn.setGeometry(QRect(344, 36, 50, 24))
        self.label_backup = QLabel(self.centralwidget)
        self.label_backup.setObjectName(u"label_backup")
        self.label_backup.setGeometry(QRect(9, 68, 44, 20))
        self.restore_combo = QComboBox(self.centralwidget)
        self.restore_combo.setObjectName(u"restore_combo")
        self.restore_combo.setGeometry(QRect(44, 66, 294, 24))
        self.backup_btn = QPushButton(self.centralwidget)
        self.backup_btn.setObjectName(u"backup_btn")
        self.backup_btn.setGeometry(QRect(344, 66, 50, 24))
        self.restore_btn = QPushButton(self.centralwidget)
        self.restore_btn.setObjectName(u"restore_btn")
        self.restore_btn.setGeometry(QRect(400, 66, 50, 24))
        self.delete_btn = QPushButton(self.centralwidget)
        self.delete_btn.setObjectName(u"delete_btn")
        self.delete_btn.setGeometry(QRect(456, 66, 50, 24))
        self.export_btn = QPushButton(self.centralwidget)
        self.export_btn.setObjectName(u"export_btn")
        self.export_btn.setGeometry(QRect(400, 36, 50, 24))
        self.import_btn = QPushButton(self.centralwidget)
        self.import_btn.setObjectName(u"import_btn")
        self.import_btn.setGeometry(QRect(456, 36, 50, 24))
        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"功夫派怀旧服存档工具", None))
        self.path_label.setText(QCoreApplication.translate("MainWindow", u"存档位置：", None))
        self.label_account.setText(QCoreApplication.translate("MainWindow", u"账号：", None))
        self.label_char.setText(QCoreApplication.translate("MainWindow", u"角色：", None))
#if QT_CONFIG(tooltip)
        self.relief_btn.setToolTip(QCoreApplication.translate("MainWindow", u"给予<=10级的角色缺少的鲲鹏套装装备", None))
#endif // QT_CONFIG(tooltip)
        self.relief_btn.setText(QCoreApplication.translate("MainWindow", u"减负", None))
        self.label_backup.setText(QCoreApplication.translate("MainWindow", u"备份：", None))
#if QT_CONFIG(tooltip)
        self.backup_btn.setToolTip(QCoreApplication.translate("MainWindow", u"备份账号存档", None))
#endif // QT_CONFIG(tooltip)
        self.backup_btn.setText(QCoreApplication.translate("MainWindow", u"备份", None))
#if QT_CONFIG(tooltip)
        self.restore_btn.setToolTip(QCoreApplication.translate("MainWindow", u"恢复账号备份存档", None))
#endif // QT_CONFIG(tooltip)
        self.restore_btn.setText(QCoreApplication.translate("MainWindow", u"恢复", None))
#if QT_CONFIG(tooltip)
        self.delete_btn.setToolTip(QCoreApplication.translate("MainWindow", u"删除账号备份存档", None))
#endif // QT_CONFIG(tooltip)
        self.delete_btn.setText(QCoreApplication.translate("MainWindow", u"删除", None))
#if QT_CONFIG(tooltip)
        self.export_btn.setToolTip(QCoreApplication.translate("MainWindow", u"导出账号存档到桌面", None))
#endif // QT_CONFIG(tooltip)
        self.export_btn.setText(QCoreApplication.translate("MainWindow", u"导出", None))
#if QT_CONFIG(tooltip)
        self.import_btn.setToolTip(QCoreApplication.translate("MainWindow", u"导入账号存档到游戏", None))
#endif // QT_CONFIG(tooltip)
        self.import_btn.setText(QCoreApplication.translate("MainWindow", u"导入", None))
    # retranslateUi

