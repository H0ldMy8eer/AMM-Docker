import os
import shutil
from jinja2 import Environment, FileSystemLoader
import scanner

def render_dockerfile(module_info, global_deps, output_dir, template_env, monolith_path):
    service_name = module_info['name']
    service_path = module_info['path']
    
    abs_local_path = os.path.join(monolith_path, service_path)
    service_build_dir = os.path.join(output_dir, service_name)
    os.makedirs(service_build_dir, exist_ok=True)
    
    # Записываем общие зависимости
    with open(os.path.join(service_build_dir, "global_requirements.txt"), "w") as f:
        f.write("\n".join(global_deps))
        
    # --- НОВОЕ: Копируем локальный requirements.txt, если он есть ---
    local_req_source = os.path.join(abs_local_path, "requirements.txt")
    has_local_reqs = os.path.exists(local_req_source)
    
    if has_local_reqs:
        # Копируем его в папку сборки сервиса
        shutil.copy(local_req_source, os.path.join(service_build_dir, "requirements.txt"))
    # ---------------------------------------------------------------

    template = template_env.get_template("Dockerfile.jinja2")
    dockerfile_content = template.render(
        service_name=service_name,
        local_requirements=has_local_reqs
    )
    
    with open(os.path.join(service_build_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile_content)
    
    print(f"   🔨 [GENERATOR] Создан Dockerfile для: {service_name} (Local reqs: {has_local_reqs})")

def run_generation():
    # Находим корень проекта (AMM-Docker)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    
    templates_dir = os.path.join(project_root, "templates")
    monolith_path = os.path.join(project_root, "test_monolith_shop")
    output_dir = os.path.join(project_root, "docker_out")
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)

    print("1️⃣  Запуск сканирования...")
    scan_result = scanner.scan_project_structure(monolith_path)
    global_deps = scan_result['dependencies'].get('.', [])
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    
    print(f"2️⃣  Найдено модулей: {len(scan_result['modules'])}")
    
    for module in scan_result['modules']:
        if module['name'] == 'common':
            continue
        # Передаем monolith_path внутрь для корректного поиска зависимостей
        render_dockerfile(module, global_deps, output_dir, env, monolith_path)
    
    # ГЕНЕРАЦИЯ DOCKER-COMPOSE
    print("4️⃣  Генерация docker-compose.yaml...")
    compose_template = env.get_template("docker-compose.jinja2")
    
    # Передаем список только реальных сервисов (без common)
    active_services = [m for m in scan_result['modules'] if m['name'] != 'common']
    
    compose_content = compose_template.render(services=active_services)
    
    with open(os.path.join(output_dir, "docker-compose.yaml"), "w") as f:
        f.write(compose_content)
    
    print(f"\n✅ Готово! Результат в папке: {output_dir}")

if __name__ == "__main__":
    run_generation()