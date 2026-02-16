import os
import shutil
from jinja2 import Environment, FileSystemLoader
import scanner

def render_dockerfile(module_info, global_deps, output_path, template_env, source_path):
    """
    Генерирует Dockerfile, entrypoint.py и копирует код сервиса.
    """
    service_name = module_info['name']
    service_rel_path = module_info['path']
    
    # Полный путь к исходному коду сервиса
    abs_source_path = os.path.join(source_path, service_rel_path)
    
    # Путь в docker_out для этого сервиса
    service_build_dir = os.path.join(output_path, service_name)
    os.makedirs(service_build_dir, exist_ok=True)
    
    # --- 1. Копирование исходного кода модуля ---
    if os.path.exists(abs_source_path):
        print(f"   📂 [COPY] Копирование кода из {service_rel_path}...")
        shutil.copytree(abs_source_path, service_build_dir, dirs_exist_ok=True)

    # --- 2. Обработка зависимостей ---
    # Глобальные
    if global_deps:
        with open(os.path.join(service_build_dir, "global_requirements.txt"), "w") as f:
            f.write("\n".join(global_deps))
        
    # Локальные
    local_req_source = os.path.join(abs_source_path, "requirements.txt")
    has_local_reqs = os.path.exists(local_req_source) # <--- ВОТ ЗДЕСЬ МЫ ЕЁ ТЕПЕРЬ ОПРЕДЕЛЯЕМ ЯВНО
    
    if has_local_reqs:
        shutil.copy(local_req_source, os.path.join(service_build_dir, "requirements.txt"))

    # --- 3. Рендерим Entrypoint (Точку входа) ---
    entry_template = template_env.get_template("entrypoint.jinja2")
    entry_content = entry_template.render(service_name=service_name)
    
    with open(os.path.join(service_build_dir, "entrypoint.py"), "w") as f:
        f.write(entry_content)

    # --- 4. Рендерим Dockerfile ---
    template = template_env.get_template("Dockerfile.jinja2")
    dockerfile_content = template.render(
        service_name=service_name,
        local_requirements=has_local_reqs # Теперь переменная существует
    )
    
    with open(os.path.join(service_build_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)
    
    print(f"   🔨 [GENERATOR] Артефакты для {service_name} готовы (+entrypoint)")

def run_generation(source_path=None, output_path=None):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    templates_dir = os.path.join(project_root, "templates")
    
    if not source_path:
        source_path = os.path.join(project_root, "test_monolith_shop")
    if not output_path:
        output_path = os.path.join(project_root, "docker_out")

    # Очистка папки вывода
    if os.path.exists(output_path):
        shutil.rmtree(output_path)
    os.makedirs(output_path, exist_ok=True)

    print(f"1️⃣  Запуск сканирования: {source_path}")
    scan_result = scanner.scan_project_structure(source_path)
    global_deps = scan_result.get('dependencies', {}).get('.', [])
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    modules = scan_result.get('modules', [])
    
    active_services = []
    for module in modules:
        if module['name'] in ['__pycache__', 'instance', 'templates', 'venv', '.git']:
            continue
            
        try:
            render_dockerfile(module, global_deps, output_path, env, source_path)
            active_services.append(module)
        except Exception as e:
            print(f"⚠️ Ошибка при обработке модуля {module['name']}: {e}")

    # Копирование общих файлов (db.py, app.py)
    shared_files = ['db.py', 'app.py']
    for file in shared_files:
        full_path = os.path.join(source_path, file)
        if os.path.exists(full_path):
             for service in active_services:
                 shutil.copy(full_path, os.path.join(output_path, service['name'], file))

    # Генерация docker-compose
    if active_services:
        print("4️⃣  Генерация docker-compose.yaml...")
        compose_template = env.get_template("docker-compose.jinja2")
        compose_content = compose_template.render(services=active_services)
        with open(os.path.join(output_path, "docker-compose.yaml"), "w") as f:
            f.write(compose_content)
        print(f"\n✅ Миграция завершена! Проверь папку: {output_path}")

if __name__ == "__main__":
    run_generation()