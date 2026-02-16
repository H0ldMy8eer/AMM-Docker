import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import sys
import os
import subprocess

# Настройка путей
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, 'src'))

import generator

class AMMApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Настройки окна ---
        self.title("AMM-Docker")
        window_width = 500
        window_height = 850
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.minsize(450, 700)
        
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Заголовок ---
        self.title_label = ctk.CTkLabel(self, text="AMM-DOCKER", font=("Roboto", 28, "bold"))
        self.title_label.pack(pady=(30, 5))
        self.sub_label = ctk.CTkLabel(self, text="Migration Assistant", font=("Roboto", 16), text_color="gray")
        self.sub_label.pack(pady=(0, 20))

        # --- Блок 1: Исходный код ---
        self.path_label = ctk.CTkLabel(self, text="1. Путь к монолиту:", font=("Roboto", 14, "bold"))
        self.path_label.pack(anchor="w", padx=30, pady=(10, 0))
        
        self.path_entry = ctk.CTkEntry(self, placeholder_text="Выберите папку с кодом...", height=40)
        self.path_entry.pack(padx=30, pady=10, fill="x")

        self.browse_btn = ctk.CTkButton(self, text="📂 ВЫБРАТЬ ИСХОДНИК", fg_color="#3b3b3b", hover_color="#4b4b4b", command=self.browse_source)
        self.browse_btn.pack(padx=30, fill="x")

        # --- Блок 2: Настройка вывода (Чекбокс) ---
        self.sep = ctk.CTkLabel(self, text="------------------------------------------------", text_color="gray")
        self.sep.pack(pady=10)

        self.use_default_output = ctk.BooleanVar(value=True)
        self.output_checkbox = ctk.CTkCheckBox(self, text="Сохранить результат внутри проекта", 
                                               variable=self.use_default_output, 
                                               command=self.toggle_output_input,
                                               font=("Roboto", 13))
        self.output_checkbox.pack(pady=10, padx=30, anchor="w")

        # Фрейм для кастомного пути (изначально скрыт, если чекбокс True)
        self.custom_output_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        self.out_path_entry = ctk.CTkEntry(self.custom_output_frame, placeholder_text="Куда сохранить результат?", height=40)
        self.out_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.out_browse_btn = ctk.CTkButton(self.custom_output_frame, text="...", width=40, height=40, fg_color="#3b3b3b", command=self.browse_output)
        self.out_browse_btn.pack(side="right")

        # --- Кнопка старта ---
        self.run_btn = ctk.CTkButton(self, text="🚀 ЗАПУСТИТЬ МИГРАЦИЮ", 
                                     fg_color="#28a745", hover_color="#218838",
                                     font=("Roboto", 16, "bold"), height=50,
                                     command=self.start_migration)
        self.run_btn.pack(padx=30, pady=20, fill="x")

        # --- Логи ---
        self.log_view = ctk.CTkTextbox(self, font=("Courier New", 13), text_color="#A9FFAD", fg_color="#1a1a1a")
        self.log_view.pack(padx=30, pady=10, fill="both", expand=True)
        self.log_view.configure(state="disabled")

        # Кнопка открытия результата (появится позже)
        self.open_result_btn = ctk.CTkButton(self, text="📂 ОТКРЫТЬ ПАПКУ РЕЗУЛЬТАТА", command=self.open_result_folder)
        self.final_output_path = "" # Сюда запомним итоговый путь

        self.status_label = ctk.CTkLabel(self, text="Готов к работе", text_color="gray")
        self.status_label.pack(pady=10)

        # Перехват stdout
        sys.stdout = self

    def toggle_output_input(self):
        """Показывает или скрывает поле выбора пути вывода"""
        if self.use_default_output.get():
            self.custom_output_frame.pack_forget()
        else:
            self.custom_output_frame.pack(padx=30, pady=5, fill="x")

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
        self.log_view.configure(state="normal")
        self.log_view.insert("end", txt)
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def flush(self): pass

    def start_migration(self):
        source_path = self.path_entry.get()
        if not source_path or not os.path.exists(source_path):
            messagebox.showerror("Ошибка", "Укажите верный путь к монолиту!")
            return

        # Определяем, куда сохранять
        if self.use_default_output.get():
            # Если чекбокс ВКЛ: создаем папку docker_out внутри монолита
            self.final_output_path = os.path.join(source_path, "docker_out")
        else:
            # Если чекбокс ВЫКЛ: берем путь из второго поля
            custom_out = self.out_path_entry.get()
            if not custom_out:
                messagebox.showerror("Ошибка", "Выберите папку для сохранения результата!")
                return
            self.final_output_path = os.path.join(custom_out, "docker_out")

        self.open_result_btn.pack_forget()
        self.run_btn.configure(state="disabled", text="Анализ...")
        
        threading.Thread(target=self.run_logic, args=(source_path, self.final_output_path), daemon=True).start()

    def run_logic(self, src, out):
        try:
            print(f"--- Старт миграции ---\nИсточник: {src}\nВывод: {out}\n")
            # Передаем оба пути в генератор
            generator.run_generation(src, out)
            self.after(0, self.finish_success)
        except Exception as e:
            print(f"Ошибка: {e}")
            self.after(0, self.finish_error)

    def finish_success(self):
        self.run_btn.configure(state="normal", text="ЗАПУСТИТЬ МИГРАЦИЮ")
        self.status_label.configure(text="Успешно! ✅", text_color="green")
        self.open_result_btn.pack(padx=30, pady=(0, 10), fill="x", before=self.status_label)
        messagebox.showinfo("Успех", "Файлы сгенерированы!")

    def finish_error(self):
        self.run_btn.configure(state="normal", text="ЗАПУСТИТЬ МИГРАЦИЮ")
        self.status_label.configure(text="Ошибка ❌", text_color="red")

    def open_result_folder(self):
        if os.path.exists(self.final_output_path):
            if sys.platform == "darwin": subprocess.call(["open", self.final_output_path])
            elif sys.platform == "win32": os.startfile(self.final_output_path)
            else: subprocess.call(["xdg-open", self.final_output_path])

if __name__ == "__main__":
    app = AMMApp()
    app.mainloop()