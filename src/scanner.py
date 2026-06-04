"""
scanner.py — unified project scanner for AMM-Docker.

scan_project_structure() is the single public entry point.
It auto-detects the project type and delegates to the right scanner:
  • Python monolith  → AST-based Blueprint/APIRouter/urlpatterns analysis
  • Java monolith    → java_scanner.scan_java_project()
  • Frontend present → frontend_scanner.scan_frontend_project()

All Python source analysis uses the built-in `ast` module —
immune to false positives from comments and string literals.
"""
import os
import ast
import json
from collections import defaultdict

import java_scanner
import frontend_scanner

# ─────────────────────────────────────────────────────────────────────────────
# Framework-agnostic constants
# ─────────────────────────────────────────────────────────────────────────────

# Router/Blueprint class names across popular Python web frameworks
ROUTER_CLASSES = frozenset({
    'Blueprint',   # Flask, Quart, Sanic
    'APIRouter',   # FastAPI
    'Router',      # Starlette
    'Namespace',   # Flask-RESTX / Flask-RESTPlus
})

# Which keyword argument carries the URL prefix for each router class
ROUTER_PREFIX_KWARG = {
    'Blueprint':  'url_prefix',
    'APIRouter':  'prefix',
    'Router':     'prefix',
    'Namespace':  'path',
}

# Variable-name suffixes to strip when deriving a service name from a var name
_VAR_SUFFIXES = (
    '_blueprint', '_bp', 'blueprint', 'bp',
    '_router',    '_route',   'router',   'route',
    '_api',       '_ns',      'ns',       '_resource',
)

# File names that strongly hint at a service entry-point (any framework)
SERVICE_FILES = frozenset({
    # Flask / generic REST
    'routes.py', 'views.py', 'api.py',
    'handlers.py', 'endpoints.py', 'resources.py',
    # FastAPI / Starlette
    'router.py', 'routers.py',
    # Django
    'urls.py',
})

IGNORE_DIRS = frozenset({
    '__pycache__', 'venv', 'env', '.venv',
    'node_modules', 'instance', 'migrations',
    'tests', 'test', '.git', 'dist', 'build', 'docker_out',
    '.tox', '.mypy_cache', '.pytest_cache',
})

# Root-level .py files that are entry points, not shared modules
_ROOT_ENTRY_FILES = frozenset({
    'run', 'app', 'wsgi', 'asgi', 'manage', 'setup',
    'conftest', 'init_db', 'settings', 'celery',
})


# ─────────────────────────────────────────────────────────────────────────────
# Project-type detection
# ─────────────────────────────────────────────────────────────────────────────

# Ordered list: first match wins. More specific frameworks go first.
_FRONTEND_FRAMEWORK_MAP = [
    ('next',           'next'),
    ('nuxt',           'nuxt'),
    ('@angular/core',  'angular'),
    ('svelte',         'svelte'),
    ('vue',            'vue'),
    ('react',          'react'),
]

# package.json locations to probe, relative to a candidate root dir.
# Covers flat repos (root-level package.json) and common monorepo layouts.
_FRONTEND_SEARCH_DIRS = ('', 'frontend', 'client', 'web', 'ui', 'app')


def _detect_frontend_framework(package_json_path):
    """
    Return the primary frontend framework name from a package.json file,
    or 'unknown' if the file cannot be read or no known framework is found.
    """
    try:
        with open(package_json_path, 'r', encoding='utf-8') as fh:
            pkg = json.load(fh)
    except Exception:
        return 'unknown'

    all_deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
    for pkg_name, framework in _FRONTEND_FRAMEWORK_MAP:
        if pkg_name in all_deps:
            return framework
    return 'unknown'


