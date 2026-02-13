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

        # --- КОРРЕКТНЫЕ РАЗМЕРЫ ДЛЯ MAC ---
        self.title("AMM-Docker")
        
        # Устанавливаем размер 500 пикселей в ширину и 850 в высоту
        window_width = 450
        window_height = 700
        
        # Центрируем на экране
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width // 2) - (window_width // 2)
        y = (screen_height // 2) - (window_height // 2)
        
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.minsize(450, 700) # Минимальный порог, чтобы не "схлопывалось"
        
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Заголовок ---
        self.title_label = ctk.CTkLabel(self, text="AMM-DOCKER", font=("Roboto", 28, "bold"))
        self.title_label.pack(pady=(40, 5))
        
        self.sub_label = ctk.CTkLabel(self, text="Migration Assistant", font=("Roboto", 16), text_color="gray")
        self.sub_label.pack(pady=(0, 30))

        # --- Поле выбора пути ---
        self.path_entry = ctk.CTkEntry(self, placeholder_text="Путь к проекту...", height=45, font=("Roboto", 14))
        self.path_entry.pack(padx=30, pady=10, fill="x")

        self.browse_btn = ctk.CTkButton(self, text="📁 ВЫБРАТЬ ПАПКУ", height=40, 
                                     fg_color="#3b3b3b", hover_color="#4b4b4b", command=self.browse)
        self.browse_btn.pack(padx=30, pady=5, fill="x")

        # --- Кнопка запуска ---
        self.run_btn = ctk.CTkButton(self, text="ЗАПУСТИТЬ МИГРАЦИЮ", 
                                     fg_color="#28a745", hover_color="#218838",
                                     font=("Roboto", 16, "bold"), height=55,
                                     command=self.start_migration)
        self.run_btn.pack(padx=30, pady=30, fill="x")

        # --- Логи (делаем их крупнее) ---
        self.log_view = ctk.CTkTextbox(self, font=("Courier New", 13), text_color="#A9FFAD", fg_color="#1a1a1a")
        self.log_view.pack(padx=30, pady=10, fill="both", expand=True) # expand=True заставит его расти
        self.log_view.configure(state="disabled")

        # --- Кнопка результата (появится позже) ---
        self.open_folder_btn = ctk.CTkButton(self, text="ОТКРЫТЬ РЕЗУЛЬТАТ", 
                                             fg_color="#007bff", hover_color="#0069d9",
                                             height=50, font=("Roboto", 15, "bold"),
                                             command=self.open_result_folder)

        self.status_label = ctk.CTkLabel(self, text="Статус: Готов", text_color="gray", font=("Roboto", 13))
        self.status_label.pack(pady=20)

        sys.stdout = self # Теперь само приложение ловит принты

    # Методы для перехвата print
    def write(self, string):
        self.log_view.configure(state="normal")
        self.log_view.insert("end", string)
        self.log_view.see("end")
        self.log_view.configure(state="disabled")
    def flush(self): pass

    def browse(self):
        directory = filedialog.askdirectory()
        if directory:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, directory)

    def open_result_folder(self):
        path = os.path.join(current_dir, "docker_out")
        if os.path.exists(path):
            subprocess.call(["open", path])

    def start_migration(self):
        target_path = self.path_entry.get()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("Ошибка", "Путь не найден!")
            return

        self.open_folder_btn.pack_forget()
        self.run_btn.configure(state="disabled", text="АНАЛИЗ...")
        threading.Thread(target=self.run_logic, daemon=True).start()

    def run_logic(self):
        try:
            generator.run_generation() 
            self.after(0, self.finish_success)
        except Exception as e:
            print(f"\n Ошибка: {str(e)}")
            self.after(0, lambda: self.status_label.configure(text="Статус: Ошибка ❌", text_color="red"))

    def finish_success(self):
        self.run_btn.configure(state="normal", text="ПОВТОРИТЬ")
        self.status_label.configure(text="Статус: Завершено ✅", text_color="green")
        # Показываем синюю кнопку прямо над статусом
        self.open_folder_btn.pack(padx=30, pady=(0, 10), fill="x", before=self.status_label)
        messagebox.showinfo("Успех", "Docker-файлы созданы!")

if __name__ == "__main__":
    app = AMMApp()
    app.mainloop()