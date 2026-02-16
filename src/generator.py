import re
import os
import shutil
from jinja2 import Environment, FileSystemLoader
import scanner

def sanitize_models(service_dir):
    """
    Удаляет жесткие SQL-связи (ForeignKey и relationship) из моделей,
    так как в микросервисах базы разделены.
    """
    print(f"🧹 Очистка моделей в {service_dir}...")
    for root, _, files in os.walk(service_dir):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 1. Удаляем db.ForeignKey('...')
                # Заменяем ", db.ForeignKey(...)" на пустоту
                new_content = re.sub(r",\s*db\.ForeignKey\([^)]+\)", "", content)
                
                # 2. Удаляем db.relationship(...)
                # Удаляем строки вида: orders = db.relationship(...)
                new_content = re.sub(r"^\s*\w+\s*=\s*db\.relationship\(.+\).*$", "", new_content, flags=re.MULTILINE)
                
                if content != new_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)

def create_stubs(service_build_dir, all_modules, current_service_name):
    """Создает заглушки (пустые пакеты) для соседних сервисов"""
    for module in all_modules:
        mod_name = module['name']
        if mod_name == current_service_name or mod_name in ['common', 'utils']:
            continue
            
        stub_dir = os.path.join(service_build_dir, mod_name)
        if not os.path.exists(stub_dir):
            os.makedirs(stub_dir)
            
            with open(os.path.join(stub_dir, "__init__.py"), "w") as f:
                f.write(f"# Stub for {mod_name}\n")
            
            # ИСПРАВЛЕНИЕ: Используем простую заглушку без MagicMock (чтобы избежать рекурсии)
            with open(os.path.join(stub_dir, "models.py"), "w") as f:
                f.write("""
import sys

class Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        # Если заглушку вызвали как функцию (например, Order(id=1)), возвращаем себя
        return self

    def __getattr__(self, name):
        # Если у заглушки спросили атрибут (например, Order.query), возвращаем себя
        return self

    def __iter__(self):
        # Если заглушку пытаются перебрать в цикле, возвращаем пустой список
        return iter([])

# ЗАМЕНА МОДУЛЯ:
# Мы говорим Python, что этот файл (модуль) — это экземпляр класса Stub.
# Теперь:
# from orders.models import Order -> сработает (вернет Stub)
# from orders.models import Product -> сработает (вернет Stub)
sys.modules[__name__] = Stub()
""")
                
