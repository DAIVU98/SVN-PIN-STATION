import multiprocessing as mp
import time
from engine.move_mini_cobot import Arm
import engine.loader as ldr

DEBUG=ldr.usr_cfg["main"]["debug"]

class Arm_worker(mp.Process):
    def __init__(self, id, command: mp.Queue, command_receive: mp.Queue, capture: mp.Event, batt_coords: mp.Array, 
                 arm1_status: mp.Manager, arm2_status: mp.Manager, start_system_flag: mp.Event, msg: mp.Manager, msg_type: mp.Manager):
        super().__init__(daemon=True)
        self.id = id
        self.worker_Running = False
        self.is_Running = False  # Arm 1 starts running, Arm 2 waits for command
        self.start_system_flag = start_system_flag
        self.msg = msg
        self.msg_type = msg_type
        self.batt_coords = batt_coords
        for i in range(4):
            self.batt_coords[i] = -1
        self.command = command
        self.command_receive = command_receive
        self.capture = capture
        self.capture_count = 0
        self.batt_id = 1

        # Here for more controls
        self.arm1_status = arm1_status
        self.arm2_status = arm2_status

        # Put here for ease of use
        self.arm_status = arm1_status if self.id == 0 else arm2_status
        if DEBUG: print("Initializing Arm_worker", id)

    def run(self):
        self.arm = Arm(self.id, self.arm_status, self.msg, self.msg_type)
        self.worker_Running = True
        curTime = time.time()
        if DEBUG: print("Worker", self.id, "started:", self.worker_Running)
        while self.worker_Running:
            if self.id == 0 and self.start_system_flag.is_set():
                self.is_Running = True
                self.start_system_flag.clear()
                
            # ╭────────────────────────────────────────────────────────────────────────────╮
            # │                           Receive command                                  │
            # ╰────────────────────────────────────────────────────────────────────────────╯
            try:
                # command_receive = self.command_receive.get_nowait()
                command_receive = self.command_receive.get(timeout=0.1)  # this command is somehow more consistent
            except:
                command_receive = None
            if command_receive != None:
                if self.id == 0: # If arm 1 receives it, that means arm 2 is in this state
                    self.arm2_status["state"] = command_receive
                else:
                    self.arm1_status["state"] = command_receive
                if DEBUG: print("Arm", self.arm.id, "has received command:", command_receive)
                if DEBUG: print("Got command after", time.time() - curTime)
            else:
                curTime = time.time()
            # ╭────────────────────────────────────────────────────────────────────────────╮
            # │                         Arm 1 command receiver block                       │
            # ╰────────────────────────────────────────────────────────────────────────────╯

            # Arm 2 requests arm 1 to turn off the VAC
            if command_receive == "vac off":
                self.command.put("get batt info")  # Arm 1 requests arm 2 to get batt info before deleting it
                self.arm.tcp_state(0)  # turn off VAC
                time.sleep(0.1)
                # Trigger the reset state
                # Allows the handle detection function to get new coords right after homing
                self.arm.current_state = "reset batt info"
                self.arm.home()
                self.command.put("vac has turned off")  # Safe for arm 2 to continue

            # Arm 1 will continue when arm 2 begin to move to battery tray, ensure safety
            elif command_receive == "grip batt checked":
                self.arm.current_state = "continue"

            # ╭────────────────────────────────────────────────────────────────────────────╮
            # │                         Arm 2 command receiver block                       │
            # ╰────────────────────────────────────────────────────────────────────────────╯
            elif command_receive == "arm1 finished":
                print(f"batt id right now is {self.batt_id}")
                self.is_Running = True
                self.arm.current_state = "running"
            elif command_receive == "get batt info":
                self.batt_id = self.batt_coords[3]
                print(f"batt id changed to {self.batt_id}")
                self.command.put("get batt info success")
            elif command_receive == "vac has turned off":
                self.arm.current_state = "vac has turned off"

            # ╭────────────────────────────────────────────────────────────────────────────╮
            # │                         Both arm run block                                 │
            # ╰────────────────────────────────────────────────────────────────────────────╯
            # Both Arms check for run flag
            # Only arm 1 will check for battery coordinates, -1 will be the halt value
            if self.is_Running and (self.id == 1 or (self.id == 0 and self.batt_coords[0] != -1)):
                self.state = ""
                if not self.capture.is_set():  # Halt loop when capture is requested
                    # Testing states and UI state update
                    # self._test_states()
                    try:
                        self.state = self.arm.take_object(
                            start=[self.batt_coords[0], self.batt_coords[1], self.batt_coords[2], self.batt_id], log=False,
                            capture_count=self.capture_count)
                    except:
                        self.state = "Couldn't proceed to next stage"
                    # Emit the command to other arm as "state"
                    if DEBUG: print("Arm", self.arm.id, "has sent command:", self.state)
                    self.command.put(self.state)

                # Reset Arm 2 parameters
                if self.state == "arm2 finished":
                    self.is_Running = False
                    self.capture_count = 0

                # Arm 1 will reset the battery info back to -1 when arm 2 got battery info
                if self.arm.current_state == "reset batt info":
                    for i in range(4):
                        self.batt_coords[i] = -1
                    print("reset to -1")
                # Reset arm 1 parameters, allow arm 1 to run
                if self.arm.current_state == "continue":
                    self.capture_count = 0
                    self.is_Running = True
                    self.arm.current_state = "running"

                # If capture is requested, set the capture flag and halt loop
                elif self.state == "capture":
                    self.capture.set()
                    self.capture_count += 1
                    if DEBUG: print("Capture started")

            # ╭────────────────────────────────────────────────────────────────────────────╮
            # │                              Control block                                 │
            # ╰────────────────────────────────────────────────────────────────────────────╯
            try:
                if (command_receive == "stop"):
                    self.arm.abort()
                    self.arm.tcp_state(0)
                elif (command_receive == "home"):
                    self.arm.home()
                elif (command_receive == "update_var"):
                    self.arm.update_var() 
                elif (command_receive == "connect"):
                    self.arm.init_robot()
                    try: self.arm.tcp_state(0)
                    except: print("TCP failed. Arm not connected")
                elif (command_receive == "disconnect"):
                    self.arm_status["state"] = None
                    try: self.arm.tcp_state(0)
                    except: print("TCP failed. Arm not connected")
                    self.arm.robot.disable_robot()
                    time.sleep(1)
                    self.arm_status["enabled"] = False
                    self.arm.robot.power_off()
                    time.sleep(1)
                    self.arm_status["powered"] = False
                    self.arm.robot.logout()
                    self.arm.robot = None
                    self.arm_status["connected"] = False
                elif (command_receive == "power_on"):
                    self.arm.robot.power_on()
                elif (command_receive == "power_off"):
                    self.arm.robot.disable_robot()
                    time.sleep(1)
                    self.arm.robot.power_off()
                elif (command_receive == "enable"):
                    self.arm.robot.enable_robot()
                elif (command_receive == "disable"):
                    self.arm.robot.disable_robot()
            except: pass
                
            try: self.arm.update_status()
            except: pass
            
    def stop(self):
        self.is_Running = False

    def _test_states(self):
        time.sleep(2)
        if self.id == 0 and self.arm.current_state == "running":
            if self.capture_count >= 4:
                self.state = "arm1 finished"
            else:
                self.state = "capture"
        elif self.id == 1:
            if self.arm.current_state == "grip batt checked":
                self.state = "arm2 finished"
            elif self.capture_count > 1 and self.arm.current_state == "vac has turned off":
                self.state = "grip batt checked"
                self.arm.current_state = "grip batt checked"
            elif self.capture_count <= 1 and self.arm.current_state == "vac has turned off": 
                self.state = "capture"
            elif self.arm.current_state == "running":
                self.state = "vac off"
        time.sleep(2)
        