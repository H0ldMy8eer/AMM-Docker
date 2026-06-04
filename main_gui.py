import customtkinter as ctk
import tkinter
from tkinter import filedialog, messagebox
import threading
import shutil
import sys
import os
import subprocess
import webbrowser
import urllib.request
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

import generator
import scanner


class AMMApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("AMM-Docker")
        window_width = 500
        window_height = 720
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = max(30, (screen_height // 2) - (window_height // 2))
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.minsize(450, 650)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Заголовок ---
        ctk.CTkLabel(self, text="AMM-DOCKER", font=("Roboto", 32, "bold")).pack(pady=(40, 0))
        ctk.CTkLabel(self, text="Migration Assistant", font=("Roboto", 14), text_color="gray").pack(pady=(0, 15))

        # --- Путь к монолиту ---
        ctk.CTkLabel(self, text="Путь к монолиту:", font=("Roboto", 13, "bold")).pack(anchor="w", padx=40, pady=(5, 0))
        self.path_entry = ctk.CTkEntry(self, placeholder_text="Выберите папку с кодом...", height=40)
        self.path_entry.pack(padx=40, pady=5, fill="x")
        ctk.CTkButton(self, text="📂 ВЫБРАТЬ ПАПКУ", fg_color="#3b3b3b", hover_color="#4b4b4b",
                      height=40, command=self.browse_source).pack(padx=40, fill="x")

        # --- Кнопка сканирования (всегда видна) ---
        self.scan_btn = ctk.CTkButton(
            self, text="СКАНИРОВАТЬ",
            fg_color="#0d6efd", hover_color="#0b5ed7",
            font=("Roboto", 15, "bold"), height=45,
            command=self.start_scan
        )
        self.scan_btn.pack(padx=40, pady=10, fill="x")

        # --- Прогресс-бар (скрыт по умолчанию) ---
        self.progress_bar = ctk.CTkProgressBar(self, mode="indeterminate", height=6)
        self.progress_label = ctk.CTkLabel(
            self, text="", font=("Roboto", 11), text_color="#5DADE2"
        )

        # --- Динамические кнопки (появляются после сканирования) ---
        self.generate_btn = ctk.CTkButton(
            self, text="⚙️ ГЕНЕРИРОВАТЬ",
            fg_color="#28a745", hover_color="#218838",
            font=("Roboto", 14, "bold"), height=42,
            command=self.start_generation
        )

        self.regen_btn = ctk.CTkButton(
            self, text="🔄 ПЕРЕГЕНЕРИРОВАТЬ",
            fg_color="#5c636a", hover_color="#494f54",
            font=("Roboto", 13, "bold"), height=38,
            command=self.start_generation
        )

        # Блок управления Docker
        self.docker_frame = ctk.CTkFrame(self)
        ctk.CTkLabel(self.docker_frame, text="Управление Docker", font=("Roboto", 13, "bold")).pack(pady=(5, 5))
        docker_btns = ctk.CTkFrame(self.docker_frame, fg_color="transparent")
        docker_btns.pack(pady=(0, 10), fill="x", padx=10)
        ctk.CTkButton(docker_btns, text="▶️ Поднять", fg_color="#007bff", hover_color="#0056b3",
                      height=40, command=self.docker_up).pack(side="left", expand=True, padx=5)
        ctk.CTkButton(docker_btns, text="⏹ Остановить", fg_color="#dc3545", hover_color="#c82333",
                      height=40, command=self.docker_down).pack(side="right", expand=True, padx=5)

        # Кнопка карты зависимостей
        self.map_btn = ctk.CTkButton(
            self, text="Карта зависимостей",
            fg_color="#6d28d9", hover_color="#5b21b6",
            font=("Roboto", 13, "bold"), height=38,
            command=self.show_dependency_map
        )

        # Кнопка удаления docker_out + БД
        self.delete_btn = ctk.CTkButton(
            self, text="Удалить docker_out + БД",
            fg_color="#7f1d1d", hover_color="#991b1b",
            font=("Roboto", 13, "bold"), height=38,
            command=self.delete_docker_out
        )

        # --- Терминал ---
        self.log_view = ctk.CTkTextbox(self, font=("Menlo", 12), text_color="#FFFFFF",
                                       fg_color="#000000", border_color="#333333", border_width=2)
        self.log_view.pack(padx=20, pady=10, fill="both", expand=True)
        self.log_view.configure(state="disabled")
        self.log_view.tag_config("error",   foreground="#FF4C4C")
        self.log_view.tag_config("success", foreground="#00FF00")
        self.log_view.tag_config("info",    foreground="#5DADE2")
        self.log_view.tag_config("warning", foreground="#F4D03F")
        self.log_view.tag_config("default", foreground="#F8F8F2")

        self.source_path = ""
        self.final_output_path = ""
        self.scan_result = None
        self._up_process = None
        self._up_cancelled = False
        sys.stdout = self

    # ------------------------------------------------------------------ #
    #  Утилиты                                                             #
    # ------------------------------------------------------------------ #

    def browse_source(self):
        d = filedialog.askdirectory()
        if d:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, d)

    def write(self, txt):
        self.log_view.configure(state="normal")
        if any(w in txt for w in ["❌", "Ошибка", "ERROR", "failed", "Traceback", "Exception"]):
            tag = "error"
        elif any(w in txt for w in ["✅", "Успешно", "Success", "Healthy"]):
            tag = "success"
        elif any(w in txt for w in ["🐳", "▶️", "🛑", "---", "Building", "Status", "Container"]):
            tag = "info"
        elif any(w in txt for w in ["WARN", "Warning", "⚠️"]):
            tag = "warning"
        else:
            tag = "default"
        self.log_view.insert("end", txt, tag)
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def flush(self): pass

    def _clear_log(self):
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.configure(state="disabled")

    def _hide_action_buttons(self):
        self.generate_btn.pack_forget()
        self.regen_btn.pack_forget()
        self.docker_frame.pack_forget()
        self.map_btn.pack_forget()
        self.delete_btn.pack_forget()

    def _show_after_generation(self):
        self.generate_btn.pack_forget()
        self.regen_btn.pack(padx=40, pady=(8, 0), fill="x", before=self.log_view)
        self.docker_frame.pack(padx=40, pady=5, fill="x", before=self.log_view)
        self.map_btn.pack(padx=40, pady=(0, 5), fill="x", before=self.log_view)
        self.delete_btn.pack(padx=40, pady=(0, 8), fill="x", before=self.log_view)

    def _show_after_scan_with_output(self):
        self.generate_btn.pack_forget()
        self.regen_btn.pack(padx=40, pady=(8, 0), fill="x", before=self.log_view)
        self.docker_frame.pack(padx=40, pady=5, fill="x", before=self.log_view)
        self.map_btn.pack(padx=40, pady=(0, 5), fill="x", before=self.log_view)
        self.delete_btn.pack(padx=40, pady=(0, 8), fill="x", before=self.log_view)

    def _show_after_scan_no_output(self):
        self.regen_btn.pack_forget()
        self.docker_frame.pack_forget()
        self.delete_btn.pack_forget()
        self.generate_btn.pack(padx=40, pady=(8, 0), fill="x", before=self.log_view)
        self.map_btn.pack(padx=40, pady=(0, 5), fill="x", before=self.log_view)

    # ------------------------------------------------------------------ #
    #  Прогресс-бар                                                        #
    # ------------------------------------------------------------------ #

    def _show_progress(self, message=""):
        """Показывает анимированный прогресс-бар под кнопкой сканирования."""
        if message:
            self.progress_label.configure(text=message)
            self.progress_label.pack(padx=40, pady=(0, 2), before=self.log_view)
        self.progress_bar.pack(padx=40, pady=(0, 6), fill="x", before=self.log_view)
        self.progress_bar.start()

    def _hide_progress(self):
        """Скрывает прогресс-бар."""
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.progress_label.pack_forget()

    # ------------------------------------------------------------------ #
    #  Сканирование                                                        #
    # ------------------------------------------------------------------ #

    def start_scan(self):
        source_path = self.path_entry.get().strip()
        if not source_path or not os.path.exists(source_path):
            messagebox.showerror("Ошибка", "Укажите верный путь к монолиту!")
            return

        self.source_path = source_path
        self.final_output_path = os.path.join(source_path, "docker_out")

        self._hide_action_buttons()
        self._clear_log()
        self.scan_btn.configure(state="disabled", text="Сканирование...")
        self._show_progress("Анализ структуры проекта...")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self):
        try:
            print(f"--- Сканирование монолита ---\n{self.source_path}\n")
            result = scanner.scan_project_structure(self.source_path)
            if result.get('language') == 'python':
                result['import_edges'] = scanner.analyze_import_graph(self.source_path, result['modules'])
            elif result.get('language') == 'java':
                import java_scanner as _js
                result['import_edges'] = _js.analyze_java_import_graph(
                    result.get('modules', []),
                    result.get('root', self.source_path),
                    result.get('base_package', ''),
                )
            else:
                result['import_edges'] = []
            self.scan_result = result
            self.after(0, self._finish_scan)
        except Exception as e:
            print(f"❌ Ошибка сканирования: {e}")
            self.after(0, self._finish_scan_error)

    def _finish_scan(self):
        self._hide_progress()
        self.scan_btn.configure(state="normal", text="🔍 СКАНИРОВАТЬ")

        modules   = self.scan_result.get('modules', [])
        services  = [m for m in modules if m['type'] == 'service']
        shared    = [m for m in modules if m['type'] == 'shared']
        edges     = self.scan_result.get('import_edges', [])
        frontend  = self.scan_result.get('frontend')

        total_services = len(services) + (1 if frontend else 0)
        print(f"✅ Найдено: {total_services} сервис(ов), {len(shared)} shared-библиотек, {len(edges)} связей\n")
        for m in modules:
            icon = "🚀" if m['type'] == 'service' else "📚"
            if 'files_count' in m:
                detail = f"{m['files_count']} .py файлов"
            else:
                ctrl   = len(m.get('controllers', []))
                svc    = len(m.get('services', []))
                entity = len(m.get('entities', []))
                detail = f"ctrl={ctrl}  svc={svc}  entity={entity}"
            print(f"  {icon} {m['name']}  ({detail})")
        if frontend:
            fw   = frontend.get('framework', 'unknown')
            bt   = frontend.get('build_tool', '')
            port = frontend.get('dev_port', 3000)
            ts   = " / TypeScript" if frontend.get('typescript') else ""
            print(f"  🌐 frontend  ({fw} / {bt}{ts}, dev port {port})")

        if os.path.exists(self.final_output_path):
            print(f"\nНайдена папка docker_out — контейнеры готовы к запуску.")
            self._show_after_scan_with_output()
        else:
            print(f"\nПапка docker_out не найдена — нажмите «Генерировать».")
            self._show_after_scan_no_output()

    def _finish_scan_error(self):
        self._hide_progress()
        self.scan_btn.configure(state="normal", text="🔍 СКАНИРОВАТЬ")

    # ------------------------------------------------------------------ #
    #  Генерация / Перегенерация                                          #
    # ------------------------------------------------------------------ #

    def start_generation(self):
        if not self.source_path or not os.path.exists(self.source_path):
            messagebox.showerror("Ошибка", "Сначала выполните сканирование!")
            return

        self._hide_action_buttons()
        self.scan_btn.configure(state="disabled")
        self._clear_log()
        self._show_progress("Генерация Docker-артефактов...")
        threading.Thread(target=self._run_generation, daemon=True).start()

    def _run_generation(self):
        try:
            print(f"--- Генерация Docker-артефактов ---\nВывод: {self.final_output_path}\n")
            self.scan_result = generator.run_generation(self.source_path, self.final_output_path)
            self.after(0, self._finish_generation)
        except Exception as e:
            print(f"❌ Ошибка генерации: {e}")
            self.after(0, self._finish_generation_error)

    def _finish_generation(self):
        self._hide_progress()
        self.scan_btn.configure(state="normal")
        self._show_after_generation()
        print("\n✅ Готово! Запустите контейнеры кнопкой «Поднять».")

    def _finish_generation_error(self):
        self._hide_progress()
        self.scan_btn.configure(state="normal")
        self.generate_btn.pack(padx=40, pady=(8, 0), fill="x", before=self.log_view)

    # ------------------------------------------------------------------ #
    #  Карта зависимостей                                                 #
    # ------------------------------------------------------------------ #

    def show_dependency_map(self):
        if not self.scan_result:
            messagebox.showinfo("Карта зависимостей", "Сначала выполните сканирование!")
            return

        modules = self.scan_result.get('modules', [])
        edges   = self.scan_result.get('import_edges', [])

        if not modules:
            messagebox.showinfo("Карта зависимостей", "Модули не найдены.")
            return

        win = ctk.CTkToplevel(self)
        win.title("Карта зависимостей")
        win.geometry("760x540")
        win.resizable(True, True)

        canvas = tkinter.Canvas(win, bg="#0f172a", highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        services = [m for m in modules if m['type'] == 'service']
        shared   = [m for m in modules if m['type'] == 'shared']
        W, H, BOX_W, BOX_H = 760, 540, 120, 36

        def box_cx(i, total):
            return (i + 1) * W / (total + 1)

        # Позиции центров блоков
        positions = {}
        for i, svc in enumerate(services):
            x, y = box_cx(i, len(services)), 150
            positions[svc['name']] = (x, y)
            canvas.create_rectangle(
                x - BOX_W//2, y - BOX_H//2, x + BOX_W//2, y + BOX_H//2,
                fill="#1d4ed8", outline="#60a5fa", width=2
            )
            canvas.create_text(x, y, text=svc['name'], fill="white",
                               font=("Menlo", 10, "bold"))

        for i, sh in enumerate(shared):
            x, y = box_cx(i, len(shared)), 390
            positions[sh['name']] = (x, y)
            canvas.create_rectangle(
                x - BOX_W//2, y - BOX_H//2, x + BOX_W//2, y + BOX_H//2,
                fill="#374151", outline="#9ca3af", width=2
            )
            canvas.create_text(x, y, text=sh['name'], fill="#e5e7eb",
                               font=("Menlo", 10))

        # Рисуем рёбра ПОСЛЕ блоков, чтобы они были поверх
        for edge in edges:
            s, d = edge['from'], edge['to']
            if s not in positions or d not in positions:
                continue
            x1, y1 = positions[s]
            x2, y2 = positions[d]

            if abs(y1 - y2) < 10:
                # Горизонтальное ребро (сервис → сервис на одной строке):
                # рисуем дугу ВЫШЕ строки сервисов, выходя из боковых сторон
                side1 = BOX_W // 2 if x2 > x1 else -(BOX_W // 2)
                side2 = -(BOX_W // 2) if x2 > x1 else BOX_W // 2
                sx, sy = x1 + side1, y1
                ex, ey = x2 + side2, y2
                mid_x = (sx + ex) / 2
                arc_y  = y1 - 55    # дуга на 55px выше
                canvas.create_line(
                    sx, sy, mid_x, arc_y, ex, ey,
                    arrow="last", fill="#f59e0b", width=2,
                    arrowshape=(10, 12, 4), smooth=True
                )
            else:
                # Вертикальное ребро (сервис → shared): выходим снизу/сверху блока
                dy1 = BOX_H // 2 if y2 > y1 else -(BOX_H // 2)
                dy2 = -(BOX_H // 2) if y2 > y1 else BOX_H // 2
                canvas.create_line(
                    x1, y1 + dy1, x2, y2 + dy2,
                    arrow="last", fill="#f59e0b", width=2,
                    arrowshape=(10, 12, 4)
                )

        # Легенда
        canvas.create_rectangle(16, H - 78, 195, H - 10, fill="#1e293b", outline="#334155")
        canvas.create_rectangle(26, H - 66, 50, H - 50, fill="#1d4ed8", outline="#60a5fa")
        canvas.create_text(57, H - 58, anchor="w", text="Сервис", fill="white", font=("Menlo", 9))
        canvas.create_rectangle(26, H - 44, 50, H - 28, fill="#374151", outline="#9ca3af")
        canvas.create_text(57, H - 36, anchor="w", text="Shared-библиотека", fill="white", font=("Menlo", 9))
        canvas.create_line(26, H - 16, 50, H - 16, fill="#f59e0b", width=2,
                           arrow="last", arrowshape=(8, 10, 3))
        canvas.create_text(57, H - 16, anchor="w", text="Импорт", fill="white", font=("Menlo", 9))

        canvas.create_text(W // 2, 40, text="Карта зависимостей микросервисов",
                           fill="#e2e8f0", font=("Menlo", 14, "bold"))
        canvas.create_text(W // 2, 65,
                           text=f"{len(services)} сервис(ов)  •  {len(shared)} shared  •  {len(edges)} связей",
                           fill="#64748b", font=("Menlo", 10))

    # ------------------------------------------------------------------ #
    #  Docker                                                              #
    # ------------------------------------------------------------------ #

    def docker_up(self):
        if not self.final_output_path or not os.path.exists(self.final_output_path):
            messagebox.showerror("Ошибка", "Папка docker_out не найдена. Выполните генерацию.")
            return
        print("\nЗапуск контейнеров (Up)...")
        self._up_cancelled = False

        def _run_up():
            mac_env = os.environ.copy()
            mac_env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + mac_env.get("PATH", "")
            process = subprocess.Popen(
                ["docker", "compose", "up", "-d", "--build",
                 "--remove-orphans", "--force-recreate"],
                cwd=self.final_output_path,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=mac_env
            )
            self._up_process = process
            for line in process.stdout:
                print(line, end="")
            process.wait()
            self._up_process = None
            if not self._up_cancelled:
                if process.returncode == 0:
                    print("✅ Операция Docker завершена.\n")
                    self._open_browser()
                else:
                    print(f"❌ Команда завершилась с кодом {process.returncode}\n")

        threading.Thread(target=_run_up, daemon=True).start()

    def docker_down(self):
        if not self.final_output_path or not os.path.exists(self.final_output_path):
            messagebox.showerror("Ошибка", "Папка docker_out не найдена.")
            return
        proc = self._up_process
        if proc and proc.poll() is None:
            self._up_cancelled = True
            proc.terminate()
        print("\n🛑 Остановка контейнеров (Down)...")
        threading.Thread(target=self.run_subprocess,
                         args=(["docker", "compose", "down", "--remove-orphans"],),
                         kwargs={"success_codes": (0, 1)},
                         daemon=True).start()

    def delete_docker_out(self):
        if not self.final_output_path or not os.path.exists(self.final_output_path):
            messagebox.showerror("Ошибка", "Папка docker_out не найдена.")
            return

        confirmed = messagebox.askyesno(
            "Подтверждение удаления",
            "Вы действительно хотите удалить docker_out вместе с БД?\n\n"
            "Это удалит:\n"
            "• Папку docker_out со всеми сгенерированными файлами\n"
            "• Docker volume с данными PostgreSQL (postgres_data)\n\n"
            "Оригинальный код монолита затронут НЕ будет.",
            icon="warning"
        )
        if not confirmed:
            return

        print("\n🗑 Удаление docker_out и БД...")
        threading.Thread(target=self._run_delete, daemon=True).start()

    def _run_delete(self):
        if os.path.exists(self.final_output_path):
            self.run_subprocess(["docker", "compose", "down", "-v", "--remove-orphans"],
                               success_codes=(0, 1))

        try:
            if os.path.exists(self.final_output_path):
                shutil.rmtree(self.final_output_path)
            print("✅ Папка docker_out удалена.\n")
        except Exception as e:
            print(f"❌ Не удалось удалить docker_out: {e}\n")
            return

        self.after(0, self._after_delete)

    def _after_delete(self):
        self._hide_action_buttons()
        self.generate_btn.pack(padx=40, pady=(8, 0), fill="x", before=self.log_view)
        self.map_btn.pack(padx=40, pady=(0, 5), fill="x", before=self.log_view)
        print("✅ Готово. Нажмите «Генерировать» для повторного создания.\n")

    def _open_browser(self):
        url = "http://localhost:8888"
        print(f"🌐 Ожидаю готовности API Gateway ({url})...")
        for _ in range(30):
            try:
                urllib.request.urlopen(url, timeout=1)
                print(f"✅ Шлюз готов! Открываю браузер...\n")
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(1)
        print(f"⚠️ Шлюз не ответил за 30 секунд. Откройте вручную: {url}\n")

    def run_subprocess(self, command, on_success=None, success_codes=(0,)):
        try:
            mac_env = os.environ.copy()
            mac_env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + mac_env.get("PATH", "")
            process = subprocess.Popen(
                command, cwd=self.final_output_path,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, env=mac_env
            )
            for line in process.stdout:
                print(line, end="")
            process.wait()
            if process.returncode in success_codes:
                print("✅ Операция Docker завершена.\n")
                if on_success:
                    on_success()
            else:
                print(f"❌ Команда завершилась с кодом {process.returncode}\n")
        except Exception as e:
            print(f"❌ Ошибка Docker: {e}\nУбедитесь, что Docker Desktop запущен.")


if __name__ == "__main__":
    app = AMMApp()
    app.mainloop()
