import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import sys
import os
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

import generator

class AMMApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Настройки окна ---
        self.title("AMM-Docker")
        window_width = 500  # Чуть расширил для красивого терминала
        window_height = 720
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        y = max(30, y)
        
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.minsize(450, 650)
        
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Заголовок (Больше и ниже) ---
        self.title_label = ctk.CTkLabel(self, text="AMM-DOCKER", font=("Roboto", 32, "bold"))
        self.title_label.pack(pady=(40, 0)) # Увеличили верхний отступ
        self.sub_label = ctk.CTkLabel(self, text="Migration Assistant", font=("Roboto", 14), text_color="gray")
        self.sub_label.pack(pady=(0, 15))

        # --- Блок 1: Исходный код ---
        self.path_label = ctk.CTkLabel(self, text="1. Путь к монолиту:", font=("Roboto", 13, "bold"))
        self.path_label.pack(anchor="w", padx=40, pady=(5, 0))
        
        self.path_entry = ctk.CTkEntry(self, placeholder_text="Выберите папку с кодом...", height=40)
        self.path_entry.pack(padx=40, pady=5, fill="x")

        # Кнопка: Уже (за счет padx=40) и Выше (height=40)
        self.browse_btn = ctk.CTkButton(self, text="📂 ВЫБРАТЬ ИСХОДНИК", fg_color="#3b3b3b", hover_color="#4b4b4b", height=40, command=self.browse_source)
        self.browse_btn.pack(padx=40, fill="x")

        # --- Блок 2: Настройка вывода ---
        self.sep = ctk.CTkLabel(self, text="----------------------------------------", text_color="gray")
        self.sep.pack(pady=5)

        self.use_default_output = ctk.BooleanVar(value=True)
        self.output_checkbox = ctk.CTkCheckBox(self, text="Сохранить результат внутри проекта", 
                                               variable=self.use_default_output, 
                                               command=self.toggle_output_input,
                                               font=("Roboto", 12))
        self.output_checkbox.pack(pady=5, padx=40, anchor="w")

        self.custom_output_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.out_path_entry = ctk.CTkEntry(self.custom_output_frame, placeholder_text="Куда сохранить результат?", height=40)
        self.out_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.out_browse_btn = ctk.CTkButton(self.custom_output_frame, text="...", width=45, height=40, fg_color="#3b3b3b", command=self.browse_output)
        self.out_browse_btn.pack(side="right")

        # --- Кнопка старта (Уже и Выше) ---
        self.run_btn = ctk.CTkButton(self, text="🚀 1. ЗАПУСТИТЬ МИГРАЦИЮ", 
                                     fg_color="#28a745", hover_color="#218838",
                                     font=("Roboto", 15, "bold"), height=45)
        self.run_btn.configure(command=self.start_migration)
        self.run_btn.pack(padx=40, pady=10, fill="x")

        # --- БЛОК 3: Управление Docker ---
        self.docker_frame = ctk.CTkFrame(self)
        self.docker_frame.pack(padx=40, pady=5, fill="x")
        
        self.docker_label = ctk.CTkLabel(self.docker_frame, text="Управление Docker (Mac OS)", font=("Roboto", 13, "bold"))
        self.docker_label.pack(pady=(5, 5))

        self.docker_btns_frame = ctk.CTkFrame(self.docker_frame, fg_color="transparent")
        self.docker_btns_frame.pack(pady=(0, 10), fill="x", padx=10)

        self.up_btn = ctk.CTkButton(self.docker_btns_frame, text="▶️ Поднять", fg_color="#007bff", hover_color="#0056b3", height=40, command=self.docker_up)
        self.up_btn.pack(side="left", expand=True, padx=5)

        self.down_btn = ctk.CTkButton(self.docker_btns_frame, text="⏹ Остановить", fg_color="#dc3545", hover_color="#c82333", height=40, command=self.docker_down)
        self.down_btn.pack(side="right", expand=True, padx=5)
        
        self.docker_frame.pack_forget()

        # --- НАСТОЯЩИЙ ТЕРМИНАЛ ---
        # Черный фон, маковский терминальный шрифт Menlo
        self.log_view = ctk.CTkTextbox(self, font=("Menlo", 12), text_color="#FFFFFF", fg_color="#000000", border_color="#333333", border_width=2)
        self.log_view.pack(padx=20, pady=10, fill="both", expand=True)
        self.log_view.configure(state="disabled")

        # Настраиваем цветовые теги для эмуляции подсветки терминала
        self.log_view.tag_config("error", foreground="#FF4C4C")      # Красный
        self.log_view.tag_config("success", foreground="#00FF00")    # Ярко-зеленый
        self.log_view.tag_config("info", foreground="#5DADE2")       # Голубой
        self.log_view.tag_config("warning", foreground="#F4D03F")    # Желтый
        self.log_view.tag_config("default", foreground="#F8F8F2")    # Стандартный бело-серый

        self.final_output_path = ""
        sys.stdout = self

    def toggle_output_input(self):
        if self.use_default_output.get():
            self.custom_output_frame.pack_forget()
        else:
            self.custom_output_frame.pack(padx=40, pady=5, fill="x")

    def browse_source(self):
        d = filedialog.askdirectory()
        if d:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, d)

    def browse_output(self):
        d = filedialog.askdirectory()
        if d:
            self.out_path_entry.delete(0, "end")
            self.out_path_entry.insert(0, d)

    def write(self, txt):
        """Перехват принтов и умная раскраска логов терминала"""
        self.log_view.configure(state="normal")
        
        # Эвристика раскраски текста
        if any(w in txt for w in ["❌", "Ошибка", "ERROR", "failed", "Traceback", "Exception"]):
            self.log_view.insert("end", txt, "error")
        elif any(w in txt for w in ["✅", "Успешно", "Success", "Healthy"]):
            self.log_view.insert("end", txt, "success")
        elif any(w in txt for w in ["🐳", "▶️", "🛑", "---", "Building", "Status", "Container"]):
            self.log_view.insert("end", txt, "info")
        elif any(w in txt for w in ["WARN", "Warning", "⚠️"]):
            self.log_view.insert("end", txt, "warning")
        else:
            self.log_view.insert("end", txt, "default")
            
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def flush(self): pass

    def start_migration(self):
        source_path = self.path_entry.get()
        if not source_path or not os.path.exists(source_path):
            messagebox.showerror("Ошибка", "Укажите верный путь к монолиту!")
            return

        if self.use_default_output.get():
            self.final_output_path = os.path.join(source_path, "docker_out")
        else:
            custom_out = self.out_path_entry.get()
            if not custom_out:
                messagebox.showerror("Ошибка", "Выберите папку для сохранения результата!")
                return
            self.final_output_path = os.path.join(custom_out, "docker_out")

        self.run_btn.configure(state="disabled", text="Анализ...")
        self.docker_frame.pack_forget()
        self.log_view.configure(state="normal")
        self.log_view.delete("1.0", "end")
        self.log_view.configure(state="disabled")
        
        threading.Thread(target=self.run_logic, args=(source_path, self.final_output_path), daemon=True).start()

    def run_logic(self, src, out):
        try:
            print(f"--- Старт миграции ---\nИсточник: {src}\nВывод: {out}\n")
            generator.run_generation(src, out)
            self.after(0, self.finish_success)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            self.after(0, self.finish_error)

    def finish_success(self):
        self.run_btn.configure(state="normal", text="🔄 ПЕРЕГЕНЕРИРОВАТЬ")
        self.docker_frame.pack(padx=40, pady=10, fill="x", before=self.log_view)
        print("\n✅ Готово! Вы можете управлять Docker-контейнерами с помощью кнопок выше.")

    def finish_error(self):
        self.run_btn.configure(state="normal", text="ЗАПУСТИТЬ МИГРАЦИЮ")

    def docker_up(self):
        print("\n🐳 Запуск контейнеров в фоновом режиме (Up)...")
        threading.Thread(target=self.run_subprocess, args=(["docker", "compose", "up", "-d", "--build"],), daemon=True).start()

    def docker_down(self):
        print("\n🛑 Остановка и удаление контейнеров (Down)...")
        threading.Thread(target=self.run_subprocess, args=(["docker", "compose", "down", "-v"],), daemon=True).start()

    def run_subprocess(self, command):
        try:
            mac_env = os.environ.copy()
            mac_env["PATH"] = "/usr/local/bin:/opt/homebrew/bin:" + mac_env.get("PATH", "")

            process = subprocess.Popen(
                command, 
                cwd=self.final_output_path, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                env=mac_env
            )
            for line in process.stdout:
                print(line, end="")
            process.wait()
            
            if process.returncode == 0:
                print("✅ Операция Docker успешно завершена.\n")
            else:
                print(f"❌ Команда завершилась с кодом {process.returncode}\n")
        except Exception as e:
            print(f"❌ Ошибка выполнения Docker: {e}\nУбедитесь, что Docker Desktop запущен.")

if __name__ == "__main__":
    app = AMMApp()
    app.mainloop()

