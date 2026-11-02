"""
LIONREEL STUDIO — CONTRACT VERIFICATION SUITE
Scans all Python files via AST and verifies that every call to ClipLedger methods
strictly adheres to the method signature defined in clip_ledger.py.
Fails CI/startup if any unknown keyword argument or mismatched parameter is used.
"""

import ast
import inspect
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import clip_ledger

def check_all_contracts(target_dir=BASE_DIR, verbose=False):
    ledger_cls = clip_ledger.ClipLedger
    ledger_methods = {}
    for attr in dir(ledger_cls):
        if not attr.startswith("_"):
            func = getattr(ledger_cls, attr)
            if callable(func):
                ledger_methods[attr] = {
                    "func": func,
                    "sig": inspect.signature(func),
                    "params": inspect.signature(func).parameters
                }

    errors = []
    checked_calls = 0

    skip_dirs = {".venv", "venv", ".git", "__pycache__", "quarantine"}

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(".py"):
                fpath = os.path.join(root, f)
                rel_path = os.path.relpath(fpath, target_dir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                        tree = ast.parse(fh.read(), filename=fpath)
                except Exception as e:
                    if verbose:
                        print(f"[WARN] Failed to parse {rel_path}: {e}")
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        method_name = None
                        is_ledger_call = False

                        if isinstance(node.func, ast.Attribute):
                            attr_name = node.func.attr
                            # Match obj.ledger.method() or self.ledger.method() or ledger.method()
                            if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "ledger":
                                method_name = attr_name
                                is_ledger_call = True
                            elif isinstance(node.func.value, ast.Name) and node.func.value.id in ("ledger", "ClipLedger"):
                                method_name = attr_name
                                is_ledger_call = True
                            elif attr_name in ledger_methods:
                                # Could be a ledger method call
                                method_name = attr_name
                                is_ledger_call = True

                        if is_ledger_call and method_name in ledger_methods:
                            checked_calls += 1
                            m_info = ledger_methods[method_name]
                            sig = m_info["sig"]
                            params = m_info["params"]

                            has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

                            call_kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]
                            for kw_arg in call_kwargs:
                                if not has_var_kw and kw_arg not in params:
                                    msg = (f"{rel_path}:{node.lineno} -> Method 'ClipLedger.{method_name}()' "
                                           f"got unexpected keyword argument '{kw_arg}'. Allowed parameters: {list(params.keys())}")
                                    errors.append(msg)

                            # Check positional argument count
                            pos_args_count = len(node.args)
                            # inspect.signature on instance method includes 'self'
                            max_pos_params = sum(1 for p in params.values() if p.kind in (
                                inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                inspect.Parameter.VAR_POSITIONAL
                            ))
                            has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params.values())

                            if not has_var_pos and pos_args_count > max_pos_params:
                                msg = (f"{rel_path}:{node.lineno} -> Method 'ClipLedger.{method_name}()' "
                                       f"called with {pos_args_count} positional args but accepts at most {max_pos_params}")
                                errors.append(msg)

    return checked_calls, errors

if __name__ == "__main__":
    count, errs = check_all_contracts(verbose=True)
    if errs:
        print(f"[CONTRACT CHECK FAILED] Found {len(errs)} contract violations across {count} calls:")
        for e in errs:
            print(f"  ERROR: {e}")
        sys.exit(1)
    else:
        print(f"CONTRACT CHECK OK (verified {count} ClipLedger call sites across workspace)")
        sys.exit(0)
