from math import radians as rad, pi
import engine.loader as ldr
while True:
    try: 
        from jkrc import jkrc
        break
    except: 
        ldr.show_error("Missing Dependency", "Your PC is missing Visual C++ Redistributable 2013 (x64). Download and install before proceeding.", lib_import=True)

from PyQt5.QtWidgets import QMessageBox

class Arm:
    def __init__(self, id, arm_status, msg, msg_type):
        self.id = id
        self.current_state = "running"

        # Read configuration and initialize all vars
        self.update_var()
        self.arm_status = arm_status
        self.status = None
        self.robot = None
        self.run = False
        self.msg = msg
        self.msg_type = msg_type
        #robot initialization
        # self.init_robot()
        
    def init_robot(self):
        self.robot = jkrc.RC(self.ip)
        print("Initializing Arm", self.ip)
        self.msg_type.append("information")
        self.msg.append(f"Initializing Arm {self.id + 1} at {self.ip}, please wait.")
        print(self.robot.login())
        print(self.robot.power_on())
        print(self.robot.enable_robot())
        
        self.status = self.robot.get_robot_status()
        print(self.status)
        #check whether robot is ready
        if len(self.status) > 1:
            self.arm_status.update({"connected": self.status[0] == 0, "powered": self.status[1][2], "enabled": self.status[1][3]})
            if self.status[1][2] and self.status[1][3]:  # Check if robot is powered on and enabled
                self.run = True
                print("Arm", self.id, "is ready.")

                # add tool, coords data
                self.update_robot()

                self.home()
            else:
                self.run = False
                msg = f"Failed to initialize Arm {self.id + 1} at {self.ip}. Please check the connection and power status."
                self.msg_type.append("critical")
                self.msg.append(msg)
                print(msg)
        else:
            self.arm_status.update({"connected": self.status[0] == 0, "powered": False, "enabled": False})
            self.run = False
            msg = f"Failed to initialize Arm {self.id + 1} at {self.ip}. Please check the connection and power status."
            self.msg_type.append("critical")
            self.msg.append(msg)
            print(msg)
        
    def update_status(self):
        self.status = self.robot.get_robot_status()
        self.arm_status.update({"connected": self.status[0] == 0, "powered": self.status[1][2], "enabled": self.status[1][3]})
        
    def update_var(self):
        ldr.reload_cfg()
        self.cfg = ldr.usr_cfg
        cfg = self.cfg["mini"][self.id]
        self.speed = cfg["speed"]
        self.speed_rad = cfg["speed_rad"]
        self.accel = cfg["accel"]
        self.accel_rad = cfg["accel_rad"]
        self.ip = cfg["ip"]

        self.arm_default_pos = [rad(i) for i in cfg["arm_default_pos"]]  # [J1, J2, J3, J4, J5, J6] in rad
        self.tcp_default_pos = cfg["tcp_default_pos"]  # [x, y, z, rx, ry, rz] in mm and rad
        self.tcp_end_pos = cfg["tcp_end_pos"]  # [x, y, z, rx, ry, rz] in mm and rad
        self.tcp_transfer_pos = cfg["tcp_transfer_pos"]

        self.tcp_offset = cfg["tcp_offset"]  # [x, y, z, rx, ry, rz] in mm and rad
        self.tcp_offset = self.tcp_offset[:3] + [rad(self.tcp_offset[i]) for i in range(3, 6)]  # Convert angles to radians

        self.user_coord = cfg["user_coord"]  # [x, y, z] in mm
        self.user_coord = self.user_coord[:3] + [rad(self.user_coord[i]) for i in range(3, 6)]

        self.tool = cfg["tool"]  # DO3 for vacuum pump

        if hasattr(self, "status") and self.status[0] == 0:
            self.update_robot()

    def update_robot(self):
        self.robot.set_user_frame_data(1, self.user_coord, "table_corner")
        self.robot.set_user_frame_id(1)
        self.robot.set_tool_data(1, self.tcp_offset, "TCP Tool")  # Set offset for tool 1
        self.robot.set_tool_id(1)  # Set tool ID to 1
        self.tcp_state(0)  # Disable gripper / VAC

    def home(self, speed=10, accel=5, log=False):
        if log: print("Home arm.")
        self.robot.joint_move_extend(self.arm_default_pos, 0, 1, speed, accel, 0.1)  # Move to default position

    def abort(self):
        try: self.robot.motion_abort()
        except: pass
        
    def tcp_state(self, state):
        self.robot.set_digital_output(self.id, self.tool, state)

    def take_object(self, start=None, end=None, speed=0, log=False, capture_count=0):
        # ╭────────────────────────────────────────────────────────────────────────────╮
        # │                              ARM 0 Process                                 │
        # ╰────────────────────────────────────────────────────────────────────────────╯
        if self.id == 0:
            if self.current_state == "running":
                if start is None:
                    raise Exception("No start position provided.")
                if end is None:
                    end = self.tcp_end_pos
                if speed == 0:
                    speed = self.speed
                if log: print("Taking object at", start, "ending at", end, "speed", speed)

                tcp_pos = self.tcp_default_pos[:3] + [rad(self.tcp_default_pos[i]) for i in range(3, 6)]
                end = end[:3] + [rad(end[i]) for i in range(3, 6)]
                transfer = self.tcp_transfer_pos[:3] + [rad(self.tcp_transfer_pos[i]) for i in range(3, 6)]

                if capture_count < 1:
                    # Move up to avoid collision
                    if log: print('Moving to', tcp_pos)
                    tcp_pos[0] = start[0]
                    tcp_pos[1] = start[1]
                    tcp_pos[2] += 25
                    self.robot.linear_move_extend(tcp_pos, 0, 0, self.speed, self.accel, 0.1)

                    # Move down to pick battery
                    tcp_pos[2] -= 25
                    if log: print('Moving down')
                    self.robot.linear_move_extend(tcp_pos, 0, 0, self.speed, self.accel, 0.1)
                    self.tcp_state(1)  # Activate gripper to pick battery

                    # Move up after picking battery
                    tcp_pos[2] += 25
                    if log: print('Moving up')
                    self.robot.linear_move_extend(tcp_pos, 0, 0, self.speed, self.accel, 0.1)

                    # Go to camera, capture first picture
                    if log: print('Moving to', end)
                    # calculate rotate angle, with 0->90deg (0->pi/2rad) constraint
                    end[4] = rad(-start[2]) if start[2] < 90 else rad(90 - start[2])
                    # With calculated angle, go to camera, capture first picture
                    joint_pos = self.robot.kine_inverse(self.robot.get_joint_position()[1], end)[1]
                    self.robot.joint_move_extend(joint_pos, 0, 1, self.speed_rad, self.accel_rad, 0.1)
                    return "capture"

                elif capture_count < 4:  # Go to camera, capture 3 more pics
                    if log: print('Turning 90 deg right:', capture_count)

                    # calculate rotate angle, with -pi rad ->pi rad constraint
                    end[4] = rad((-90) * capture_count +
                                 (-start[2] if start[2] < 90
                                  else 90 - start[2]))

                    self.robot.linear_move_extend(end, 0, 1, self.speed, self.accel, 0.1)
                    return "capture"

                # Go to transfer position
                if log: print('Moving to', transfer)
                transfer[5] -= rad(start[2] - 90) if start[2] < 90 else rad(start[2] + 90)
                joint_pos = self.robot.kine_inverse(self.robot.get_joint_position()[1], transfer)[1]
                self.robot.joint_move_extend(joint_pos, 0, 0, self.speed_rad, self.accel_rad, 0.1)

                self.current_state = "arm1 finished"
                return "arm1 finished"
        # ╭────────────────────────────────────────────────────────────────────────────╮
        # │                              ARM 1 Process                                 │
        # ╰────────────────────────────────────────────────────────────────────────────╯
        elif self.id == 1:
            if speed == 0:
                speed = self.speed
            transfer = self.tcp_transfer_pos[:3] + [rad(self.tcp_transfer_pos[i]) for i in range(3, 6)]
            transfer[1] += 40
            end = self.tcp_end_pos[:3] + [rad(self.tcp_end_pos[i]) for i in range(3, 6)]

            if self.current_state == "running":
                # Prepare to get battery
                if log: print('Moving to', transfer)
                self.robot.linear_move_extend(transfer, 0, 0, self.speed, self.accel, 0.1)

                # Get battery
                if log: print('Moving to', transfer)
                transfer[1] -= 40
                self.robot.linear_move_extend(transfer, 0, 1, self.speed, self.accel, 0.1)
                self.tcp_state(1)

                self.current_state = "vac off"  # Waits for signal to change state -> vac has turned off
                return "vac off"

            elif self.current_state == "vac has turned off":  # continue after vac has been turned off
                if capture_count == 0:
                    # Arm 1 go to camera
                    if log: print('Moving to', end)
                    self.robot.linear_move_extend(end, 0, 1, self.speed, self.accel, 0.1)
                    return "capture"
                elif capture_count == 1:
                    # Turn around for camera
                    if log: print('Turning around')
                    end[4] += pi
                    self.robot.linear_move_extend(end, 0, 1, self.speed, self.accel, 0.1)
                    return "capture"
                else:
                    self.current_state = "grip batt checked"
                    return "grip batt checked"

            elif self.current_state == "grip batt checked":
                # Move to battery tray, with given id in start
                batt_pos = [ldr.batt_matrix[int(start[3])][0][0], ldr.batt_matrix[int(start[3])][0][1], 35, pi, 0, 0]
                if log: print('Moving to', batt_pos)
                self.robot.linear_move_extend(batt_pos, 0, 0, speed, 700, 0.1)

                # Drop battery
                batt_pos = [ldr.batt_matrix[int(start[3])][0][0], ldr.batt_matrix[int(start[3])][0][1], 27, pi, 0, 0]
                if log: print('Dropping Battery')
                self.robot.linear_move_extend(batt_pos, 0, 1, self.speed, self.accel, 0.1)
                self.tcp_state(0)

                # Move up to avoid collision
                batt_pos = [ldr.batt_matrix[int(start[3])][0][0], ldr.batt_matrix[int(start[3])][0][1], 70, pi, 0, 0]
                self.robot.linear_move_extend(batt_pos, 0, 0, self.speed, self.accel, 0.1)

                # Go back home
                self.home()
                return "arm2 finished"


