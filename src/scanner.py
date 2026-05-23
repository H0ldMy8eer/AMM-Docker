import os
import re

SERVICE_FILES = {"routes.py", "views.py", "api.py", "handlers.py", "endpoints.py", "resources.py"}
IGNORE_DIRS = {'__pycache__', 'venv', 'env', 'node_modules', 'instance', 'migrations',
               'tests', 'test', '.git', 'dist', 'build', 'docker_out'}


def parse_requirements(file_path):
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


def _extract_all_blueprints(fpath):
    """Возвращает {var_name: {'url_prefix': ...}} для ВСЕХ Blueprint в файле."""
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return {}

    if 'Blueprint(' not in content:
        return {}

    results = {}
    for m in re.finditer(r'(\w+)\s*=\s*Blueprint\s*\(([^)]*)\)', content, re.DOTALL):
        var_name = m.group(1)
        args_str = m.group(2)
        prefix_m = re.search(r"url_prefix\s*=\s*['\"]([^'\"]+)['\"]", args_str)
        url_prefix = prefix_m.group(1) if prefix_m else None
        results[var_name] = {'url_prefix': url_prefix}
    return results


def _is_service_dir(dirpath, filenames):
    py_files = [f for f in filenames if f.endswith(".py")]
    if not py_files:
        return False
    if any(f in SERVICE_FILES for f in filenames):
        return True
    for py_file in py_files:
        try:
            with open(os.path.join(dirpath, py_file), 'r', encoding='utf-8') as fh:
                if 'Blueprint(' in fh.read():
                    return True
        except Exception:
            pass
    return False


def _service_name_from_var(var_name):
    """auth_bp / auth_blueprint / AuthBlueprint → auth"""
    name = var_name.lower()
    for suffix in ('_blueprint', '_bp', 'blueprint', 'bp'):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)]
            break
    return name.strip('_') or var_name.lower()


def _count_py_files(dirpath):
    total = []
    for _, _, files in os.walk(dirpath):
        total.extend(f for f in files if f.endswith('.py'))
    return len(total)


def scan_project_structure(root_path):
    """
    Сканирует монолит.
    Если в папке несколько .py файлов с Blueprint — каждый становится отдельным сервисом
    (автодекомпозиция). Иначе — папка целиком.
    """
    project_map = {
        "root": root_path,
        "modules": [],
        "dependencies": {},
        "files": []
    }

    print(f"🔍 [SCANNER] Начинаю анализ монолита: {root_path}")

    candidates = []
    per_file_container_dirs = set()  # директории, разбитые по-файлово

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith('.') and d not in IGNORE_DIRS
        ]

        rel_path = os.path.relpath(dirpath, root_path)
        if rel_path == '.':
            if "requirements.txt" in filenames:
                project_map["dependencies"]['.'] = parse_requirements(
                    os.path.join(dirpath, "requirements.txt")
                )
            continue

        depth = rel_path.count(os.sep)
        if depth > 2:
            continue

        if "requirements.txt" in filenames:
            project_map["dependencies"][rel_path] = parse_requirements(
                os.path.join(dirpath, "requirements.txt")
            )

        total_py_count = _count_py_files(dirpath)
        if total_py_count == 0:
            continue

        # Собираем Blueprint-определения из ВСЕХ .py файлов (включая __init__.py)
        # Ключ: (fname, var_name) → {'url_prefix': ...}
        all_bp_defs = {}
        container_name = rel_path.split(os.sep)[-1]
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            bps = _extract_all_blueprints(os.path.join(dirpath, fname))
            for var_name, info in bps.items():
                all_bp_defs[(fname, var_name)] = info

        if len(all_bp_defs) >= 2:
            # Несколько Blueprint-ов → автодекомпозиция по переменным
            per_file_container_dirs.add(rel_path)
            print(f"   🔀 [DECOMPOSE] {rel_path}/ → {len(all_bp_defs)} сервисов")

            for (fname, var_name), info in all_bp_defs.items():
                url_prefix = info['url_prefix']
                # Имя сервиса: из url_prefix или из имени переменной
                if url_prefix:
                    service_name = url_prefix.strip('/').split('/')[0]
                else:
                    service_name = _service_name_from_var(var_name)

                # import_path: из __init__.py → пакет целиком, иначе пакет.модуль
                module_name = fname[:-3]
                if module_name == '__init__':
                    import_path = container_name
                else:
                    import_path = f"{container_name}.{module_name}"

                candidates.append({
                    'name_override': service_name,
                    'rel_path': rel_path,
                    'dirpath': dirpath,
                    'depth': depth,
                    'total_py_count': total_py_count,
                    'is_service': True,
                    'module_file': fname,
                    'import_path': import_path,
                    'blueprint_var': var_name,
                    'url_prefix': url_prefix or f'/{service_name}',
                })
        else:
            py_files = [f for f in filenames if f.endswith(".py")]
            if not py_files:
                continue
            is_service = _is_service_dir(dirpath, filenames)
            candidates.append({
                'rel_path': rel_path,
                'dirpath': dirpath,
                'depth': depth,
                'total_py_count': total_py_count,
                'is_service': is_service,
            })

    # Второй проход: строим список модулей без дублирования
    claimed_prefixes = set()

    # Предки глубоких сервисов (не per-file) → помечаем как контейнеры
    for c in candidates:
        if c['is_service'] and c['depth'] > 0 and 'module_file' not in c:
            parts = c['rel_path'].split(os.sep)
            for i in range(1, len(parts)):
                claimed_prefixes.add(os.sep.join(parts[:i]))

    for c in sorted(candidates, key=lambda x: x['depth']):
        rel_path = c['rel_path']
        is_service = c['is_service']

        # Пропустить директорию-контейнер для per-file (сами файлы будут добавлены)
        if rel_path in per_file_container_dirs and 'module_file' not in c:
            continue

        # Пропустить родительскую папку-контейнер для вложенных сервисов
        if rel_path in claimed_prefixes and not is_service:
            continue

        parent = os.sep.join(rel_path.split(os.sep)[:-1])
        if parent in claimed_prefixes and not is_service:
            continue

        module_type = "service" if is_service else "shared"

        if 'name_override' in c:
            name = c['name_override']
        elif parent in claimed_prefixes:
            name = rel_path.split(os.sep)[-1]
        else:
            name = rel_path.replace(os.sep, '_')

        module = {
            "name": name,
            "path": rel_path,
            "type": module_type,
            "files_count": c['total_py_count'],
        }

        # Добавляем метаданные для per-file blueprints
        if 'module_file' in c:
            module['module_file'] = c['module_file']
            module['import_path'] = c['import_path']
            module['blueprint_var'] = c['blueprint_var']
            module['url_prefix'] = c['url_prefix']

        project_map["modules"].append(module)

        icon = "🚀" if is_service else "📚"
        suffix = f" [{c.get('url_prefix', '')}]" if 'url_prefix' in c else ""
        print(f"   {icon} [MODULE] {module_type}: {name} @ {rel_path}{suffix} (py: {c['total_py_count']})")

    return project_map


def analyze_import_graph(root_path, modules):
    """Строит граф импортов между модулями."""
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
