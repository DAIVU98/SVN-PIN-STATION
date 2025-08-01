import cv2
import numpy as np
import os
import time
import cv2
import numpy as np

def calibrate_camera(reset_cam_flag, idx=0, checkerboard=(9, 6), square_size=19.0, num_images=20, save_path="./camera/calib/camera_calib_1080z.npz"):
    objp = np.zeros((checkerboard[0]*checkerboard[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:checkerboard[0], 0:checkerboard[1]].T.reshape(-1, 2)
    objp *= square_size

    objpoints = []
    imgpoints = []

    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    collected = 0
    print("Starting calibration capture...")

    while collected < num_images:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, checkerboard,
            cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)

        if found:
            corners2 = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1),
                criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
            imgpoints.append(corners2)
            objpoints.append(objp)
            collected += 1
            print(f"Captured {collected}/{num_images}")

            cv2.drawChessboardCorners(frame, checkerboard, corners2, found)
            cv2.imshow("checkerboard", frame)
            cv2.waitKey(500)  # pause to let user move board

        cv2.imshow("Live Feed", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or cv2.getWindowProperty("Live Feed", cv2.WND_PROP_VISIBLE) < 1:
            print("⏹️ User stopped.")
            cap.release()
            cv2.destroyAllWindows()
            reset_cam_flag.value = 1
            return

    cap.release()
    cv2.destroyAllWindows()
    reset_cam_flag.value = 1

    print("Calibrating...")
    ret, K, D, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, gray.shape[::-1], None, None
    )

    print("\nCalibration complete.")
    print("RMS Reprojection Error:", ret)
    print("Camera Matrix K:\n", K)
    print("Distortion Coefficients D:\n", D)

    np.savez(save_path, K=K, D=D)
    print(f"💾 Saved calibration to: {save_path}")

def open_undistorted_view(reset_cam_flag, idx=0, load_path="./camera/calib/camera_calib_1080z.npz"):
    # Load saved calibration
    try:
        data = np.load(load_path)
        K = data['K']
        D = data['D']
    except Exception as e:
        print(f"❌ Failed to load calibration data: {e}")
        return
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame.")
        return

    h, w = frame.shape[:2]
    new_K, roi = cv2.getOptimalNewCameraMatrix(K, D, (w, h), 1, (w, h))
    map1, map2 = cv2.initUndistortRectifyMap(K, D, None, new_K, (w, h), 5)

    cv2.namedWindow("Undistorted View")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        undist = cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR)
        cv2.imshow("Undistorted View", undist)

        key = cv2.waitKey(1) & 0xFF
        if key == 27 or cv2.getWindowProperty("Undistorted View", cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    cv2.destroyAllWindows()
    reset_cam_flag.value = 1

if __name__ == "__main__":
    calibrate_camera(idx=0, save_path="./camera/calib/camera_calib_1080zzz.npz")