if __name__ == "__main__":
    arm1 = Arm(0)
    arm2 = Arm(1)
    # print(robot.get_tool_data(1))

    while arm1.run:
        spd = 0
        cmd = input("Enter command: ").strip().lower().split()
        print(len(cmd), cmd)
        if len(cmd) == 0:
            continue
        if cmd[0] == "quit" or cmd[0] == "python":
            break
        elif cmd[0] == "enable":
            arm1.robot.enable_robot()
        elif cmd[0] == "update":
            arm1.update_var(ldr.cfg, arm1.id)
            arm1.robot.set_tool_data(1, arm1.tcp_offset, "TCP VAC")
        elif cmd[0] == "clear":
            print('\n' * 10)
        elif cmd[0] == "stop":
            arm1.robot.jog_stop(-1)
        elif cmd[0] == "home":
            idx = cmd[1]
            if int(idx):
                arm2.home()
            else:
                arm1.home()
        elif cmd[0] == "pos":  # x, y, speed (optional)
            idx = int(cmd[1])
            try:
                log = int(cmd[-1])
            except:
                log = False
            if idx == 0:
                arm1.take_object(start=[float(cmd[2]), float(cmd[3]), float(cmd[4])], end=arm1.tcp_end_pos,
                                 log=log)  # (start (x, y), end (x, y))
            elif idx == 1:
                arm2.take_object(start=[float(cmd[2]), float(cmd[3]), float(cmd[4])], end=arm1.tcp_end_pos, log=log)
        elif cmd[0] == "move":
            if cmd[1] == "j":  # J_idx, mode, coord_frame, speed, unit_deg
                arm1.robot.jog(int(cmd[2]), 0, 1, 1000, rad(float(cmd[3])))
            elif cmd[1] == "js":  # [J1, J2, J3, J4, J5, J6], mode, speed
                joint_pos = [float(cmd[i]) for i in range(2, 8)]
                joint_pos = [joint_pos[i] / 180 * pi for i in range(6)]
                arm1.robot.joint_move_extend(joint_pos, 0, 0, 5, 1, 0.1)
            elif cmd[1] == "l":  # [x, y, z, rx, ry, rz], mode, is_block, speed
                tcp_pos = [float(cmd[2]), float(cmd[3]), float(cmd[4]), rad(float(cmd[5])), rad(float(cmd[6])),
                           rad(float(cmd[7]))]
                tcp_pos = [tcp_pos[i] + arm1.user_coord[i] for i in range(3)] + tcp_pos[3:]
                arm1.robot.linear_move(tcp_pos, 0, 0, 50)
            elif cmd[1] == "c":
                arm1.robot.linear_move([250, 150, 123, pi, 0, 0], 0, 1, 50)
                arm1.robot.circular_move([250, 200, 123, pi, 0, 0], [200, 200, 123, 0, 0, 0], 0, 1, 20, 100, 0.1)

    arm1.robot.disable_robot()  # disable robot
    arm1.robot.power_off()  # power off
    arm1.robot.logout()  # logout
    print("Robot has been powered off and logged out.")