def detect_project_type(root_path):
    """
    Detect the technology stack of a project.

    Probes the root directory and one level of well-known subdirectories
    (frontend/, client/, web/, ui/, app/) so that both flat repos and common
    monorepo layouts are handled.

    Returns:
        {
            'backend':       'java' | 'python' | None,
            'build_tool':    'maven' | 'gradle' | 'gradle-kts' | None,
            'frontend':      'react' | 'vue' | 'angular' | 'svelte'
                             | 'next' | 'nuxt' | 'unknown' | None,
            'frontend_root': str | None,   # abs path to the dir with package.json
        }
    """
    try:
        entries = set(os.listdir(root_path))
    except OSError:
        return {'backend': None, 'build_tool': None, 'frontend': None, 'frontend_root': None}

    # ── Backend ──────────────────────────────────────────────────────────────
    has_java = (
        'pom.xml' in entries or
        'build.gradle' in entries or
        'build.gradle.kts' in entries
    )
    has_python = (
        'requirements.txt' in entries or
        any(
            f.endswith('.py') and os.path.isfile(os.path.join(root_path, f))
            for f in entries
        )
    )

    if has_java:
        backend = 'java'
        if 'pom.xml' in entries:
            build_tool = 'maven'
        elif 'build.gradle.kts' in entries:
            build_tool = 'gradle-kts'
        else:
            build_tool = 'gradle'
    elif has_python:
        backend = 'python'
        build_tool = None
    else:
        backend = None
        build_tool = None

    # ── Frontend ─────────────────────────────────────────────────────────────
    frontend = None
    frontend_root = None

    for subdir in _FRONTEND_SEARCH_DIRS:
        candidate = os.path.join(root_path, subdir) if subdir else root_path
        pkg_json = os.path.join(candidate, 'package.json')
        if os.path.isfile(pkg_json):
            detected = _detect_frontend_framework(pkg_json)
            if detected != 'unknown' or frontend is None:
                frontend = detected
                frontend_root = candidate
            break

    return {
        'backend':       backend,
        'build_tool':    build_tool,
        'frontend':      frontend,
        'frontend_root': frontend_root,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public helper: requirements.txt parser
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# AST helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ast(fpath):
    """
    Parse a Python source file into an AST.
    Returns None on SyntaxError, encoding error, or any IO failure.
    """
    try:
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        return ast.parse(source, filename=fpath)
    except Exception:
        return None


def _extract_str(node):
    """Return the string value of an AST Constant node, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_router_call(node):
    """
    True if node is a Call to any known router/blueprint class
    (bare name or attribute access, e.g. flask.Blueprint or APIRouter).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        (isinstance(func, ast.Name) and func.id in ROUTER_CLASSES) or
        (isinstance(func, ast.Attribute) and func.attr in ROUTER_CLASSES)
    )


def _get_router_class(call_node):
    """Return the router class name from a Call node."""
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _has_urlpatterns(fpath):
    """
    Return True if the file contains a top-level `urlpatterns = [...]`
    assignment (Django app indicator).
    """
    tree = _parse_ast(fpath)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'urlpatterns':
                    return True
    return False


def _extract_routers_ast(fpath):
    """
    Return {var_name: {'url_prefix': str|None}} for every router/blueprint
    assignment in the file.

    Handles:
      - bp = Blueprint(...)                          (Flask)
      - router = APIRouter(prefix='/users')          (FastAPI)
      - bp: Blueprint = Blueprint(...)               (annotated assignment)
      - bp = flask.Blueprint(...)                    (attribute access)

    Not fooled by comments, multi-line calls, or string literals.
    """
    tree = _parse_ast(fpath)
    if tree is None:
        return {}

    results = {}

    for node in ast.walk(tree):
        call = None
        var_name = None

        # var = Router(...)
        if isinstance(node, ast.Assign) and _is_router_call(node.value):
            call = node.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    break

        # var: Router = Router(...)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_router_call(node.value)
            and isinstance(node.target, ast.Name)
        ):
            call = node.value
            var_name = node.target.id

        if call is None or var_name is None:
            continue

        # Determine which kwarg carries the prefix for this router class
        router_class = _get_router_class(call)
        primary_kwarg = ROUTER_PREFIX_KWARG.get(router_class, 'url_prefix')

        url_prefix = None
        for kw in call.keywords:
            if kw.arg in (primary_kwarg, 'url_prefix', 'prefix'):
                url_prefix = _extract_str(kw.value)
                break

        results[var_name] = {'url_prefix': url_prefix}

    return results


