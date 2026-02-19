
import re
import os
import shutil
from jinja2 import Environment, FileSystemLoader
import scanner

def sanitize_models(service_dir):
    print(f"🧹 Очистка моделей в {service_dir}...")
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
    
    service_build_dir = os.path.join(output_path, service_name)
    os.makedirs(service_build_dir, exist_ok=True)
    
    abs_source_path = os.path.join(source_path, service_rel_path)
    service_code_dest = os.path.join(service_build_dir, service_name)
    
    if os.path.exists(service_code_dest): 
        shutil.rmtree(service_code_dest)
    if os.path.exists(abs_source_path):
        shutil.copytree(abs_source_path, service_code_dest)
    
    sanitize_models(service_build_dir)

    if not os.path.exists(os.path.join(service_code_dest, "__init__.py")):
        with open(os.path.join(service_code_dest, "__init__.py"), "w") as f: f.write("")

    create_stubs(service_build_dir, all_modules, service_name)

    api_bridge_content = template_env.get_template("api_bridge.jinja2").render(service_name=service_name)
    with open(os.path.join(service_build_dir, "api_bridge.py"), "w") as f:
        f.write(api_bridge_content)

    client_content = template_env.get_template("http_client.jinja2").render()
    with open(os.path.join(service_build_dir, "http_client.py"), "w") as f:
        f.write(client_content)

    final_deps = set()
    if '.' in all_deps_map: final_deps.update(all_deps_map['.'])
    if service_rel_path in all_deps_map: final_deps.update(all_deps_map[service_rel_path])
    
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
        services_map=services_map
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
    
    if os.path.exists(output_path): shutil.rmtree(output_path)
    os.makedirs(output_path, exist_ok=True)

    scan_result = scanner.scan_project_structure(source_path)
    all_deps_map = scan_result.get('dependencies', {})
    
    all_modules = scan_result.get('modules', [])
    runnable_services = [m for m in all_modules if m.get('type') == 'service']
    shared_libs = [m for m in all_modules if m.get('type') == 'shared']
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    
    for module in runnable_services:
        try:
            render_service(module, all_modules, all_deps_map, output_path, env, source_path)
        except Exception as e:
            print(f"❌ Ошибка генерации сервиса {module['name']}: {e}")

    for service in runnable_services:
        service_dir = os.path.join(output_path, service['name'])
        
        db_path = os.path.join(source_path, 'db.py')
        if os.path.exists(db_path): 
            shutil.copy(db_path, os.path.join(service_dir, 'db.py'))
        
        for shared in shared_libs:
            shared_src = os.path.join(source_path, shared['name'])
            if os.path.exists(shared_src):
                shutil.copytree(shared_src, os.path.join(service_dir, shared['name']), dirs_exist_ok=True)

    compose_content = env.get_template("docker-compose.jinja2").render(services=runnable_services)
    with open(os.path.join(output_path, "docker-compose.yaml"), "w") as f:
        f.write(compose_content)

    print("\n✅ Генерация завершена успешно!")
