
import re
import os
import shutil
import secrets
import string
from jinja2 import Environment, FileSystemLoader
import scanner

def generate_password(length=24):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def sanitize_models(service_dir):
    print(f" Очистка моделей в {service_dir}...")
    for root, _, files in os.walk(service_dir):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                new_content = re.sub(r",\s*db\.ForeignKey\([^)]+\)", "", content)
                new_content = re.sub(r"^\s*\w+\s*=\s*db\.relationship\(.+\).*$", "", new_content, flags=re.MULTILINE)
                
                if content != new_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

def create_stubs(service_build_dir, all_modules, current_service_name):
    for module in all_modules:
        mod_name = module['name']
        if mod_name == current_service_name or module.get('type') == 'shared':
            continue
            
        stub_dir = os.path.join(service_build_dir, mod_name)
        if not os.path.exists(stub_dir):
            os.makedirs(stub_dir)
            
            with open(os.path.join(stub_dir, "__init__.py"), "w") as f:
                f.write(f"# Stub for {mod_name}\n")
            
            with open(os.path.join(stub_dir, "models.py"), "w") as f:
                f.write("""
import sys

class Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self

    def __iter__(self):
        return iter([])

sys.modules[__name__] = Stub()
""")
                
def render_service(module_info, all_modules, all_deps_map, output_path, template_env, source_path):
    service_name = module_info['name']
    service_rel_path = module_info['path']
    is_per_file = 'module_file' in module_info

    service_build_dir = os.path.join(output_path, service_name)
    os.makedirs(service_build_dir, exist_ok=True)

    abs_source_path = os.path.join(source_path, service_rel_path)

    if is_per_file:
        # Копируем ВСЮ папку-контейнер (нужна для относительных импортов внутри пакета)
        container_name = os.path.basename(service_rel_path)
        service_code_dest = os.path.join(service_build_dir, container_name)
        if os.path.exists(service_code_dest):
            shutil.rmtree(service_code_dest)
        if os.path.exists(abs_source_path):
            shutil.copytree(abs_source_path, service_code_dest)
    else:
        # Стандартный случай: копируем папку сервиса
        service_code_dest = os.path.join(service_build_dir, service_name)
        if os.path.exists(service_code_dest):
            shutil.rmtree(service_code_dest)
        if os.path.exists(abs_source_path):
            shutil.copytree(abs_source_path, service_code_dest)

    sanitize_models(service_build_dir)

    if not os.path.exists(os.path.join(service_code_dest, "__init__.py")):
        with open(os.path.join(service_code_dest, "__init__.py"), "w") as f:
            f.write("")

    create_stubs(service_build_dir, all_modules, service_name)

    api_bridge_content = template_env.get_template("api_bridge.jinja2").render(service_name=service_name)
    with open(os.path.join(service_build_dir, "api_bridge.py"), "w") as f:
        f.write(api_bridge_content)

    client_content = template_env.get_template("http_client.jinja2").render()
    with open(os.path.join(service_build_dir, "http_client.py"), "w") as f:
        f.write(client_content)

    final_deps = set()
    if '.' in all_deps_map:
        final_deps.update(all_deps_map['.'])
    if service_rel_path in all_deps_map:
        final_deps.update(all_deps_map[service_rel_path])

    final_deps.add("requests==2.31.0")
    final_deps.add("Flask==3.0.0")
    final_deps.add("Flask-SQLAlchemy==3.1.1")
    final_deps.add("psycopg2-binary==2.9.9")

    with open(os.path.join(service_build_dir, "requirements.txt"), "w") as f:
        f.write("\n".join(sorted(final_deps)))

    runnable_services = [m for m in all_modules if m.get('type') == 'service']
    services_map = {m['name']: f"http://{m['name']}:5000" for m in runnable_services}

    entry_content = template_env.get_template("entrypoint.jinja2").render(
        service_name=service_name,
        services_map=services_map,
        import_path=module_info.get('import_path'),
        blueprint_var=module_info.get('blueprint_var'),
        url_prefix=module_info.get('url_prefix', f'/{service_name}'),
    )
    with open(os.path.join(service_build_dir, "run.py"), "w") as f:
        f.write(entry_content)

    docker_content = template_env.get_template("Dockerfile.jinja2").render(service_name=service_name)
    with open(os.path.join(service_build_dir, "Dockerfile"), "w") as f:
        f.write(docker_content)