def _collect_imports_ast(fpath):
    """
    Return the set of top-level module names imported in a file.

    Handles:
      - import X / import X.Y.Z                 → 'X'
      - from X import Y / from X.Y import Z     → 'X'
      - importlib.import_module('X.Y')           → 'X'
      - __import__('X')                          → 'X'

    Relative imports (level > 0) are ignored to prevent intra-package
    false edges in the dependency graph.
    """
    tree = _parse_ast(fpath)
    if tree is None:
        return set()

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split('.')[0])

        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported.add(node.module.split('.')[0])

        elif isinstance(node, ast.Call):
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr

            # importlib.import_module('pkg') and __import__('pkg')
            if func_name in ('import_module', '__import__') and node.args:
                mod_name = _extract_str(node.args[0])
                if mod_name:
                    imported.add(mod_name.split('.')[0])

    return imported


# ─────────────────────────────────────────────────────────────────────────────
# Directory-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_service_dir(dirpath, filenames):
    """
    A directory is a 'service' if it contains:
      - a known service-entry filename (any framework), OR
      - any .py file that defines a router/blueprint (any framework), OR
      - a urls.py or any .py file with urlpatterns (Django)
    """
    if not any(f.endswith('.py') for f in filenames):
        return False
    if any(f in SERVICE_FILES for f in filenames):
        return True
    for fname in filenames:
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(dirpath, fname)
        if _extract_routers_ast(fpath):
            return True
        if _has_urlpatterns(fpath):
            return True
    return False


def _service_name_from_var(var_name):
    """
    Derive a clean service name from a router/blueprint variable name.

    Examples:
      auth_bp          → auth
      auth_blueprint   → auth
      users_router     → users
      AuthAPIRouter    → authapiou  (falls back to lowercased name)
    """
    name = var_name.lower()
    for suffix in _VAR_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)]
            break
    return name.strip('_') or var_name.lower()


