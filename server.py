import socket
import threading
import datetime
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from collections import deque

HOST = "127.0.0.1"   # Server IP
PORT = 12345         # Server 監聽 Port
MAX_CLIENTS = 3      # 最大同時連線人數

clients = {}        # 保存已連線的 client，格式：socket -> (username, addr)
recent_msgs = {}    # 保存每個使用者最近的訊息，用 deque 限制長度，格式：username -> deque(maxlen=3) 保存 (mid, text)
msg_id_counter = 0  # 全局訊息 ID 計數器
lock = threading.Lock()  # 多線程鎖，保護 msg_id_counter

# -------------------------------
# GUI
# -------------------------------
root = tk.Tk()
root.title("Chatroom Server")

# 聊天顯示區，禁止使用者點擊或編輯
log_box = ScrolledText(root, width=70, height=30, state="disabled")
log_box.pack(side=tk.LEFT)

def disable_click(e):
    """禁止點擊聊天區"""
    return "break"

log_box.bind("<Button-1>", disable_click)
log_box.bind("<Button-2>", disable_click)
log_box.bind("<Button-3>", disable_click)

# 顯示在線使用者列表
user_listbox = tk.Listbox(root, width=30)
user_listbox.pack(side=tk.RIGHT, fill=tk.Y)
user_listbox.config(state="disabled")

def gui_log(msg):
    """在 GUI 上插入訊息"""
    log_box.config(state="normal")
    log_box.insert(tk.END, msg + "\n")
    log_box.config(state="disabled")
    log_box.see(tk.END)

def update_user_list():
    """刷新使用者列表"""
    user_listbox.config(state="normal")
    user_listbox.delete(0, tk.END)
    for username, addr in clients.values():
        user_listbox.insert(tk.END, f"{username} {addr[0]}:{addr[1]}")
    user_listbox.config(state="disabled")

def timestamp():
    """取得當前時間字串 [HH:MM:SS]"""
    return datetime.datetime.now().strftime("[%H:%M:%S]")

# -------------------------------
# 廣播訊息給所有 client
# -------------------------------
def broadcast(msg, exclude=None):
    """
    將訊息廣播給所有 client
    exclude: 排除特定 socket，不發給他
    """
    for c in list(clients.keys()):
        if c != exclude:
            try:
                c.send(msg.encode())
            except:
                pass

def broadcast_remove(msg_id):
    """廣播收回訊息指令給所有 client"""
    cmd = f"__REMOVE__::{msg_id}"
    for c in list(clients.keys()):
        try:
            c.send(cmd.encode())
        except:
            pass

# -------------------------------
# 處理單一 client 連線
# -------------------------------
def handle_client(sock, addr):
    global msg_id_counter
    username = None
    try:
        # 先要求使用者輸入名稱
        sock.send("Enter your username: ".encode())

        # 使用者登入流程
        while True:
            username = sock.recv(1024).decode().strip()
            if not username:
                continue

            # 超過最大連線數
            if len(clients) >= MAX_CLIENTS:
                gui_log(f"{timestamp()} Connection attempt from {addr} rejected: Maximum connections reached.")
                try:
                    sock.send(f"SERVER_REJECT::{timestamp()} #Server: Unable to connect to server: Maximum connections reached.".encode())
                except:
                    pass
                sock.close()
                return

            # 名稱重複
            if username in [u for u,_ in clients.values()]:
                try:
                    sock.send("Name already in use. Please enter a different name.".encode())
                except:
                    pass
                continue

            # 註冊成功
            clients[sock] = (username, addr)
            recent_msgs[username] = deque(maxlen=3)

            # GUI 顯示新連線
            gui_log(f"{timestamp()} New connection from {addr}")
            gui_log(f"{timestamp()} {username} has joined the chat.")
            # 廣播給其他 client
            broadcast(f"{timestamp()} #Server: {username} has joined the chat.")
            # 發送登入成功訊息給該 client
            try:
                sock.send(f"SERVER_WELCOME::{username}".encode())
            except:
                pass

            update_user_list()
            break

        # -------------------------------
        # 主迴圈：接收 client 訊息
        # -------------------------------
        while True:
            data = sock.recv(4096).decode().strip()
            if not data:
                continue

            # 使用者正常離開
            if data == "exit":
                gui_log(f"{timestamp()} {username} has left the chat.")
                broadcast(f"{timestamp()} #Server: {username} has left the chat.", exclude=sock)
                try:
                    sock.send("CLIENT_EXIT::You left the chat. Disconnected from server.".encode())
                except:
                    pass
                break

            # -------------------------------
            # 收回訊息
            # -------------------------------
            if data.startswith("UNDO_ID::"):
                target = data.split("::",1)[1]
                # server 檢查是否在最近訊息內
                if any(str(mid) == str(target) for mid, _ in recent_msgs[username]):
                    # 刪掉 recent_msgs 中該 ID
                    recent_msgs[username] = deque([(mid,t) for mid,t in recent_msgs[username] if str(mid) != str(target)], maxlen=3)
                    broadcast_remove(target)
                    gui_log(f"{timestamp()} {username} retracted message #{target}")
                else:
                    try:
                        sock.send("Cannot retract this message.".encode())
                    except:
                        pass
                continue

            # -------------------------------
            # 私訊
            # -------------------------------
            if data.startswith("@"):
                parts = data.split(" ",1)
                if len(parts) < 2:
                    try:
                        sock.send("Usage: @username message".encode())
                    except:
                        pass
                    continue
                target_name, msg_text = parts[0][1:], parts[1]
                target_sock = None
                for c, (uname, _) in clients.items():
                    if uname == target_name:
                        target_sock = c
                        break

                # 生成訊息 ID
                with lock:
                        msg_id_counter += 1
                        mid = msg_id_counter

                # 限制 recent_msgs 長度
                if len(recent_msgs[username]) > 3:
                    recent_msgs[username].pop(0)

                # 格式化訊息
                formatted = f"{timestamp()} #{mid} (Private) {username} → {target_name}: {msg_text}"
                recent_msgs[username].append((mid, msg_text))
                if target_sock:
                    try:                        
                        target_sock.send(formatted.encode())
                        sock.send(formatted.encode())
                    except:
                        pass
                    gui_log(formatted)
                else:
                    try:
                        sock.send(f"User {target_name} not found.".encode())
                    except:
                        pass
                continue

            # -------------------------------
            # 一般訊息（帶 ID）
            # -------------------------------
            with lock:
                msg_id_counter += 1
                mid = msg_id_counter

            recent_msgs[username].append((mid, data))
            formatted = f"{timestamp()} #{mid} {username}: {data}"
            gui_log(f"{timestamp()} #{mid} {username} sent: {data}")
            broadcast(formatted)

    except Exception as e:
        gui_log(f"{timestamp()} Error with {addr}: {e}")

    finally:
        # 清理 client
        if sock in clients:
            uname, _ = clients[sock]
            gui_log(f"{timestamp()} {uname} disconnected.")
            # 刪除資料
            try:
                del recent_msgs[uname]
            except:
                pass
            try:
                del clients[sock]
            except:
                pass
            update_user_list()

        try:
            sock.close()
        except:
            pass

# -------------------------------
# 啟動 server
# -------------------------------
def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    gui_log(f"{timestamp()} Server started on ({HOST}, {PORT})")

    def accept_loop():
        """接受連線迴圈，每個 client 用新 thread 處理"""
        while True:
            sock, addr = server.accept()
            threading.Thread(target=handle_client, args=(sock, addr), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()

start_server()
root.mainloop()