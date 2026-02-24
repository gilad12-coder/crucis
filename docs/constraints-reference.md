# Constraints Reference

34 constraints are available, all mechanically checked via Python AST analysis. No runtime execution needed.

Use any combination in `primary` or `secondary` gates in your constraint profiles (`constraints/profiles.yaml`).

- **Primary constraints** — hard gates. Violations cause regeneration.
- **Secondary constraints** — soft gates. Violations are reported but don't block.

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

## Quick-copy profiles

### Minimal

```yaml
profiles:
  minimal:
    primary:
      max_cyclomatic_complexity: 15
```

### Recommended

```yaml
profiles:
  recommended:
    primary:
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
    secondary:
      require_docstrings: true
      no_print_statements: true
      no_debugger_statements: true
      no_magic_numbers: true
```

### Strict

```yaml
profiles:
  strict:
    primary:
      max_cyclomatic_complexity: 5
      max_cognitive_complexity: 8
      max_lines_per_function: 30
      max_parameters: 3
      max_nested_depth: 3
      max_return_statements: 4
      max_local_variables: 5
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
    secondary:
      require_docstrings: true
      require_type_annotations: true
      no_print_statements: true
      no_star_imports: true
      no_global_state: true
      no_debugger_statements: true
      no_nested_imports: true
```