def run_generation(source_path=None, output_path=None):
    if not source_path or not os.path.exists(source_path):
        print("Ошибка: Путь к монолиту не указан")
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    templates_dir = os.path.join(project_root, "templates")
    
    if os.path.exists(output_path): 
        shutil.rmtree(output_path)
    os.makedirs(output_path, exist_ok=True)

    # 1. СКАНИРОВАНИЕ
    scan_result = scanner.scan_project_structure(source_path)
    all_deps_map = scan_result.get('dependencies', {})
    
    all_modules = scan_result.get('modules', [])
    runnable_services = [m for m in all_modules if m.get('type') == 'service']
    shared_libs = [m for m in all_modules if m.get('type') == 'shared']
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    
    # 2. ГЕНЕРАЦИЯ СЕРВИСОВ
    for module in runnable_services:
        try:
            render_service(module, all_modules, all_deps_map, output_path, env, source_path)
        except Exception as e:
            print(f"❌ Ошибка генерации сервиса {module['name']}: {e}")

    # 3. КОПИРОВАНИЕ ОБЩИХ РЕСУРСОВ
    for service in runnable_services:
        service_dir = os.path.join(output_path, service['name'])

        db_dest = os.path.join(service_dir, 'db.py')
        db_src = os.path.join(source_path, 'db.py')
        if os.path.exists(db_src):
            shutil.copy(db_src, db_dest)
        elif not os.path.exists(db_dest):
            # Генерируем минимальный db.py если в монолите его нет
            with open(db_dest, 'w') as f:
                f.write("from flask_sqlalchemy import SQLAlchemy\ndb = SQLAlchemy()\n")

        for shared in shared_libs:
            shared_src = os.path.join(source_path, shared['path'])
            if os.path.exists(shared_src):
                shutil.copytree(shared_src, os.path.join(service_dir, shared['name']), dirs_exist_ok=True)

        # Копируем глобальные templates/ и static/ из корня монолита если они есть
        for root_resource in ('templates', 'static'):
            resource_src = os.path.join(source_path, root_resource)
            if os.path.exists(resource_src):
                resource_dst = os.path.join(service_dir, root_resource)
                shutil.copytree(resource_src, resource_dst, dirs_exist_ok=True)

        # Копируем корневые .py файлы (models.py, config.py, extensions.py и т.д.)
        # чтобы сервисные импорты типа "from models import db" работали
        _skip_root_files = {'run.py', 'app.py'}
        for fname in os.listdir(source_path):
            if not fname.endswith('.py'):
                continue
            if fname in _skip_root_files:
                continue
            src_file = os.path.join(source_path, fname)
            if not os.path.isfile(src_file):
                continue
            dst_file = os.path.join(service_dir, fname)
            if not os.path.exists(dst_file):  # не перезаписываем сгенерированный db.py
                shutil.copy(src_file, dst_file)

    # 4. АНАЛИЗ ГРАФА ЗАВИСИМОСТЕЙ
    scan_result['import_edges'] = scanner.analyze_import_graph(source_path, all_modules)

    # 5. ГЕНЕРАЦИЯ API GATEWAY (NGINX)
    print(" Генерация API Gateway (Nginx)...")
    nginx_dir = os.path.join(output_path, "nginx")
    os.makedirs(nginx_dir, exist_ok=True)
    nginx_content = env.get_template("nginx.conf.jinja2").render(services=runnable_services)
    with open(os.path.join(nginx_dir, "nginx.conf"), "w") as f:
        f.write(nginx_content)

    # 6. ГЕНЕРАЦИЯ .env С СЛУЧАЙНЫМ ПАРОЛЕМ
    pg_password = generate_password()
    secret_key = generate_password(32)
    env_content = (
        "POSTGRES_USER=admin\n"
        f"POSTGRES_PASSWORD={pg_password}\n"
        "POSTGRES_DB=microservices_db\n"
        f"SECRET_KEY={secret_key}\n"
    )
    env_path = os.path.join(output_path, ".env")
    with open(env_path, "w") as f:
        f.write(env_content)

    example_content = (
        "POSTGRES_USER=admin\n"
        "POSTGRES_PASSWORD=<your-secure-password>\n"
        "POSTGRES_DB=microservices_db\n"
        "SECRET_KEY=<your-secret-key>\n"
    )
    with open(os.path.join(output_path, ".env.example"), "w") as f:
        f.write(example_content)

    print(f"🔐 Сгенерирован случайный пароль БД → {env_path}")

    # 7. КОНФИГИ ЛОГИРОВАНИЯ (Promtail + Grafana)
    logging_dir = os.path.join(output_path, "logging")
    os.makedirs(logging_dir, exist_ok=True)
    for config_file in ("promtail-config.yaml", "grafana-datasource.yaml"):
        src_config = os.path.join(templates_dir, config_file)
        if os.path.exists(src_config):
            shutil.copy(src_config, os.path.join(logging_dir, config_file))
    print("📊 Конфиги Loki/Promtail/Grafana сгенерированы → logging/")

    # 8. DOCKER COMPOSE
    compose_content = env.get_template("docker-compose.jinja2").render(services=runnable_services)
    with open(os.path.join(output_path, "docker-compose.yaml"), "w") as f:
        f.write(compose_content)

    print("\n✅ Генерация завершена успешно!")
    return scan_result


