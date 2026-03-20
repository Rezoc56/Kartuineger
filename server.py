import socket
import threading
import os
import time
from datetime import datetime

VERSION        = "Kartuineger v1.0"
STUDIO         = "by Rezoc Studio"
HOST           = "0.0.0.0"
PORT           = 5000
BUFFER_SIZE    = 4096
MAX_MSG_LEN    = 500          # максимальная длина сообщения
HISTORY_FILE   = "messages.txt"
HISTORY_SEND   = 20           # сколько последних сообщений отправлять при подключении
RATE_LIMIT_SEC = 0.5          # минимальный интервал между сообщениями (сек)
ENCODING       = "utf-8"

clients_lock   = threading.Lock()
file_lock      = threading.Lock()

clients: dict = {}

def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_last_messages(n: int = HISTORY_SEND) -> list[str]:
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with file_lock:
            with open(HISTORY_FILE, "r", encoding=ENCODING) as f:
                lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-n:]]
    except OSError:
        return []


def save_message(nick: str, text: str) -> None:
    line = f"[{timestamp()}] {nick}: {text}\n"
    try:
        with file_lock:
            with open(HISTORY_FILE, "a", encoding=ENCODING) as f:
                f.write(line)
    except OSError as e:
        log(f"[ОШИБКА] Не удалось записать в файл: {e}")


def send_to(conn: socket.socket, text: str) -> bool:
    try:
        conn.sendall((text + "\n").encode(ENCODING))
        return True
    except OSError:
        return False


def broadcast(message: str, exclude: socket.socket | None = None) -> None:
    dead = []
    with clients_lock:
        targets = list(clients.keys())
    for conn in targets:
        if conn is exclude:
            continue
        if not send_to(conn, message):
            dead.append(conn)
    for conn in dead:
        remove_client(conn)


def remove_client(conn: socket.socket) -> None:
    with clients_lock:
        info = clients.pop(conn, None)
    try:
        conn.close()
    except OSError:
        pass
    if info:
        nick = info.get("nick", "?")
        log(f"[-] Отключился: {nick}")
        broadcast(f"[Сервер] {nick} покинул чат.")

def handle_client(conn: socket.socket, addr: tuple) -> None:
    log(f"[+] Новое соединение: {addr}")

    buf = ""
    nick = None

    try:
        while True:
            try:
                chunk = conn.recv(BUFFER_SIZE)
            except OSError:
                break

            if not chunk:
                break

            buf += chunk.decode(ENCODING, errors="replace")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                if line.startswith("JOIN "):
                    if nick is not None:
                        continue
                    raw_nick = line[5:].strip()
                    if not raw_nick or len(raw_nick) > 32:
                        send_to(conn, "[Ошибка] Недопустимый никнейм.")
                        continue
                    with clients_lock:
                        taken = any(
                            c["nick"] == raw_nick
                            for c in clients.values()
                        )
                    if taken:
                        send_to(conn, "[Ошибка] Никнейм уже занят.")
                        continue

                    nick = raw_nick
                    with clients_lock:
                        clients[conn] = {"nick": nick, "last_msg_time": 0.0}

                    log(f"[JOIN] {nick} ({addr})")

                    history = read_last_messages(HISTORY_SEND)
                    if history:
                        send_to(conn, f"[Сервер] Последние {len(history)} сообщений:")
                        for msg in history:
                            send_to(conn, msg)
                    send_to(conn, f"[Сервер] Добро пожаловать, {nick}!")
                    broadcast(f"[Сервер] {nick} вошёл в чат.", exclude=conn)

                elif line.startswith("MSG "):
                    if nick is None:
                        send_to(conn, "[Ошибка] Сначала выполните JOIN.")
                        continue

                    text = line[4:]

                    if not text.strip():
                        continue

                    if len(text) > MAX_MSG_LEN:
                        send_to(conn, f"[Ошибка] Сообщение слишком длинное (макс. {MAX_MSG_LEN} символов).")
                        continue

                    now = time.monotonic()
                    with clients_lock:
                        last = clients.get(conn, {}).get("last_msg_time", 0.0)
                    if now - last < RATE_LIMIT_SEC:
                        send_to(conn, "[Ошибка] Слишком часто. Подождите немного.")
                        continue
                    with clients_lock:
                        if conn in clients:
                            clients[conn]["last_msg_time"] = now

                    formatted = f"[{timestamp()}] {nick}: {text}"
                    save_message(nick, text)
                    broadcast(formatted)

                elif line.startswith("GET_LAST "):
                    if nick is None:
                        send_to(conn, "[Ошибка] Сначала выполните JOIN.")
                        continue
                    try:
                        n = int(line[9:].strip())
                        n = max(1, min(n, 100))
                    except ValueError:
                        send_to(conn, "[Ошибка] Неверный формат GET_LAST.")
                        continue
                    history = read_last_messages(n)
                    send_to(conn, f"[Сервер] Последние {len(history)} сообщений:")
                    for msg in history:
                        send_to(conn, msg)

                else:
                    send_to(conn, "[Ошибка] Неизвестная команда.")

    except Exception as e:
        log(f"[ОШИБКА] Поток клиента {addr}: {e}")
    finally:
        remove_client(conn)

def main() -> None:
    print(f"{'─' * 40}")
    print(f"  {VERSION}")
    print(f"  {STUDIO}")
    print(f"{'─' * 40}")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
    except OSError as e:
        log(f"[КРИТИЧНО] Не удалось запустить сервер: {e}")
        return

    server.listen(50)
    log(f"Сервер запущен на {HOST}:{PORT}")

    try:
        while True:
            try:
                conn, addr = server.accept()
            except OSError:
                break

            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                daemon=True,
            )
            thread.start()
    except KeyboardInterrupt:
        log("Сервер остановлен.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