def _count_py_files(dirpath):
    total = 0
    for _, _, files in os.walk(dirpath):
        total += sum(1 for f in files if f.endswith('.py'))
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _scan_python_project(root_path):
    """
    Scan a Python monolith using AST analysis (framework-agnostic).

    Auto-decomposition: if a directory has ≥2 router definitions across
    its direct .py files, each router becomes its own microservice.
    Otherwise the whole directory is one service or shared library.
    """
    project_map = {
        "root": root_path,
        "modules": [],
        "dependencies": {},
        "files": []
    }

    print(f"🔍 [SCANNER] Начинаю анализ монолита: {root_path}")

    candidates = []
    per_file_container_dirs = set()

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith('.') and d not in IGNORE_DIRS
        ]

        rel_path = os.path.relpath(dirpath, root_path)

        # Root: only collect root-level requirements.txt
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

        # Collect router definitions from all direct .py files via AST
        all_router_defs = {}
        container_name = rel_path.split(os.sep)[-1]
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            routers = _extract_routers_ast(os.path.join(dirpath, fname))
            for var_name, info in routers.items():
                all_router_defs[(fname, var_name)] = info

        if len(all_router_defs) >= 2:
            # Multiple routers → auto-decompose each into its own service
            per_file_container_dirs.add(rel_path)
            print(f"   🔀 [DECOMPOSE] {rel_path}/ → {len(all_router_defs)} сервисов")

            for (fname, var_name), info in all_router_defs.items():
                url_prefix = info['url_prefix']
                if url_prefix:
                    service_name = url_prefix.strip('/').split('/')[0]
                else:
                    service_name = _service_name_from_var(var_name)

                module_name = fname[:-3]
                import_path = (
                    container_name if module_name == '__init__'
                    else f"{container_name}.{module_name}"
                )

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
            candidates.append({
                'rel_path': rel_path,
                'dirpath': dirpath,
                'depth': depth,
                'total_py_count': total_py_count,
                'is_service': _is_service_dir(dirpath, filenames),
            })

    # ── Second pass: deduplicate and build module list ──────────────────────

    # Mark parent directories of nested services as containers (skip them)
    claimed_prefixes = set()
    for c in candidates:
        if c['is_service'] and c['depth'] > 0 and 'module_file' not in c:
            parts = c['rel_path'].split(os.sep)
            for i in range(1, len(parts)):
                claimed_prefixes.add(os.sep.join(parts[:i]))

    for c in sorted(candidates, key=lambda x: x['depth']):
        rel_path = c['rel_path']
        is_service = c['is_service']

        # Skip the container dir when per-file decomposition applies
        if rel_path in per_file_container_dirs and 'module_file' not in c:
            continue

        # Skip non-service parent containers
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

        if 'module_file' in c:
            module['module_file'] = c['module_file']
            module['import_path'] = c['import_path']
            module['blueprint_var'] = c['blueprint_var']
            module['url_prefix'] = c['url_prefix']

        project_map["modules"].append(module)

        icon = "🚀" if is_service else "📚"
        suffix = f" [{c.get('url_prefix', '')}]" if 'url_prefix' in c else ""
        print(f"   {icon} [MODULE] {module_type}: {name} @ {rel_path}{suffix} (py: {c['total_py_count']})")

    # Root-level .py files → shared modules (models.py, config.py, db.py, etc.)
    # They're imported by services but never added as subdirectory candidates.
    try:
        root_entries = sorted(os.listdir(root_path))
    except OSError:
        root_entries = []

    for fname in root_entries:
        if not fname.endswith('.py'):
            continue
        stem = fname[:-3]
        if stem.startswith('_') or stem in _ROOT_ENTRY_FILES:
            continue
        if not os.path.isfile(os.path.join(root_path, fname)):
            continue
        project_map['modules'].append({
            'name': stem,
            'path': fname,
            'type': 'shared',
            'files_count': 1,
            'is_root_file': True,
        })
        print(f"   📄 [MODULE] shared: {stem} @ {fname} (root)")

    return project_map


def scan_project_structure(root_path):
    """
    Unified entry point: detect the project type, delegate to the right
    scanner, and attach frontend data when present.

    Always returns a dict that includes at minimum:
        root, language, project_type, modules, frontend (None if absent).

    Python projects additionally have: dependencies, files.
    Java projects additionally have: build_tool, framework, java_version,
        spring_boot_version, features, server_port, db_type, db_url,
        base_package, architecture, raw_deps.
    """
    ptype   = detect_project_type(root_path)
    backend = ptype['backend']

    print(f"🔍 [SCANNER] Тип проекта: backend={backend}  "
          f"frontend={ptype['frontend']}")

    # ── Backend ───────────────────────────────────────────────────────────────
    if backend == 'java':
        result = java_scanner.scan_java_project(root_path)
        result['language'] = 'java'
        # Keep keys consistent so the rest of the pipeline never KeyErrors
        result.setdefault('dependencies', {})
        result.setdefault('files', [])
    else:
        result = _scan_python_project(root_path)
        result['language'] = 'python'

    result['project_type'] = ptype

    # ── Frontend ──────────────────────────────────────────────────────────────
    frontend_root = ptype.get('frontend_root')
    if ptype['frontend'] and frontend_root:
        result['frontend'] = frontend_scanner.scan_frontend_project(frontend_root)
    else:
        result['frontend'] = None

    return result


