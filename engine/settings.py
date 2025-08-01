import multiprocessing as mp
from copy import deepcopy
from io import StringIO
import sys
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
)
from engine.QCodeEditor import QCodeEditor, YAMLHighlighter

try:
    # ------------------------------------------------------------------
    #  Original lib imports
    # ------------------------------------------------------------------
    from resource.settingsUI import Ui_MainWindow
    from engine.QCodeEditor import QCodeEditor, YAMLHighlighter
    from engine.camera_calibration import calibrate_camera, open_undistorted_view
    import engine.loader as ldr
    os = ldr.os
    yaml = ldr.YAML()
    DEBUG = ldr.usr_cfg["main"]["debug"]
except:
    # ------------------------------------------------------------------
    #  Added lib imports trick after file relocation and refactoring
    # ------------------------------------------------------------------
    from QCodeEditor import QCodeEditor, YAMLHighlighter
    from camera_calibration import calibrate_camera, open_undistorted_view
    import loader as ldr
    os = ldr.os
    yaml = ldr.YAML()
    DEBUG = ldr.usr_cfg["main"]["debug"]
    path = ldr.PROJECT_ROOT

    import importlib.util
    from pathlib import Path

    # Absolute path to the file you want to import
    target_path = Path(__file__).resolve().parent.parent / "resource" / "settingsUI.py"

    # Load the module
    spec = importlib.util.spec_from_file_location("settingsUI", target_path)
    settingsUI = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settingsUI)

    # Use it!
    Ui_MainWindow = settingsUI.Ui_MainWindow

