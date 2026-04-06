import socket
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import re
import time

HOST = "127.0.0.1"   # 伺服器 IP
PORT = 12345         # 伺服器 Port

# message_list: 保存所有顯示在聊天區的訊息，格式 (id_or_None, text)
# 保留訊息順序，id_or_None 用來做訊息收回識別
message_list = []
clicked_id = None     # 右鍵點擊時選中的訊息 ID
my_username = None    # 這個 client 的使用者名稱

# -------------------------------
# GUI
# -------------------------------
root = tk.Tk()
root.title("Chatroom Client")

# 顯示 Username 的 Label，初始為空
username_label = tk.Label(root, text="Username: ", font=("Arial", 12))
username_label.pack(pady=(5,0))

# 聊天顯示區，使用 ScrolledText 可滾動
text_area = ScrolledText(root, width=60, height=25, state="disabled", wrap="word")
text_area.pack()

# 防止使用者選取文字或拖曳
def disable_left(e):
    return "break"

text_area.bind("<Button-1>", disable_left)
text_area.bind("<Button-2>", disable_left)

# 輸入訊息的 Entry
entry = tk.Entry(root, width=50)
entry.pack(side=tk.LEFT, padx=5)
entry.focus_set()  # 啟動時自動 focus 在輸入框

# 右鍵選單（延後顯示，由 on_right_click 控制）
menu = tk.Menu(root, tearoff=0)
def recall_action():
    """右鍵選單執行：收回訊息"""
    global clicked_id
    if clicked_id:
        try:
            # 發送收回訊息指令給 server
            client.send(f"UNDO_ID::{clicked_id}".encode())
        except:
            pass
menu.add_command(label="收回訊息", command=recall_action)

# -------------------------------
# GUI 更新封裝（安全從 thread 呼叫）
# -------------------------------

def gui_insert(msg):
    """在聊天區插入訊息（安全從 thread 呼叫）"""
    root.after(0, lambda: _insert_text(msg))

def _insert_text(msg):
    """實際插入訊息"""
    text_area.config(state="normal")
    text_area.insert(tk.END, msg + "\n")
    text_area.config(state="disabled")
    text_area.see(tk.END)  # 滾動到底部

def gui_refresh():
    """刷新整個訊息列表（保留順序）"""
    root.after(0, _refresh_display)

def _refresh_display():
    """實際刷新聊天區內容"""
    text_area.config(state="normal")
    text_area.delete("1.0", tk.END)
    for mid, msg in message_list:
        text_area.insert(tk.END, msg + "\n")
    text_area.config(state="disabled")
    text_area.see(tk.END)

def gui_set_username(name):
    """設定 Username Label"""
    root.after(0, lambda: username_label.config(text=f"Username: {name}"))

def gui_close_with_message(msg, delay=3):
    """顯示訊息後延遲關閉視窗"""
    def _show_and_close():
        _insert_text(msg)
        root.update()
        time.sleep(delay)
        root.destroy()
    threading.Thread(target=_show_and_close, daemon=True).start()

# -------------------------------
# 右鍵處理：找出被點擊行的 ID（若有）
# -------------------------------
def on_right_click(event):
    """
    取得被右鍵點擊的行文字，檢查是否有 #ID
    如果有，設定 clicked_id 並顯示右鍵選單
    """
    global clicked_id
    try:
        index = text_area.index(f"@{event.x},{event.y}")  # e.g. "12.0"
        # 取得整行文字
        line_start = index.split(".")[0] + ".0"
        line_end = index.split(".")[0] + ".end"
        line_text = text_area.get(line_start, line_end)
        m = re.search(r"#(\d+)", line_text)
        if m:
            clicked_id = m.group(1)  # 找到 ID
            menu.post(event.x_root, event.y_root)  # 顯示右鍵選單
        else:
            clicked_id = None
            # 沒 ID 的訊息不顯示選單
    except Exception:
        clicked_id = None

text_area.bind("<Button-3>", on_right_click)  # 右鍵綁定

# -------------------------------
# Networking
# -------------------------------
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))

def receive_loop():
    """
    接收 server 訊息迴圈
    - SERVER_WELCOME:: 登入成功
    - SERVER_REJECT:: 連線被拒
    - CLIENT_EXIT:: 離開指令
    - __REMOVE__:: 收回訊息
    - #ID 訊息（普通訊息或私訊帶 ID）
    - 其他訊息（無 ID）
    """
    global message_list, my_username
    try:
        while True:
            data = client.recv(4096).decode()
            if not data:
                continue

            # 登入成功 welcome -> 設 username label
            if data.startswith("SERVER_WELCOME::"):
                name = data.split("::",1)[1]
                my_username = name
                gui_set_username(name)
                # 同時加入聊天區顯示登入訊息（無 ID，Server 系統訊息）
                message_list.append((None, f"{time.strftime('[%H:%M:%S]')} #Server: You are logged in as {name}"))
                gui_refresh()
                continue

            # server 拒絕連線
            if data.startswith("SERVER_REJECT::"):
                msg = data.split("::",1)[1]
                gui_close_with_message(msg, delay=3)
                return

            # server 指示 client 離開
            if data.startswith("CLIENT_EXIT::"):
                msg = data.split("::",1)[1]
                gui_close_with_message(msg, delay=3)
                return

            # 收回訊息指令
            if data.startswith("__REMOVE__::"):
                mid = data.split("::",1)[1]
                # 刪除 message_list 中所有該 ID 訊息
                message_list[:] = [(m,t) for (m,t) in message_list if (m is None or str(m) != str(mid))]
                gui_refresh()
                continue

            # 帶 ID 的訊息
            m = re.search(r"#(\d+)", data)
            if m:
                mid = m.group(1)
                message_list.append((mid, data))
                gui_refresh()
                continue

            # 其他訊息（無 ID，例如 server 系統訊息）
            message_list.append((None, data))
            gui_refresh()

    except Exception:
        gui_close_with_message("Disconnected from server.", delay=3)

threading.Thread(target=receive_loop, daemon=True).start()

# -------------------------------
# 發送訊息
# -------------------------------
def send_message():
    """從 Entry 取得訊息，發送給 server"""
    msg = entry.get().strip()
    entry.delete(0, tk.END)
    if not msg:
        return
    try:
        client.send(msg.encode())
    except Exception:
        gui_close_with_message("Disconnected (send failed).", delay=3)

btn = tk.Button(root, text="Send", command=send_message)
btn.pack(side=tk.LEFT)

root.mainloop()