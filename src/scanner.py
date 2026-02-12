import os

def parse_requirements(file_path):
    """Читает файл requirements.txt и возвращает список библиотек."""
    dependencies = []
    if not os.path.exists(file_path):
        return []
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Игнорируем пустые строки и комментарии
                if not line or line.startswith('#'):
                    continue
                dependencies.append(line)
        return dependencies
    except Exception as e:
        print(f"Ошибка чтения {file_path}: {e}")
        return []

def scan_project_structure(root_path):
    """
    Рекурсивно обходит папки и строит карту проекта.
    Входные данные: путь к директории проекта[cite: 167].
    """
    project_map = {
        "root": root_path,
        "modules": [],       # найденные кандидаты в сервисы
        "dependencies": {},  # библиотеки
        "files": []          # все файлы
    }

    print(f"🔍 [SCANNER] Начинаю анализ папки: {root_path}")

    # os.walk позволяет "гулять" по всем вложенным папкам
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Игнорируем системные папки (начинаются с точки) и __pycache__
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
        
        # Получаем относительный путь
        rel_path = os.path.relpath(dirpath, root_path)
        
        # 1. Ищем файлы зависимостей
        if "requirements.txt" in filenames:
            full_req_path = os.path.join(dirpath, "requirements.txt")
            deps = parse_requirements(full_req_path)
            project_map["dependencies"][rel_path] = deps
            print(f"   📦 [DEPS] В '{rel_path}' найдено {len(deps)} зависимостей: {deps}")

        # 2. Ищем Python-файлы и определяем модули
        py_files = [f for f in filenames if f.endswith(".py")]
        if py_files:
            # Если в папке есть __init__.py — это явный признак модуля Python
            if "__init__.py" in filenames and rel_path != ".":
                module_name = os.path.basename(dirpath)
                project_map["modules"].append({
                    "name": module_name,
                    "path": rel_path,
                    "files_count": len(py_files)
                })
                print(f"   🧩 [MODULE] Обнаружен кандидат в сервис: {module_name}")

    return project_map

# --- Блок тестирования ---
if __name__ == "__main__":
    # Вычисляем путь к папке test_monolith_shop
    # Мы предполагаем, что она лежит рядом с папкой src (на уровень выше)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir) # Поднимаемся из src в корень
    test_path = os.path.join(project_root, "test_monolith_shop")
    
    # Проверка на случай, если запуск из другой папки
    if not os.path.exists(test_path):
        # Пробуем искать в текущей директории (если запуск из корня)
        test_path = "test_monolith_shop"

    if os.path.exists(test_path):
        scan_project_structure(test_path)
    else:
        print(f"❌ Ошибка: Папка {test_path} не найдена.")
        