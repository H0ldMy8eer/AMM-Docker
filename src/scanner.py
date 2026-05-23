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

    print(f"🔍 [SCANNER] Начинаю анализ монолита: {root_path}")

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

def analyze_import_graph(root_path, modules):
    """Строит граф импортов: какой модуль импортирует какой другой модуль."""
    module_names = [m['name'] for m in modules]
    edges = []
    seen = set()

    for module in modules:
        module_path = os.path.join(root_path, module['path'])
        if not os.path.isdir(module_path):
            continue

        for dirpath, _, filenames in os.walk(module_path):
            for filename in filenames:
                if not filename.endswith('.py'):
                    continue
                try:
                    with open(os.path.join(dirpath, filename), 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception:
                    continue

                for target in module_names:
                    if target == module['name']:
                        continue
                    edge = (module['name'], target)
                    if edge in seen:
                        continue
                    if f'import {target}' in content or f'from {target}' in content:
                        edges.append({'from': module['name'], 'to': target})
                        seen.add(edge)

    return edges


if __name__ == "__main__":
    pass