def render_service(module_info, all_modules, all_deps_map, output_path, template_env, source_path):
    service_name = module_info['name']
    service_rel_path = module_info['path'] # Например: "users" или "."
    
    # Путь куда будем собирать сервис: docker_out/users
    service_build_dir = os.path.join(output_path, service_name)
    os.makedirs(service_build_dir, exist_ok=True)
    
    # 1. КОПИРОВАНИЕ КОДА
    # Копируем исходный код модуля в папку: docker_out/users/users
    abs_source_path = os.path.join(source_path, service_rel_path)
    service_code_dest = os.path.join(service_build_dir, service_name)
    
    if os.path.exists(service_code_dest): 
        shutil.rmtree(service_code_dest)
    
    if os.path.exists(abs_source_path):
        shutil.copytree(abs_source_path, service_code_dest)
    
    sanitize_models(service_build_dir)

    # Гарантируем наличие __init__.py
    if not os.path.exists(os.path.join(service_code_dest, "init.py")):
        with open(os.path.join(service_code_dest, "init.py"), "w") as f: f.write("")

    # 2. СОЗДАНИЕ ЗАГЛУШЕК (чтобы from orders.models import ... не ломало код)
    create_stubs(service_build_dir, all_modules, service_name)

    # 3. ГЕНЕРАЦИЯ ВСПОМОГАТЕЛЬНЫХ ФАЙЛОВ
    # API Bridge
    api_bridge_content = template_env.get_template("api_bridge.jinja2").render(service_name=service_name)
    with open(os.path.join(service_build_dir, "api_bridge.py"), "w") as f:
        f.write(api_bridge_content)

    # HTTP Client
    client_content = template_env.get_template("http_client.jinja2").render()
    with open(os.path.join(service_build_dir, "http_client.py"), "w") as f:
        f.write(client_content)

    # 4. СБОР ЗАВИСИМОСТЕЙ (ЕДИНЫЙ ФАЙЛ!)
    final_deps = set()
    
    # а) Глобальные зависимости (из корня)
    if '.' in all_deps_map:
        final_deps.update(all_deps_map['.'])
        
    # б) Локальные зависимости модуля
    if service_rel_path in all_deps_map:
        final_deps.update(all_deps_map[service_rel_path])
        
    # в) Системные зависимости (для работы мостов)
    final_deps.add("requests==2.31.0")
    final_deps.add("Flask==3.0.0")
    final_deps.add("Flask-SQLAlchemy==3.1.1")
    
    with open(os.path.join(service_build_dir, "requirements.txt"), "w") as f:
        f.write("\n".join(sorted(final_deps)))

    # 5. ENTRYPOINT (run.py)
    # Собираем карту сервисов для конфига: {'users': 'http://users:5000', ...}
    services_map = {m['name']: f"http://{m['name']}:5000" for m in all_modules if m['name'] not in ['utils', 'common']}
    
    # Используем шаблон entrypoint, но сохраняем как run.py
    entry_content = template_env.get_template("entrypoint.jinja2").render(
        service_name=service_name,
        services_map=services_map
    )
    with open(os.path.join(service_build_dir, "run.py"), "w") as f:
        f.write(entry_content)

    # 6. DOCKERFILE
    docker_content = template_env.get_template("Dockerfile.jinja2").render(
        service_name=service_name
    )
    with open(os.path.join(service_build_dir, "Dockerfile"), "w") as f:
        f.write(docker_content)
def run_generation(source_path=None, output_path=None):
    if not source_path or not os.path.exists(source_path):
        print("Ошибка: Путь к монолиту не указан")
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    templates_dir = os.path.join(project_root, "templates")
    
    # Очистка папки вывода
    if os.path.exists(output_path): shutil.rmtree(output_path)
    os.makedirs(output_path, exist_ok=True)

    # 1. СКАНИРОВАНИЕ
    scan_result = scanner.scan_project_structure(source_path)
    
    # Получаем карту всех зависимостей: {'users': ['pandas'], '.': ['flask']}
    all_deps_map = scan_result.get('dependencies', {})
    
    # Получаем список модулей (исключая мусор)
    modules = [m for m in scan_result.get('modules', []) 
               if m['name'] not in ['pycache', 'instance', 'templates', 'venv', '.git']]
    
    env = Environment(loader=FileSystemLoader(templates_dir))
    
    # 2. ГЕНЕРАЦИЯ СЕРВИСОВ
    for module in modules:
        try:
            render_service(module, modules, all_deps_map, output_path, env, source_path)
        except Exception as e:
            print(f"❌ Ошибка генерации сервиса {module['name']}: {e}")
            import traceback
            traceback.print_exc()

    # 3. КОПИРОВАНИЕ ОБЩИХ РЕСУРСОВ
    for service in modules:
        service_dir = os.path.join(output_path, service['name'])
        
        # Копируем ТОЛЬКО db.py (app.py больше не нужен, у нас есть run.py)
        db_path = os.path.join(source_path, 'db.py')
        if os.path.exists(db_path): 
            shutil.copy(db_path, os.path.join(service_dir, 'db.py'))
        
        # Копируем utils
        u_src = os.path.join(source_path, 'utils')
        if os.path.exists(u_src): 
            shutil.copytree(u_src, os.path.join(service_dir, 'utils'), dirs_exist_ok=True)

    # 4. DOCKER COMPOSE
    runnable_services = [s for s in modules if s['name'] not in ['utils', 'common']]
    compose_content = env.get_template("docker-compose.jinja2").render(services=runnable_services)
    with open(os.path.join(output_path, "docker-compose.yaml"), "w") as f:
        f.write(compose_content)

    print("✅ Генерация завершена успешно!")

if __name__ == "__main__":
    pass