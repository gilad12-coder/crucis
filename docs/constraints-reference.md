# Constraints Reference

44 constraints are available, all mechanically checked via Python AST analysis. No runtime execution needed.

List constraints flat in your profiles (`constraints/profiles.yaml`). They are auto-classified into **required** (blocking) or **advisory** based on the field type.

- **Required constraints** — hard gates. Violations cause regeneration.
- **Advisory constraints** — soft gates. Violations are reported but don't block.

The following fields are advisory (all others are required): `require_docstrings`, `no_print_statements`, `no_debugger_statements`, `no_global_state`, `require_type_annotations`, `no_nested_imports`, `no_star_imports`, `max_local_variables`.

The old nested `primary:`/`secondary:` format still works for backward compatibility, but the flat format is preferred.

---

## Complexity & Size

Control how large and complex functions are allowed to be.

| Constraint | Type | Description |
|---|---|---|
| `max_cyclomatic_complexity` | `int` | Max McCabe complexity per function |
| `max_cognitive_complexity` | `int` | Max SonarSource cognitive complexity per function (penalizes nesting) |
| `max_lines_per_function` | `int` | Max lines in any single function |
| `max_total_lines` | `int` | Max total lines in the file |
| `max_time_complexity` | `str` | Max estimated time complexity: `"O(1)"`, `"O(log n)"`, `"O(n)"`, `"O(n log n)"`, `"O(n^2)"`, `"O(n^3)"`, `"O(2^n)"` |
| `max_parameters` | `int` | Max parameters per function (excluding `self`/`cls`) |
| `max_nested_depth` | `int` | Max nesting depth of control flow structures |
| `max_return_statements` | `int` | Max `return` statements per function |
| `max_local_variables` | `int` | Max local variables per function (excludes parameters) |

---

## Correctness

Patterns that cause incorrect behavior at runtime.

| Constraint | Description |
|---|---|
| `no_bare_except` | Disallow `except:` without specifying an exception type |
| `no_try_except_pass` | Disallow `except: pass` or `except SomeError: pass` |
| `no_return_in_finally` | Disallow `return`/`break`/`continue` inside `finally` blocks |
| `no_unreachable_code` | Disallow statements after `return`, `raise`, `break`, or `continue` |
| `no_duplicate_dict_keys` | Disallow duplicate constant keys in dict literals |
| `no_loop_variable_closure` | Disallow closures capturing loop variables without default args |
| `no_mutable_defaults` | Disallow mutable literals as default arguments (`def f(x=[])`) |
| `no_mutable_call_in_defaults` | Disallow function calls as defaults (`def f(ts=datetime.now())`) |
| `no_shadowing_builtins` | Disallow names that shadow Python builtins |
| `no_open_without_context_manager` | Disallow `open()` without `with` statement |

---

## Security

Prevent common vulnerability patterns.

| Constraint | Description |
|---|---|
| `no_eval` | Disallow `eval()` |
| `no_exec` | Disallow `exec()` |
| `no_unsafe_deserialization` | Disallow `pickle.load()`, `marshal.load()`, etc. |
| `no_unsafe_yaml` | Disallow `yaml.load()` without `Loader=SafeLoader` |
| `no_shell_true` | Disallow `subprocess.run(cmd, shell=True)` |
| `no_hardcoded_secrets` | Disallow string literals in `password`/`secret`/`token` variables |
| `no_requests_without_timeout` | Disallow `requests.get()` etc. without `timeout` |

---

## Style & Documentation

| Constraint | Description |
|---|---|
| `require_docstrings` | Require docstrings on all functions and classes |
| `require_type_annotations` | Require type annotations on all parameters and return values |
| `no_print_statements` | Disallow `print()` calls |
| `no_star_imports` | Disallow `from module import *` |
| `no_global_state` | Disallow module-level mutable variable assignments |
| `no_debugger_statements` | Disallow `pdb`/`ipdb`/`breakpoint()` |
| `no_nested_imports` | Disallow import statements inside functions |
| `no_magic_numbers` | Disallow numeric literals other than -1, 0, 1, 2 inside functions |
| `max_string_literal_repeats` | Max times the same string literal can appear |
| `allowed_imports` | Whitelist of allowed import module names |

