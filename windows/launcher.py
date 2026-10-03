"""Start NanoManager on Windows: run the panels server and open the control page in a window.

    python launcher.py                 localhost only (this PC)
    python launcher.py --share         also reachable from phones on your Wi-Fi
    python launcher.py --no-browser    just run the server

Your pairing, saved scenes and favourites live in %APPDATA%\\NanoManager.
Close the console window (or press Ctrl+C) to stop it.
"""
import os
import runpy
import socket
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("NANOLEAF_UI_PORT", "8765"))
URL = "http://127.0.0.1:%d" % PORT


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def answering():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def open_window():
    """An app-style window in Edge (on every Windows 10/11), else the default browser."""
    if os.name == "nt":
        try:
            if subprocess.call(["cmd", "/c", "start", "", "msedge", "--app=" + URL],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                return
        except OSError:
            pass
    webbrowser.open(URL)


def open_when_ready():
    for _ in range(60):
        if answering():
            open_window()
            return
        time.sleep(0.5)
    print("The server did not start; see the messages above.")


def main():
    args = sys.argv[1:]
    share = "--share" in args
    data = os.environ.get("NANOLEAF_DATA_DIR") or os.path.join(
        os.environ.get("APPDATA") or os.path.expanduser("~"), "NanoManager")
    os.environ["NANOLEAF_DATA_DIR"] = data
    os.environ["NANOLEAF_LISTEN"] = "0.0.0.0" if share else os.environ.get("NANOLEAF_LISTEN", "127.0.0.1")
    os.makedirs(data, exist_ok=True)

    if answering():                         # already running: just show it
        print("NanoManager is already running; opening it.")
        if "--no-browser" not in args:
            open_window()
        return

    print("NanoManager - control your Nanoleaf panels")
    print("  This window is the server. Close it to stop NanoManager.")
    print("  Control page:  " + URL)
    if share:
        ip = lan_ip()
        print("  From a phone on the same Wi-Fi:  http://%s:%d" % (ip or "<this PC's address>", PORT))
        print("  (Windows may ask to allow it through the firewall: choose Private networks.)")
    print("  Your data:     " + data)
    print("")
    if "--no-browser" not in args:
        threading.Thread(target=open_when_ready, daemon=True).start()
    sys.path.insert(0, HERE)
    runpy.run_path(os.path.join(HERE, "nanoleaf_server.py"), run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