# ------------------------------------------------------------------
#  Actual Code
# ------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, arm1_status, arm2_status, arm1_comms, arm2_comms, camPos_is_Opened, camSh_is_Opened, stop_system_flag, reset_cam_flag, msg, msg_type):
        super().__init__()
        self.uic = Ui_MainWindow()
        self.uic.setupUi(self)
        # Create editor widgets (don't overwrite uic.lb_cfg)
        self.lb_cfg_editor = QCodeEditor(DISPLAY_LINE_NUMBERS=True, HIGHLIGHT_CURRENT_LINE=True)
        self.lb_usr_cfg_editor = QCodeEditor(DISPLAY_LINE_NUMBERS=True, HIGHLIGHT_CURRENT_LINE=True)
        self.read_only = True
        self.lb_cfg_editor.setReadOnly(self.read_only)

        # 🔥 Keep strong reference to highlighters!
        self.lb_cfg_highlighter = YAMLHighlighter(self.lb_cfg_editor.document())
        self.lb_usr_cfg_highlighter = YAMLHighlighter(self.lb_usr_cfg_editor.document())

        # Add editors to layout placeholders
        for container, editor in [
            (self.uic.lb_cfg, self.lb_cfg_editor),
            (self.uic.lb_usr_cfg, self.lb_usr_cfg_editor)
        ]:
            self.uic.gridLayout_pro = QVBoxLayout(container)
            self.uic.gridLayout_pro.setContentsMargins(0, 0, 0, 0)
            self.uic.gridLayout_pro.addWidget(editor)
        
        self.arm1_status = arm1_status
        self.arm2_status = arm2_status
        self.arm1_comms = arm1_comms
        self.arm2_comms = arm2_comms
        self.camPos_is_Opened = camPos_is_Opened
        self.camSh_is_Opened = camSh_is_Opened
        self.stop_system_flag = stop_system_flag # mp.Event
        self.reset_cam_flag = reset_cam_flag # mp.Value
        self.msg = msg # mp.Manager
        self.msg_type = msg_type # mp.Manager

        self.usr_cfg = deepcopy(ldr.usr_cfg)
        self.cfg = deepcopy(ldr.cfg)
        self._init_current_settings(self.usr_cfg)

        # Buttons
        # Arm Init
        self.uic.btn_arm_1_connect.clicked.connect(lambda: self._clicked(0, "connect"))
        self.uic.btn_arm_1_power.clicked.connect(lambda: self._clicked(0, "power"))
        self.uic.btn_arm_1_enable.clicked.connect(lambda: self._clicked(0, "enable"))
        
        self.uic.btn_arm_2_connect.clicked.connect(lambda: self._clicked(1, "connect"))
        self.uic.btn_arm_2_power.clicked.connect(lambda: self._clicked(1, "power"))
        self.uic.btn_arm_2_enable.clicked.connect(lambda: self._clicked(1, "enable"))
        
        # Arm Controls
        self.uic.btn_arm_1_home.clicked.connect(lambda: self._clicked(0, "home"))
        self.uic.btn_arm_1_stop.clicked.connect(lambda: self._clicked(0, "stop"))
        
        self.uic.btn_arm_2_home.clicked.connect(lambda: self._clicked(1, "home"))
        self.uic.btn_arm_2_stop.clicked.connect(lambda: self._clicked(1, "stop"))

        # Camera Controls
        self.uic.btn_clear_img.clicked.connect(lambda: self.clear_old_images(keep_latest=12))
        self.uic.btn_calib.clicked.connect(self._calibrate_camera)
        self.uic.btn_undistorted_view.clicked.connect(self._open_undistorted_view)
        
        # Main Controls
        self.uic.btn_apply.clicked.connect(self._apply_settings)
        self.uic.btn_cancel.clicked.connect(self._cancel_settings)
        self.uic.btn_reset.clicked.connect(self._reset_settings)

        # Tab controls
        self.previous_tab_index = self.uic.tab_mode.currentIndex()
        self.uic.tab_mode.currentChanged.connect(self._change_tab)

        # Advaced Settings
        self.uic.checkBox.toggled.connect(self._toggle_read_only)
        
    # ------------------------------------------------------------------
    #  Button Controls
    # ------------------------------------------------------------------
    def _clicked(self, sender_id, type):
        if DEBUG: print("Sending from Arm: ", sender_id, "msg: ", type)
        comms = self.arm2_comms if sender_id == 0 else self.arm1_comms
        status = self.arm1_status if sender_id == 0 else self.arm2_status
        if type == "connect":
            if status["connected"]:
                comms.put("disconnect")
            else:
                comms.put("connect")
        elif type == "power":
            if status["powered"]:
                comms.put("power_off")
            else:
                comms.put("power_on")
        elif type == "enable":
            if status["enabled"]:
                comms.put("disable")
            else:
                comms.put("enable")
        else: # Home, Stop, Update_var
            if type == "stop":
                self.stop_system_flag.value += sender_id + 1
            else:
                comms.put(type)
            # if type == "stop":
            #     self.stop_system_flag.set()

    def _change_tab(self):
        if self.previous_tab_index != self.uic.tab_mode.currentIndex():
            valid = self._read_settings()
            if valid:
                self._init_current_settings(self.usr_cfg)
            else:
                self.uic.tab_mode.setCurrentIndex(self.previous_tab_index)
                
            self.previous_tab_index = self.uic.tab_mode.currentIndex()

    def _toggle_read_only(self):
        self.read_only = not self.read_only
        self.lb_cfg_editor.setReadOnly(self.read_only)

    def _calibrate_camera(self):
        name = self.uic.calib_file_name.text().strip()
        if ldr.is_valid_filename(name=name, parent=self, directory=ldr.camera_calib):
            name += ".npz"
            calibrate_camera(self.reset_cam_flag, idx=ldr.usr_cfg["cam_pos"]["idx"], save_path=ldr.camera_calib / name)
            ldr.reload_cfg()
            self.uic.calib_file.clear()
            self.uic.calib_file.addItems(ldr.camera_calib_files)

    def _open_undistorted_view(self):
        open_undistorted_view(self.reset_cam_flag, idx=self.usr_cfg["cam_pos"]["idx"], load_path=ldr.camera_calib / self.uic.calib_file.currentText())
        
    # ------------------------------------------------------------------
    #  Logging helper
    # ------------------------------------------------------------------
    def _init_current_settings(self, cfg_file):
        mini = cfg_file["mini"]
        arm_1 = mini[0]
        arm_2 = mini[1]
        cam_pos = cfg_file["cam_pos"]
        self.uic.arm_1_ip.setText(arm_1["ip"])
        self.uic.arm_1_J_speed.setValue(arm_1["speed_rad"])
        self.uic.arm_1_L_speed.setValue(arm_1["speed"])
        self.uic.arm_1_J_accel.setValue(arm_1["accel_rad"])
        self.uic.arm_1_L_accel.setValue(arm_1["accel"])
        self.uic.arm_1_tcp_port.setValue(arm_1["tool"])
        # Arm 2
        self.uic.arm_2_ip.setText(arm_2["ip"])
        self.uic.arm_2_J_speed.setValue(arm_2["speed_rad"])
        self.uic.arm_2_L_speed.setValue(arm_2["speed"])
        self.uic.arm_2_J_accel.setValue(arm_2["accel_rad"])
        self.uic.arm_2_L_accel.setValue(arm_2["accel"])
        self.uic.arm_2_tcp_port.setValue(arm_2["tool"])
        # Cam Init
        self.uic.cam_pos_id.setValue(cfg_file["cam_pos"]["idx"])
        self.uic.cam_shot_id.setValue(cfg_file["cam_shot"]["idx"])
        # Cam Calib
        self.uic.calib_file.clear()
        self.uic.calib_file.addItems(ldr.camera_calib_files)
        self.uic.calib_file.setCurrentText(cam_pos["camera_calib"])
        # Cam Detect
        self.uic.yolo_model.clear()
        self.uic.yolo_model.addItems(ldr.detect_model_files)
        self.uic.yolo_model.setCurrentText(cam_pos["detect_model"])
        self.uic.frame_samples.setValue(cfg_file["main"]["frame_to_avg"])
        self.uic.confidence_thres.setValue(cam_pos["conf"])
        # Aruco
        self.uic.tag_size.setValue(cam_pos["tag_size"])
        self.uic.tag_L_dist.setValue(cam_pos["tray_length"])
        self.uic.tag_W_dist.setValue(cam_pos["tray_width"])
        # Constraints
        self.uic.upper_x_limit.setValue(mini["max_x"])
        self.uic.lower_x_limit.setValue(mini["min_x"])
        self.uic.upper_y_limit.setValue(mini["max_y"])
        self.uic.lower_y_limit.setValue(mini["min_y"])
        # Advanced Settings
        stream = StringIO()
        yaml.dump(self.usr_cfg, stream)
        self.lb_usr_cfg_editor.setPlainText(stream.getvalue())
        stream = StringIO()
        yaml.dump(self.cfg, stream)
        self.lb_cfg_editor.setPlainText(stream.getvalue())
        # Documentation
        ldr.load_markdown(self.uic.readMe)

    def _read_settings(self):
        if self.previous_tab_index == 0:
            mini = self.usr_cfg["mini"]
            arm_1 = mini[0]
            arm_2 = mini[1]
            cam_pos = self.usr_cfg["cam_pos"]
            # Arm 1
            arm_1["ip"] = self.uic.arm_1_ip.text()
            arm_1["speed"] = self.uic.arm_1_L_speed.value()
            arm_1["speed_rad"] = self.uic.arm_1_J_speed.value()
            arm_1["accel"] = self.uic.arm_1_L_accel.value()
            arm_1["accel_rad"] = self.uic.arm_1_J_accel.value()
            arm_1["tool"] = self.uic.arm_1_tcp_port.value()
            # Arm 2
            arm_2["ip"] = self.uic.arm_2_ip.text()
            arm_2["speed"] = self.uic.arm_2_L_speed.value()
            arm_2["speed_rad"] = self.uic.arm_2_J_speed.value()
            arm_2["accel"] = self.uic.arm_2_L_accel.value()
            arm_2["accel_rad"] = self.uic.arm_2_J_accel.value()
            arm_2["tool"] = self.uic.arm_2_tcp_port.value()
            # Cam Init
            self.usr_cfg["cam_pos"]["idx"] = self.uic.cam_pos_id.value()
            self.usr_cfg["cam_shot"]["idx"] = self.uic.cam_shot_id.value()
            # Cam Calib
            cam_pos["camera_calib"] = self.uic.calib_file.currentText()
            # Cam Detect
            cam_pos["detect_model"] = self.uic.yolo_model.currentText()
            self.usr_cfg["main"]["frame_to_avg"] = self.uic.frame_samples.value()
            cam_pos["conf"] = self.uic.confidence_thres.value()
            # Aruco
            cam_pos["tag_size"] = self.uic.tag_size.value()
            cam_pos["tray_length"] = self.uic.tag_L_dist.value()
            cam_pos["tray_width"] = self.uic.tag_W_dist.value()
            # Constraints
            mini["max_x"] = self.uic.upper_x_limit.value()
            mini["min_x"] = self.uic.lower_x_limit.value()
            mini["max_y"] = self.uic.upper_y_limit.value()
            mini["min_y"] = self.uic.lower_y_limit.value()

            stream = StringIO()
            yaml.dump(self.usr_cfg, stream)
            valid = ldr.validate_yaml(stream.getvalue(), reference_data=ldr.usr_cfg, parent=self)
            return valid # Can save
        elif self.previous_tab_index == 1:
            # Advanced Settings
            text = self.lb_usr_cfg_editor.toPlainText()
            valid_1 = ldr.validate_yaml(text, reference_data=ldr.usr_cfg, parent=self)
            if valid_1:
                self.usr_cfg = yaml.load(StringIO(text))
                
            text = self.lb_cfg_editor.toPlainText()
            valid_2 = ldr.validate_yaml(text, reference_data=ldr.cfg, parent=self)
            if valid_2:
                self.cfg = yaml.load(StringIO(text))
                
            return valid_1 and valid_2 # Can't save
        else:
            return True
            
    def _apply_settings(self):
        valid = self._read_settings()
        if valid:
            with open(ldr.usr_cfg_path, 'w', encoding='utf-8') as f:
                f.write(ldr.yaml_remove_blanks(self.usr_cfg))
            with open(ldr.cfg_path, 'w', encoding='utf-8') as f:
                f.write(ldr.yaml_remove_blanks(self.cfg))
            ldr.reload_cfg()
            
            self._clicked(0, "update_var")
            self._clicked(1, "update_var")

            if self.usr_cfg["cam_pos"]["camera_calib"] != ldr.usr_cfg["cam_pos"]["camera_calib"]:
                self.reset_cam_flag.value = 1
            return True
        else:
            return False

    def _apply_camera_settings(self):
        cam_pos_idx = self.usr_cfg["cam_pos"]["idx"]
        cam_shot_idx = self.usr_cfg["cam_shot"]["idx"]
        cam_pos_val = self.uic.cam_pos_id.value()
        cam_shot_val = self.uic.cam_shot_id.value()
        cam_pos_change = cam_pos_idx != cam_pos_val
        cam_shot_change = cam_shot_idx != cam_shot_val
        
        if cam_pos_change or cam_shot_change:
            self.usr_cfg["cam_pos"]["idx"] = cam_pos_val
            self.usr_cfg["cam_pos"]["idx"] += ((cam_pos_val > cam_pos_idx) - (cam_pos_val < cam_pos_idx)) * (cam_pos_val == cam_shot_val) # Ensure unique index
            self.usr_cfg["cam_shot"]["idx"] = cam_shot_val
            self.usr_cfg["cam_shot"]["idx"] += ((cam_shot_val > cam_shot_idx) - (cam_shot_val < cam_shot_idx)) * (cam_pos_val == cam_shot_val) # Ensure unique index
            
            self.uic.cam_pos_id.setValue(self.usr_cfg["cam_pos"]["idx"])
            self.uic.cam_shot_id.setValue(self.usr_cfg["cam_shot"]["idx"])
            with open(ldr.usr_cfg_path, 'w', encoding='utf-8') as f:
                f.write(ldr.yaml_remove_blanks(self.usr_cfg))

            ldr.reload_cfg()
        
        if cam_pos_change:
            self.reset_cam_flag.value = 1
        if cam_shot_change:
            self.reset_cam_flag.value = 2

    def _cancel_settings(self):
        self.usr_cfg = deepcopy(ldr.usr_cfg)
        self.cfg = deepcopy(ldr.cfg)
        self._init_current_settings(self.usr_cfg)

    def _reset_settings(self):
        self.usr_cfg = deepcopy(ldr.cfg)
        self.cfg = deepcopy(ldr.cfg)
        self._init_current_settings(self.cfg)
        self._apply_settings()

    def clear_old_images(self, keep_latest=12):
        folder = ldr.folder_cam
        # List all image files (you can refine the suffixes as needed)
        images = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        images.sort(reverse=True)
        # Skip the latest `keep_latest` images, delete the rest
        for image in images[keep_latest::]:
            path = os.path.join(folder, image)
            try:
                os.remove(path)
            except Exception as e:
                print(f"Failed to delete {image}: {e}")
    
    def _update_element(self, element, attribute, value):
        element.setProperty(attribute, value)
        element.style().unpolish(element)
        element.style().polish(element)
        element.update()

    def _update_ui(self):
        self._apply_camera_settings()
        # Arm 1
        self._update_element(self.uic.led_arm_1_connected, "toggle", self.arm1_status["connected"])
        self._update_element(self.uic.led_arm_1_powered, "toggle", bool(self.arm1_status["powered"]))
        self._update_element(self.uic.led_arm_1_enabled, "toggle", bool(self.arm1_status["enabled"]))
        # Arm 2
        self._update_element(self.uic.led_arm_2_connected, "toggle", self.arm2_status["connected"])
        self._update_element(self.uic.led_arm_2_powered, "toggle", bool(self.arm2_status["powered"]))
        self._update_element(self.uic.led_arm_2_enabled, "toggle", bool(self.arm2_status["enabled"]))
        # Cam
        self._update_element(self.uic.led_cam_pos_connected, "toggle", self.camPos_is_Opened.is_set())
        self._update_element(self.uic.led_cam_shot_connected, "toggle", self.camSh_is_Opened.is_set())
        # Error reports
        if self.msg_type and self.msg:
            title = self.msg_type.pop(0)
            msg = self.msg.pop(0)
            if title == "critical":
                QMessageBox(QMessageBox.Critical, "System Error", msg, QMessageBox.Ok, self).open()
            elif title == "information":
                QMessageBox(QMessageBox.Information, "Information", msg, QMessageBox.Ok, self).open()
                
            
    def closeEvent(self, event):
        self._read_settings()
        if self.usr_cfg != yaml.load(ldr.usr_cfg_path) or self.cfg != yaml.load(ldr.cfg_path):
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Unsaved Changes")
            msg_box.setText("You have unsaved changes. Do you want to save before closing?")
            msg_box.setIcon(QMessageBox.Warning)

            save_button = msg_box.addButton("Save and Close", QMessageBox.NoRole)
            discard_button = msg_box.addButton("Discard Changes", QMessageBox.NoRole)
            cancel_button = msg_box.addButton("Cancel", QMessageBox.NoRole)

            msg_box.setDefaultButton(cancel_button)
            msg_box.exec_()
            clicked = msg_box.clickedButton()

            if clicked == cancel_button:
                event.ignore()  # ❌ Cancel close
            elif clicked == discard_button:
                self._cancel_settings()
                event.accept()  # ✅ Discard and close
            elif clicked == save_button:
                valid = self._apply_settings()
                if valid:
                    event.accept()  # ✅ Saved and close
                else:
                    event.ignore()  # ❌ Validation failed
        else:
            event.accept()  # No changes

# ╭────────────────────────────────────────────────────────────────────────────╮
# │                                 Entrypoint                                 │
# ╰────────────────────────────────────────────────────────────────────────────╯
if __name__ == "__main__":
    
    mp.freeze_support()
    mp.set_start_method("spawn", force=True)
    from engine import task_kill
    task_kill.clean()
    
    arm1_status = mp.Manager().dict({
            "connected": False,
            "powered": False,
            "enabled": False,
            "state": None
            })
    arm2_status = mp.Manager().dict({
            "connected": False,
            "powered": False,
            "enabled": False,
            "state": None
            })
    arm1_comms = mp.Queue()
    arm2_comms = mp.Queue()
    camPos_is_Opened = mp.Event()
    camSh_is_Opened = mp.Event()
    stop_system_flag = mp.Value('i', 0)
    reset_cam_flag = mp.Value('i', 0)
    msg = mp.Manager().list()
    msg_type = mp.Manager().list()
    
    app = QApplication(sys.argv)
    win = MainWindow(arm1_status, arm2_status, arm1_comms, arm2_comms, camPos_is_Opened, camSh_is_Opened, stop_system_flag, reset_cam_flag, msg, msg_type)
    win.show()
    sys.exit(app.exec())