def detect_framework(root_path, root_deps=None):
    """
    Detect the primary web framework used in a monolith project.

    Strategy (first match wins):
      1. Presence of manage.py in root  → Django
      2. Root requirements.txt package names
      3. Import statements in root-level .py files

    Returns one of: 'flask', 'fastapi', 'django', 'starlette', 'sanic',
    'tornado', 'aiohttp', or 'unknown'.
    """
    # Package-name → framework mapping (lowercase, strip version/extras)
    _PKG_MAP = {
        'flask': 'flask', 'quart': 'flask', 'flask-restx': 'flask',
        'flask-restful': 'flask', 'flask-smorest': 'flask',
        'fastapi': 'fastapi',
        'django': 'django',
        'starlette': 'starlette',
        'sanic': 'sanic',
        'tornado': 'tornado',
        'aiohttp': 'aiohttp',
        'uvicorn': 'fastapi',   # strong fastapi hint
    }

    # 1. manage.py presence → Django
    if os.path.exists(os.path.join(root_path, 'manage.py')):
        return 'django'

    # 2. Requirements.txt
    deps = root_deps or parse_requirements(
        os.path.join(root_path, 'requirements.txt')
    )
    for raw in deps:
        pkg = raw.split('==')[0].split('>=')[0].split('<=')[0] \
                 .split('[')[0].strip().lower()
        if pkg in _PKG_MAP:
            return _PKG_MAP[pkg]

    # 3. Import statements in root .py files
    try:
        root_files = [
            f for f in os.listdir(root_path)
            if f.endswith('.py') and os.path.isfile(os.path.join(root_path, f))
        ]
    except OSError:
        return 'unknown'

    for fname in root_files:
        imported = _collect_imports_ast(os.path.join(root_path, fname))
        for name in imported:
            fw = _PKG_MAP.get(name.lower())
            if fw:
                return fw

    return 'unknown'


def analyze_import_graph(root_path, modules):
    """
    Build a directed import graph between modules using AST.

    Resolves imports to modules by both module name AND directory name so that
    auto-decomposed services (whose derived name ≠ directory name) are still
    correctly connected.

    Handles: import X, from X import Y, importlib.import_module('X'),
    __import__('X'). Relative imports (level > 0) are ignored.
    """
    # Build: python_identifier → set of module names it may represent.
    # A module is reachable by:
    #   1. its logical name  (standard case: name == dir name)
    #   2. every path component  (handles nested paths and auto-decomposition
    #      where the derived service name ≠ the actual directory name)
    pkg_to_modules = defaultdict(set)
    for m in modules:
        pkg_to_modules[m['name']].add(m['name'])
        for part in m['path'].split(os.sep):
            if part:
                pkg_to_modules[part].add(m['name'])

    edges = []
    seen = set()

    for module in modules:
        # Root-level file modules are shared targets, not sources of imports
        if module.get('is_root_file'):
            continue

        module_path = os.path.join(root_path, module['path'])
        if not os.path.isdir(module_path):
            continue

        # All Python identifiers that refer to THIS module (skip self-edges)
        this_identifiers = {module['name'], module['path'].split(os.sep)[0]}

        # For auto-decomposed per-file services scan only their specific file,
        # not the entire shared directory (avoids false cross-service edges)
        if 'module_file' in module:
            files_to_scan = [os.path.join(module_path, module['module_file'])]
        else:
            files_to_scan = []
            for dirpath, _, filenames in os.walk(module_path):
                for filename in filenames:
                    if filename.endswith('.py'):
                        files_to_scan.append(os.path.join(dirpath, filename))

        for fpath in files_to_scan:
            imported = _collect_imports_ast(fpath)

            for import_name in imported:
                if import_name in this_identifiers:
                    continue

                for target_name in pkg_to_modules.get(import_name, set()):
                    if target_name == module['name']:
                        continue
                    edge = (module['name'], target_name)
                    if edge in seen:
                        continue
                    edges.append({'from': module['name'], 'to': target_name})
                    seen.add(edge)

    if edges:
        print(f"   📊 [IMPORT GRAPH] Найдено {len(edges)} связей:")
        for e in edges:
            print(f"      {e['from']} → {e['to']}")
    else:
        print("   📊 [IMPORT GRAPH] Межмодульных импортов не обнаружено")

    return edges


if __name__ == "__main__":
    pass
