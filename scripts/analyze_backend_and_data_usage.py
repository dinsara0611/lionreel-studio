import os
import sys
import ast
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Top-level entry points for backend & pipeline
ENTRY_POINTS = [
    "web_server.py",
    "lion_automate_v97.py",
    "qa_check.py",
    "clip_ledger.py",
    "pet_detector.py",
    "source_utils.py",
    "edl_manager.py",
    "metadata_generator.py",
    "stage_state_machine.py",
    "stage_timer.py",
    "watermark_detector.py",
    "tests/test_edit_step_e2e.py"
]

def get_ast_imports(filepath):
    imports = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except Exception as e:
        print(f"Error parsing AST for {filepath}: {e}")
    return imports

def get_string_references(filepath):
    strings = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # Find string literals that look like file names or relative paths
        matches = re.findall(r'["\']([a-zA-Z0-9_\-\.\/\\:]+\.[a-zA-Z0-9_]+)["\']', content)
        for m in matches:
            cleaned = m.replace('\\', '/')
            strings.add(cleaned)
    except Exception as e:
        pass
    return strings

def run():
    print("[1/3] Tracing backend import graph from entry points...")
    
    # Map of module name to file on disk
    workspace_py_files = {}
    for f in os.listdir(BASE_DIR):
        if f.endswith(".py"):
            mod_name = os.path.splitext(f)[0]
            workspace_py_files[mod_name] = f

    visited_modules = set()
    queue = []
    
    for ep in ENTRY_POINTS:
        if os.path.exists(os.path.join(BASE_DIR, ep)):
            mod = os.path.splitext(os.path.basename(ep))[0]
            queue.append(mod)
            visited_modules.add(mod)

    import_graph = {}
    
    while queue:
        current_mod = queue.pop(0)
        current_file = workspace_py_files.get(current_mod)
        if not current_file:
            continue
            
        full_path = os.path.join(BASE_DIR, current_file)
        direct_imports = get_ast_imports(full_path)
        import_graph[current_file] = list(sorted(direct_imports))
        
        for imp in direct_imports:
            if imp in workspace_py_files and imp not in visited_modules:
                visited_modules.add(imp)
                queue.append(imp)

    active_python_files = {workspace_py_files[m] for m in visited_modules if m in workspace_py_files}
    for ep in ENTRY_POINTS:
        if os.path.exists(os.path.join(BASE_DIR, ep)):
            active_python_files.add(ep)

    print(f"  -> Active Python modules ({len(active_python_files)}): {sorted(active_python_files)}")

    print("[2/3] Extracting file references and data files opened at runtime...")
    all_referenced_files = set()
    for py_file in active_python_files:
        p = os.path.join(BASE_DIR, py_file)
        if os.path.exists(p):
            refs = get_string_references(p)
            for r in refs:
                # Check if matches any file in workspace
                norm_r = os.path.normpath(r).replace('\\', '/')
                cand1 = os.path.join(BASE_DIR, norm_r)
                cand2 = os.path.join(BASE_DIR, os.path.basename(norm_r))
                try:
                    if os.path.exists(cand1):
                        all_referenced_files.add(os.path.relpath(cand1, BASE_DIR).replace('\\', '/'))
                    elif os.path.exists(cand2):
                        all_referenced_files.add(os.path.relpath(cand2, BASE_DIR).replace('\\', '/'))
                except ValueError:
                    if os.path.exists(cand1):
                        all_referenced_files.add(cand1.replace('\\', '/'))

    # Include config/, data/ databases, model weights, fonts, assets
    runtime_data_files = set()
    for d in ["config", "models", "reference"]:
        dp = os.path.join(BASE_DIR, d)
        if os.path.exists(dp):
            for root, _, files in os.walk(dp):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), BASE_DIR).replace('\\', '/')
                    runtime_data_files.add(rel)

    # Core data files
    for core_f in ["credits_registry.csv", "data/clip_ledger.db", "data/credits_registry.csv", "job_result.json"]:
        if os.path.exists(os.path.join(BASE_DIR, core_f)):
            runtime_data_files.add(core_f)

    # Output analysis
    result = {
        "active_python_modules": list(sorted(active_python_files)),
        "import_graph": import_graph,
        "string_referenced_files": list(sorted(all_referenced_files)),
        "runtime_data_files": list(sorted(runtime_data_files))
    }
    
    out_file = os.path.join(BASE_DIR, "analysis", "backend_in_use.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        
    print(f"[3/3] Analysis saved to {out_file}")

if __name__ == "__main__":
    run()