---

## Class & Module Metrics

Structural metrics for classes and modules.

| Constraint | Type | Description |
|---|---|---|
| `max_methods_per_class` | `int` | Max methods per class (SRP proxy) |
| `max_fields_per_class` | `int` | Max instance attributes per class |
| `max_class_lines` | `int` | Max total lines in any single class body |
| `max_weighted_methods_per_class` | `int` | Max sum of cyclomatic complexity across all methods in a class (WMC) |
| `max_efferent_coupling` | `int` | Max distinct imported modules |
| `min_maintainability_index` | `float` | Min Radon maintainability index (0–100, higher = better) |

---

## Python Idioms

Python-specific convention checks based on PEP 8 and common best practices.

| Constraint | Type | Description |
|---|---|---|
| `enforce_naming_conventions` | `bool` | PEP 8: snake_case functions/methods, CapWords classes |
| `no_single_char_names` | `bool` | Ban single-char variable names (loop/comprehension vars exempt) |
| `no_unnecessary_else_after_return` | `bool` | Flag `else` after `if` body ending in return/raise/break/continue |
| `no_len_as_condition` | `bool` | Flag `len(x) > 0`, `len(x) == 0`, `len(x) != 0` patterns |

---

## Quick-copy profiles

### Minimal

```yaml
profiles:
  minimal:
    max_cyclomatic_complexity: 15
```

### Recommended

```yaml
profiles:
  recommended:
    max_cyclomatic_complexity: 10
    max_cognitive_complexity: 15
    max_lines_per_function: 50
    max_parameters: 5
    max_nested_depth: 4
    no_bare_except: true
    no_unreachable_code: true
    no_mutable_defaults: true
    no_eval: true
    no_exec: true
    require_docstrings: true        # advisory
    no_print_statements: true        # advisory
    no_debugger_statements: true     # advisory
    no_magic_numbers: true
    max_methods_per_class: 20
    max_fields_per_class: 10
    max_class_lines: 200
    max_efferent_coupling: 15
    enforce_naming_conventions: true
    no_unnecessary_else_after_return: true
```

### Strict

```yaml
profiles:
  strict:
    max_cyclomatic_complexity: 5
    max_cognitive_complexity: 8
    max_lines_per_function: 30
    max_parameters: 3
    max_nested_depth: 3
    max_return_statements: 4
    max_local_variables: 5           # advisory
    max_time_complexity: "O(n)"
    no_bare_except: true
    no_try_except_pass: true
    no_return_in_finally: true
    no_unreachable_code: true
    no_duplicate_dict_keys: true
    no_loop_variable_closure: true
    no_mutable_defaults: true
    no_mutable_call_in_defaults: true
    no_shadowing_builtins: true
    no_open_without_context_manager: true
    no_eval: true
    no_exec: true
    no_unsafe_deserialization: true
    no_unsafe_yaml: true
    no_shell_true: true
    no_hardcoded_secrets: true
    no_requests_without_timeout: true
    require_docstrings: true         # advisory
    require_type_annotations: true   # advisory
    no_print_statements: true        # advisory
    no_star_imports: true            # advisory
    no_global_state: true            # advisory
    no_debugger_statements: true     # advisory
    no_nested_imports: true          # advisory
    max_methods_per_class: 10
    max_fields_per_class: 7
    max_class_lines: 100
    max_weighted_methods_per_class: 50
    max_efferent_coupling: 10
    min_maintainability_index: 20.0
    enforce_naming_conventions: true
    no_single_char_names: true
    no_unnecessary_else_after_return: true
    no_len_as_condition: true
```
