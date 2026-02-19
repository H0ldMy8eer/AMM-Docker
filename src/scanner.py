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
                if not line or line.startswith('#'):
                    continue
                dependencies.append(line)
        return dependencies
    except Exception as e:
        print(f"Ошибка чтения {file_path}: {e}")
        return []

def scan_project_structure(root_path):
    """
    Рекурсивно обходит папки и строит ИНТЕЛЛЕКТУАЛЬНУЮ карту проекта.
    Определяет тип модуля: "service" (для Docker) или "shared" (общий код).
    """
    project_map = {
        "root": root_path,
        "modules": [],       
        "dependencies": {},  
        "files": []          
    }

    print(f"🔍 [SCANNER] Начинаю глубокий анализ монолита: {root_path}")

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ['__pycache__', 'venv', 'env', 'node_modules', 'instance']]
        
        rel_path = os.path.relpath(dirpath, root_path)
        depth = rel_path.count(os.sep)
        
        if "requirements.txt" in filenames:
            full_req_path = os.path.join(dirpath, "requirements.txt")
            deps = parse_requirements(full_req_path)
            project_map["dependencies"][rel_path] = deps

        if depth == 0 and rel_path != ".":
            py_files = [f for f in filenames if f.endswith(".py")]
            
            if py_files:
                is_service = any(f in ["routes.py", "views.py"] for f in filenames)
                module_type = "service" if is_service else "shared"
                
                project_map["modules"].append({
                    "name": rel_path,
                    "path": rel_path,
                    "type": module_type,
                    "files_count": len(py_files)
                })
                
                icon = "🚀" if is_service else "📚"
                print(f"   {icon} [MODULE] Найден {module_type}: {rel_path} (файлов: {len(py_files)})")

    return project_map

if __name__ == "__main__":
    pass
