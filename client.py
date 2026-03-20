import socket
import threading
import sys

VERSION     = "Kartuineger v1.0"
STUDIO      = "by Rezoc Studio"
SERVER_HOST = "127.0.0.1"   # поменяйте на IP сервера при необходимости
SERVER_PORT = 5000
BUFFER_SIZE = 4096
MAX_MSG_LEN = 500
ENCODING    = "utf-8"

running = threading.Event()
running.set()


def clear_input_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def print_prompt() -> None:
    sys.stdout.write("Сообщение: ")
    sys.stdout.flush()

def receive_loop(sock: socket.socket) -> None:
    buf = ""
    try:
        while running.is_set():
            try:
                chunk = sock.recv(BUFFER_SIZE)
            except OSError:
                break

            if not chunk:
                break

            buf += chunk.decode(ENCODING, errors="replace")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip()
                if line:
                    clear_input_line()
                    print(line)
                    print_prompt()

    except Exception as e:
        if running.is_set():
            clear_input_line()
            print(f"[Ошибка] Поток приёма: {e}")
    finally:
        running.clear()
        clear_input_line()
        print("\n[Система] Соединение с сервером потеряно.")


def send_line(sock: socket.socket, text: str) -> bool:
    try:
        sock.sendall((text + "\n").encode(ENCODING))
        return True
    except OSError:
        return False


def input_loop(sock: socket.socket) -> None:
    print_prompt()
    try:
        while running.is_set():
            try:
                text = input()
            except EOFError:
                break

            if not running.is_set():
                break

            text = text.strip()

            if not text:
                print_prompt()
                continue

            if len(text) > MAX_MSG_LEN:
                print(f"[Система] Слишком длинное сообщение (макс. {MAX_MSG_LEN} символов).")
                print_prompt()
                continue

            if not send_line(sock, f"MSG {text}"):
                break

    except KeyboardInterrupt:
        pass
    finally:
        running.clear()

def login(sock: socket.socket) -> str | None:
    print("Введите ваш никнейм (до 32 символов):")
    while True:
        try:
            nick = input("Никнейм: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not nick:
            print("[Система] Никнейм не может быть пустым.")
            continue
        if len(nick) > 32:
            print("[Система] Никнейм слишком длинный (макс. 32 символа).")
            continue

        if not send_line(sock, f"JOIN {nick}"):
            print("[Система] Ошибка отправки никнейма.")
            return None

        return nick


def main() -> None:
    print(f"{'─' * 40}")
    print(f"  {VERSION}")
    print(f"  {STUDIO}")
    print(f"{'─' * 40}")
    print(f"Подключение к {SERVER_HOST}:{SERVER_PORT}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_HOST, SERVER_PORT))
    except ConnectionRefusedError:
        print(f"[Ошибка] Сервер недоступен ({SERVER_HOST}:{SERVER_PORT}).")
        sys.exit(1)
    except OSError as e:
        print(f"[Ошибка] Не удалось подключиться: {e}")
        sys.exit(1)

    print("Соединение установлено.\n")

    nick = login(sock)
    if nick is None:
        sock.close()
        sys.exit(0)

    recv_thread = threading.Thread(
        target=receive_loop,
        args=(sock,),
        daemon=True,
    )
    recv_thread.start()

    try:
        input_loop(sock)
    finally:
        running.clear()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        recv_thread.join(timeout=2)
        print("[Система] Вы вышли из чата.")


if __name__ == "__main__":
    main()
