from __future__ import annotations

import http.server
import socket
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox


def ip_local() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def puerto_libre() -> int:
    for p in range(8000, 8011):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            pass
        finally:
            s.close()
    raise RuntimeError("No hay puerto disponible entre 8000 y 8010.")


def main() -> None:
    raiz = Path(__file__).resolve().parents[1]
    processed = raiz / "data" / "processed"
    p = puerto_libre()

    def handler(*args, **kwargs):
        return http.server.SimpleHTTPRequestHandler(
            *args,
            directory=str(processed),
            **kwargs,
        )

    servidor = http.server.ThreadingHTTPServer(("0.0.0.0", p), handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    url = f"http://{ip_local()}:{p}/ca0001_modelo80_dashboard.html"
    url_pc = f"http://127.0.0.1:{p}/ca0001_modelo80_dashboard.html"

    v = tk.Tk()
    v.title("Monitor AFP para celular")
    v.geometry("610x330")
    v.resizable(False, False)

    tk.Label(v, text="Monitor AFP disponible en la red local", font=("Arial", 16, "bold")).pack(pady=18)
    tk.Label(v, text="Conecta el celular a la misma red Wi-Fi y abre:", font=("Arial", 11)).pack(pady=5)

    e = tk.Entry(v, width=55, font=("Arial", 12), justify="center")
    e.insert(0, url)
    e.configure(state="readonly")
    e.pack(pady=12)

    tk.Label(v, text="Mantén esta ventana abierta. Al cerrarla, el enlace deja de funcionar.", fg="#7a5300", wraplength=540).pack(pady=8)

    f = tk.Frame(v)
    f.pack(pady=12)

    def copiar() -> None:
        v.clipboard_clear()
        v.clipboard_append(url)
        v.update()
        messagebox.showinfo("Enlace copiado", "El enlace se copió.")

    def cerrar() -> None:
        servidor.shutdown()
        servidor.server_close()
        v.destroy()

    tk.Button(f, text="Copiar enlace", command=copiar, width=16).grid(row=0, column=0, padx=6)
    tk.Button(f, text="Abrir en esta PC", command=lambda: webbrowser.open(url_pc), width=16).grid(row=0, column=1, padx=6)
    tk.Button(f, text="Detener servidor", command=cerrar, width=16).grid(row=0, column=2, padx=6)

    v.protocol("WM_DELETE_WINDOW", cerrar)
    webbrowser.open(url_pc)
    v.mainloop()


if __name__ == "__main__":
    main()
