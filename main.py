# ------------------------------------------------------------------
#  Acknowledgements
# ------------------------------------------------------------------
# Mr. Hoang Duc Minh: Initial UI layout & logging table, Displaying camera captures, Gripper 3D model
# Nguyen Phuoc Khang: improve main UI, settings UI, configuration file managing, Cobot trajectory, Full system operation, Documentation, UI Tester, Project manager
# Tran Cao Cap: Battery detection, Aruco calibration, Defisheye, Refactor all system code, build executable, Documentation, -UX Tester, Project manager
# Hoang Ngoc An, Mr. Ngo Tien Tu: Detection model training, Data gathering
# All other interns: Data gathering, System assembly, Scratch code API

# ------------------------------------------------------------------
#  Codes
# ------------------------------------------------------------------
import datetime, time
import logging
import multiprocessing as mp
import sys
import psutil
import cv2

from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QHeaderView,
    QTableWidgetItem,
)
from PyQt5.QtCore import QTimer

import engine.loader as ldr
folder_cam = ldr.folder_cam
DEBUG = ldr.usr_cfg["main"]["debug"]

from resource.InterfaceUI import Ui_MainWindow
from engine.settings import MainWindow as settings_MainWindow

from worker.arm import Arm_worker
from worker.cam_pos import CamPosition
from worker.cam_shot import CamShot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MainWindow(QMainWindow):
    def __init__(self):

        super().__init__()
        self.uic = Ui_MainWindow()
        self.uic.setupUi(self)        
        self._init_table()
        self._init_labels()
        self._init_label_face()

        self.arm1_comms = mp.Queue()
        self.arm2_comms = mp.Queue()
        self.arm1_status = mp.Manager().dict({
                "connected": False,
                "powered": False,
                "enabled": False,
                "state": None
                })
        self.arm2_status = mp.Manager().dict({
                "connected": False,
                "powered": False,
                "enabled": False,
                "state": None
                })
        self.msg = mp.Manager().list()
        self.msg_type = mp.Manager().list()
        
        self.capture_flag = mp.Event()
        self.reset_cam_flag = mp.Value('i', 0)
        self.batt_coords = mp.Array('d', 4)
        self.arm1_worker_thread = None
        self.arm2_worker_thread = None
        self.start_system_flag = mp.Event()
        self.stop_system_flag = mp.Value('i', 0)
        self.foo = 0
        self.last_foo = 0

        # Buttons
        # App Controls
        self.uic.btn_close.clicked.connect(self.close)
        self.uic.btn_mini.clicked.connect(self.showMinimized)
        self.uic.btn_settings.clicked.connect(self._start_settings)  # Placeholder for settings

        # Main Controls
        self.uic.btn_start.clicked.connect(lambda: self._start_system(btn_start=True))
        self.uic.btn_stop.clicked.connect(lambda: self._stop_system(close=True))
        self.showFullScreen()

        # Camera threads
        self.camPos_is_Opened = mp.Event()
        self.camSh_is_Opened = mp.Event()
        self._init_camera(0)
        self._init_camera(1)
        
        # Init settings window placeholder
        self.settings_window = settings_MainWindow(
            self.arm1_status, self.arm2_status, self.arm1_comms, self.arm2_comms, self.camPos_is_Opened, self.camSh_is_Opened, 
            self.stop_system_flag, self.reset_cam_flag, self.msg, self.msg_type)
        
        self.event_update = QTimer(self)
        self.event_update.timeout.connect(self._update_status)
        self.event_update.start(100)

    # ------------------------------------------------------------------
    def _init_table(self):
        self.uic.table_logger.setHorizontalHeaderLabels([
            "Time", "Source", "Message", "Other"]
        )
        self.uic.table_logger.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.uic.table_logger.setRowCount(0)
        self.uic.table_logger.setAutoScroll(True)

    def _init_labels(self):
        self.uic.lb_camPos.setMaximumSize(448, 336)
        self.uic.lb_camPos.setMinimumSize(448, 336)
        self.uic.lb_camShot.setMaximumSize(448, 336)
        self.uic.lb_camShot.setMinimumSize(448, 336)
        # self.uic.lb_debug.setText(" ")

    def _init_label_face(self):
        label_map = {
            1: self.uic.lb_face_1,
            2: self.uic.lb_face_2,
            3: self.uic.lb_face_3,
            4: self.uic.lb_face_4,
            5: self.uic.lb_face_5,
            6: self.uic.lb_face_6,
        }
        for k, v in label_map.items():
            v.setMaximumSize(int(256 * 0.9), int(192 * 0.9))
            v.setMinimumSize(int(256 * 0.9), int(192 * 0.9))
            v.setScaledContents(True)

    def _init_camera(self, idx):
        if idx == 0:                
            self.camPos_is_Opened.clear()
            print(" > CamPos is Opened has cleared")
            self.camPos = CamPosition(self.camPos_is_Opened)
            self.camPos.change_pixmap_signal.connect(self._update_frame_pos)
            self.camPos.detection_signal.connect(self._handle_detection)

            self.camPos.start()
            self._update_log("GUI", "CamPosition started", "")
        elif idx == 1:
            self.camSh_is_Opened.clear()
            print(" > CamShot is Opened has cleared")
            self.camSh = CamShot(self.capture_flag, self.camSh_is_Opened)
            self.camSh.change_pixmap_signal.connect(self._update_frame_shot)
            self.camSh.flagShot.connect(self._update_images_shot)

            self.camSh.start()
            self._update_log("GUI", "CamShot started", "")
        print("Finish update cameras")
        self.count = 0

    # ------------------------------------------------------------------
    #  System control
    # ------------------------------------------------------------------
    def _start_settings(self):
        # self.foo += 1
        self._start_system()
        if hasattr(self, "settings_window") and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
        else:
            self.settings_window.show()
        
    def _start_system(self, btn_start=False):
        self.arm1_comms = mp.Queue()
        self.arm2_comms = mp.Queue()
        self.settings_window.arm1_comms = self.arm1_comms
        self.settings_window.arm2_comms = self.arm2_comms
        
        # Arm 1 thread Init
        if (self.arm1_worker_thread is None):
            self.arm1_worker_thread = Arm_worker(0, self.arm1_comms, self.arm2_comms, self.capture_flag, self.batt_coords, 
                                                 self.arm1_status, self.arm2_status, self.start_system_flag, self.msg, self.msg_type)
        else:
            self.arm1_worker_thread.command = self.arm1_comms
            self.arm1_worker_thread.command_receive = self.arm2_comms
        # Arm 2 thread Init
        if (self.arm2_worker_thread is None):
            self.arm2_worker_thread = Arm_worker(1, self.arm2_comms, self.arm1_comms, self.capture_flag, self.batt_coords, 
                                                 self.arm1_status, self.arm2_status, self.start_system_flag, self.msg, self.msg_type)
        else:
            self.arm2_worker_thread.command = self.arm2_comms
            self.arm2_worker_thread.command_receive = self.arm1_comms

        # Start threads
        if not self.arm1_worker_thread.is_alive():
            self.arm1_worker_thread.start()
        if not self.arm2_worker_thread.is_alive():
            self.arm2_worker_thread.start()

        if btn_start:
            self.arm1_comms.put("connect")
            self.arm2_comms.put("connect")

        if self.arm1_status["enabled"] and self.arm2_status["enabled"]:
            self.start_system_flag.set()
        # Arms wait for detection_signal to receive coordinates
        
    def _stop_system(self, close=False):
        self.arm1_comms.put("stop")
        self.arm2_comms.put("stop")
        arm1 = self.stop_system_flag.value == 1 or self.stop_system_flag.value == 3
        arm2 = self.stop_system_flag.value == 2 or self.stop_system_flag.value == 3
        time.sleep(0.2)
        if close or arm1:
            if self.arm1_worker_thread:
                if self.arm1_worker_thread.is_alive(): 
                    self.arm1_worker_thread.worker_Running = False
                    time.sleep(0.2)
                psutil.Process(self.arm1_worker_thread.pid).kill()
            print("Arm 1 worker thread killed")
            self.arm1_worker_thread = None
            self.arm1_status.update({"connected": False, "powered": False, "enabled": False, "state": None})
        if close or arm2:
            if self.arm2_worker_thread:
                if self.arm2_worker_thread.is_alive(): 
                    self.arm2_worker_thread.worker_Running = False
                    time.sleep(0.2)
                psutil.Process(self.arm2_worker_thread.pid).kill()
            print("Arm 2 worker thread killed")
            self.arm2_worker_thread = None
            self.arm2_status.update({"connected": False, "powered": False, "enabled": False, "state": None})

        if not close: self._start_system()    
            
    def closeEvent(self, event):
        self.settings_window.close()
        for cam in (self.camPos, self.camSh):
            if cam.isRunning():
                cam.stop()
                cam.wait(100)
        self._stop_system(close=True)
        self.event_update.stop()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    #  Camera slots
    # ------------------------------------------------------------------
    def _update_frame_pos(self, frame):
        self.uic.lb_camPos.setPixmap(QPixmap.fromImage(frame))
        self.uic.lb_camPos.setScaledContents(True)

    def _update_frame_shot(self, frame):
        self.uic.lb_camShot.setPixmap(QPixmap.fromImage(frame))
        self.uic.lb_camShot.setScaledContents(True)

    def _update_images_shot(self, flag):
        if flag == "shot":
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{folder_cam}/{timestamp}.jpg"
            frame = self.camSh.getFrame()
            cv2.imwrite(path, frame)
            self.count = self.count + 1
            self._update_image(self.count, path)
            self.camSh.done_shot = True
            self._update_log("Shot", f"Shot face {self.count}", "")
            if self.count == 6:
                self.count = 0

    def _update_camera(self, reset_cam):
        if reset_cam == 1:
            cam = self.camPos
            if not cam.restart_thread:
                cam.stop()
            else:
                self._init_camera(0)
                self.reset_cam_flag.value = 0
                
        elif reset_cam == 2:
            cam = self.camSh
            if not cam.restart_thread:
                cam.stop()
            else:
                self._init_camera(1)
                self.reset_cam_flag.value = 0
                
    # ------------------------------------------------------------------
    #  Detection handler
    # ------------------------------------------------------------------
    def _handle_detection(self, coords):
        coords_list = coords.tolist() if hasattr(coords, "tolist") else list(coords)
        mini = ldr.cfg["mini"]
        if mini["max_x"] > coords_list[0] > mini["min_x"] and mini["max_y"] > coords_list[1] > mini["min_y"] and self.batt_coords[0] == -1:
            for i, v in enumerate(coords_list):
                self.batt_coords[i] = v
            print(f"coord changed: {coords_list}")
            self._update_log("Detector", f"Battery at {coords_list}", "")

    def _handle_status(self, msg):
        arm_id = msg.get("id")
        state = msg.get("state")
        self._update_log(f"Arm {arm_id}", state, "")
        if state == "arm1 finished":
            self.cmd_q2.put(state)
        elif state == "vac has turned off":
            self.cmd_q1.put(state)

    # ------------------------------------------------------------------
    #  Logging helper
    # ------------------------------------------------------------------
    def _update_log(self, source, message, other):
        tbl = self.uic.table_logger
        row = tbl.rowCount()
        tbl.insertRow(row)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tbl.setItem(row, 0, QTableWidgetItem(now))
        tbl.setItem(row, 1, QTableWidgetItem(source))
        tbl.setItem(row, 2, QTableWidgetItem(message))
        tbl.setItem(row, 3, QTableWidgetItem(other))
        self.uic.table_logger.scrollToBottom()

    def _update_image(self, number, path):
        label_map = {
            1: self.uic.lb_face_1,
            2: self.uic.lb_face_2,
            3: self.uic.lb_face_3,
            4: self.uic.lb_face_4,
            5: self.uic.lb_face_5,
            6: self.uic.lb_face_6,
        }

        label = label_map.get(number)
        if label:
            label.clear()
            label.setPixmap(QPixmap(path))

    def _update_element(self, element, attribute, value):
        element.setProperty(attribute, value)
        element.style().unpolish(element)
        element.style().polish(element)
        element.update()
        
    def _update_status(self):
        if self.stop_system_flag.value != 0:
            self._stop_system()
            self.stop_system_flag.value = 0

        self.settings_window._update_ui()
        self._update_camera(self.reset_cam_flag.value)
        arm_1_connected = self.arm1_status["connected"]
        arm_1_powered = self.arm1_status["powered"]
        arm_1_enabled = self.arm1_status["enabled"]
        arm_2_connected = self.arm2_status["connected"]
        arm_2_powered = self.arm2_status["powered"] 
        arm_2_enabled = self.arm2_status["enabled"]
        self._update_element(self.uic.led_arm_1_connect, "toggle", arm_1_connected)
        self._update_element(self.uic.led_arm_1_power, "toggle", bool(arm_1_powered))
        self._update_element(self.uic.led_arm_1_enable, "toggle", bool(arm_1_enabled))
        
        self._update_element(self.uic.led_arm_2_connect, "toggle", arm_2_connected)
        self._update_element(self.uic.led_arm_2_power, "toggle", bool(arm_2_powered))
        self._update_element(self.uic.led_arm_2_enable, "toggle", bool(arm_2_enabled))

        if self.arm1_status["state"] not in [None, "connect", "disconnect", "enable", "disable", "power_on", "power_off"]:
            self.uic.lb_arm_1_state.setText(self.arm1_status["state"])
        elif self.arm1_status["enabled"]:
            self.uic.lb_arm_1_state.setText("Enabled")
        elif self.arm1_status["powered"]:
            self.uic.lb_arm_1_state.setText("Powered on")
        elif self.arm1_status["connected"]:
            self.uic.lb_arm_1_state.setText("Connected")
        else:
            self.uic.lb_arm_1_state.setText("Disconnected")
            
        if self.arm2_status["state"] not in [None, "connect", "disconnect", "enable", "disable", "power_on", "power_off"]:
            self.uic.lb_arm_2_state.setText(self.arm2_status["state"])
        elif self.arm2_status["enabled"]:
            self.uic.lb_arm_2_state.setText("Enabled")
        elif self.arm2_status["powered"]:
            self.uic.lb_arm_2_state.setText("Powered on")
        elif self.arm2_status["connected"]:
            self.uic.lb_arm_2_state.setText("Connected")
        else:
            self.uic.lb_arm_2_state.setText("Disconnected")
                
        if not self.camPos_is_Opened.is_set():
            self.uic.lb_camPos.setPixmap(QPixmap())
        if not self.camSh_is_Opened.is_set():
            self.uic.lb_camShot.setPixmap(QPixmap())

        


# ╭────────────────────────────────────────────────────────────────────────────╮
# │                                 Entrypoint                                 │
# ╰────────────────────────────────────────────────────────────────────────────╯
if __name__ == "__main__":
    mp.freeze_support()
    mp.set_start_method("spawn", force=True)
    from engine import task_kill

    task_kill.clean()
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

# ------------------------------------------------------------------
#  Acknowledgements # Put here for backup :))))
# ------------------------------------------------------------------
# Mr. Hoang Duc Minh: Initial UI layout & logging table, Displaying camera captures, Gripper 3D model
# Nguyen Phuoc Khang: improve main UI, settings UI, configuration file managing, Cobot trajectory, Full system operation, Documentation, UI Tester, Project manager
# Tran Cao Cap: Battery detection, Aruco calibration, Defisheye, Refactor all system code, build executable, Documentation, -UX Tester, Project manager
# Hoang Ngoc An, Mr. Ngo Tien Tu: Detection model training, Data gathering
# All other interns: Data gathering, System assembly, Scratch code API