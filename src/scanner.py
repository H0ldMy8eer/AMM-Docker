import os
import ast

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


# ─────────────────────────────────────────────────────────────────────────────
# AST helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ast(fpath):
    """Parse a Python source file into an AST. Returns None on any failure."""
    try:
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        return ast.parse(source, filename=fpath)
    except Exception:
        return None


def _is_blueprint_call(node):
    """True if node is a Call to Blueprint (bare name or attribute access)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        (isinstance(func, ast.Name) and func.id == 'Blueprint') or
        (isinstance(func, ast.Attribute) and func.attr == 'Blueprint')
    )


def _extract_str(node):
    """Return the string value of an AST Constant node, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_blueprints_ast(fpath):
    """
    Return {var_name: {'url_prefix': str|None}} for every Blueprint assignment
    found in the file.

    Handles:
      - bp = Blueprint(...)
      - bp: Blueprint = Blueprint(...)
      - bp = flask.Blueprint(...)

    Not fooled by commented-out code, string literals, or multi-line calls.
    """
    tree = _parse_ast(fpath)
    if tree is None:
        return {}

    results = {}

    for node in ast.walk(tree):
        call = None
        var_name = None

        # bp = Blueprint(...)
        if isinstance(node, ast.Assign) and _is_blueprint_call(node.value):
            call = node.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    break

        # bp: Blueprint = Blueprint(...)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_blueprint_call(node.value)
            and isinstance(node.target, ast.Name)
        ):
            call = node.value
            var_name = node.target.id

        if call is None or var_name is None:
            continue

        url_prefix = None
        for kw in call.keywords:
            if kw.arg == 'url_prefix':
                url_prefix = _extract_str(kw.value)
                break

        results[var_name] = {'url_prefix': url_prefix}

    return results


def _collect_imports_ast(fpath):
    """
    Return the set of top-level module names imported in a file.

    Handles:
      - import X           → 'X'
      - import X.Y.Z       → 'X'
      - from X import Y    → 'X'
      - from X.Y import Z  → 'X'

    Ignores relative imports (level > 0) to avoid false edges within a package.
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
    return imported


# ─────────────────────────────────────────────────────────────────────────────
# Directory-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_service_dir(dirpath, filenames):
    """
    A directory is a 'service' if it contains a known service filename
    (routes.py, views.py, …) OR if any .py file defines a Blueprint.
    """
    if not any(f.endswith('.py') for f in filenames):
        return False
    if any(f in SERVICE_FILES for f in filenames):
        return True
    for fname in filenames:
        if fname.endswith('.py') and _extract_blueprints_ast(os.path.join(dirpath, fname)):
            return True
    return False


def _service_name_from_var(var_name):
    """auth_bp / auth_blueprint / AuthBlueprint → 'auth'"""
    name = var_name.lower()
    for suffix in ('_blueprint', '_bp', 'blueprint', 'bp'):
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

def scan_project_structure(root_path):
    """
    Scan a monolith project using AST analysis.

    Auto-decomposition rule: if a directory has ≥2 Blueprint definitions
    across its direct .py files, each Blueprint becomes its own microservice.
    Otherwise the whole directory is treated as one service or shared library.
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

        # Root dir: only collect root requirements.txt
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

        # Collect Blueprint definitions from all direct .py files via AST
        all_bp_defs = {}
        container_name = rel_path.split(os.sep)[-1]
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            bps = _extract_blueprints_ast(os.path.join(dirpath, fname))
            for var_name, info in bps.items():
                all_bp_defs[(fname, var_name)] = info

        if len(all_bp_defs) >= 2:
            # Multiple Blueprints → auto-decompose each into its own service
            per_file_container_dirs.add(rel_path)
            print(f"   🔀 [DECOMPOSE] {rel_path}/ → {len(all_bp_defs)} сервисов")

            for (fname, var_name), info in all_bp_defs.items():
                url_prefix = info['url_prefix']
                if url_prefix:
                    service_name = url_prefix.strip('/').split('/')[0]
                else:
                    service_name = _service_name_from_var(var_name)

                module_name = fname[:-3]
                import_path = container_name if module_name == '__init__' \
                    else f"{container_name}.{module_name}"

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

    # Parent directories of nested services are just containers — don't add them
    claimed_prefixes = set()
    for c in candidates:
        if c['is_service'] and c['depth'] > 0 and 'module_file' not in c:
            parts = c['rel_path'].split(os.sep)
            for i in range(1, len(parts)):
                claimed_prefixes.add(os.sep.join(parts[:i]))

    for c in sorted(candidates, key=lambda x: x['depth']):
        rel_path = c['rel_path']
        is_service = c['is_service']

        # Skip the container directory when per-file decomposition applies
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

    return project_map


def analyze_import_graph(root_path, modules):
    """
    Build an import graph between modules using AST.

    Only absolute imports are considered; relative imports (level > 0) are
    ignored to avoid intra-package false edges.
    """
    module_names = {m['name'] for m in modules}
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
                imported = _collect_imports_ast(os.path.join(dirpath, filename))

                for target_name in imported:
                    if target_name == module['name']:
                        continue
                    if target_name not in module_names:
                        continue
                    edge = (module['name'], target_name)
                    if edge in seen:
                        continue
                    edges.append({'from': module['name'], 'to': target_name})
                    seen.add(edge)

    return edges


if __name__ == "__main__":
    pass
