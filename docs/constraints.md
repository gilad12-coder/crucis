# Constraints

34 constraints are available, all mechanically checked via Python AST analysis. No runtime execution needed.

Use any combination in `primary` or `secondary` gates in your [constraint profiles](configuration.md#constraint-profiles).

---

## Complexity & Size

Control how large and complex functions are allowed to be.

| Constraint | Type | Description |
|---|---|---|
| `max_cyclomatic_complexity` | `int` | Max McCabe complexity per function. Counts linearly independent paths through the control flow graph. |
| `max_cognitive_complexity` | `int` | Max SonarSource cognitive complexity per function. Like cyclomatic but penalizes nesting — deeply nested code scores higher than flat code with the same number of branches. |
| `max_lines_per_function` | `int` | Max lines in any single function (from `def` to last line). |
| `max_total_lines` | `int` | Max total lines in the file. |
| `max_time_complexity` | `str` | Max estimated time complexity based on loop nesting depth. Accepts: `"O(1)"`, `"O(log n)"`, `"O(n)"`, `"O(n log n)"`, `"O(n^2)"`, `"O(n^3)"`, `"O(2^n)"`. |
| `max_parameters` | `int` | Max parameters per function, excluding `self`/`cls`. |
| `max_nested_depth` | `int` | Max nesting depth of control flow structures (`if`/`for`/`while`/`try`/`with`). |
| `max_return_statements` | `int` | Max `return` statements in any single function. |
| `max_local_variables` | `int` | Max local variables in any single function (excludes parameters). |

??? example "Example profile"
    ```yaml
    primary:
      max_cyclomatic_complexity: 10
      max_cognitive_complexity: 15
      max_lines_per_function: 50
      max_parameters: 5
      max_nested_depth: 3
      max_time_complexity: "O(n log n)"
    ```

---

## Correctness

These catch real bugs — patterns that will cause incorrect behavior at runtime.

| Constraint | Description |
|---|---|
| `no_bare_except` | Disallow `except:` without specifying an exception type. Bare excepts catch `SystemExit` and `KeyboardInterrupt`, preventing clean shutdown. |
| `no_try_except_pass` | Disallow `except: pass` or `except SomeError: pass`. Silently swallowing exceptions makes bugs invisible. |
| `no_return_in_finally` | Disallow `return`, `break`, or `continue` inside `finally` blocks. These silently swallow any exception that was propagating. |
| `no_unreachable_code` | Disallow statements after `return`, `raise`, `break`, or `continue`. Dead code is either a logic error or leftover from refactoring. |
| `no_duplicate_dict_keys` | Disallow duplicate constant keys in dict literals (`{'a': 1, 'a': 2}`). The second value silently overwrites the first. |
| `no_loop_variable_closure` | Disallow closures inside `for` loops that capture the loop variable without a default argument. All closures will share the loop variable's final value. |
| `no_mutable_defaults` | Disallow mutable literals as default arguments (`def f(x=[])`). The default is shared across all calls, causing cross-call contamination. |
| `no_mutable_call_in_defaults` | Disallow function calls as default arguments (`def f(ts=datetime.now())`). The call executes once at definition time, not per call. Allows known-safe calls like `frozenset()`, `tuple()`, `Field()`. |
| `no_shadowing_builtins` | Disallow variable or function names that shadow Python builtins (`list`, `dict`, `type`, `id`, `input`, `open`, etc.). |
| `no_open_without_context_manager` | Disallow `open()` without a `with` statement. File descriptors leak if an exception occurs before `close()`. |

??? example "Example profile"
    ```yaml
    primary:
      no_bare_except: true
      no_unreachable_code: true
      no_mutable_defaults: true
      no_mutable_call_in_defaults: true
      no_duplicate_dict_keys: true
    ```

---

## Security

Prevent common vulnerability patterns.

| Constraint | Description |
|---|---|
| `no_eval` | Disallow `eval()`. Executes arbitrary Python expressions — code injection risk. |
| `no_exec` | Disallow `exec()`. Executes arbitrary Python statements — code injection risk. |
| `no_unsafe_deserialization` | Disallow `pickle.load()`, `pickle.loads()`, `pickle.Unpickler()`, `marshal.load()`, `marshal.loads()`. Deserializing untrusted data executes arbitrary code. |
| `no_unsafe_yaml` | Disallow `yaml.load()` without `Loader=SafeLoader`. The default YAML loader can instantiate arbitrary Python objects. |
| `no_shell_true` | Disallow `subprocess.run(cmd, shell=True)` and similar. Shell injection risk when any part of the command comes from user input. |
| `no_hardcoded_secrets` | Disallow string literals assigned to variables named `password`, `secret`, `token`, `api_key`, `access_key`, `secret_key`, or `private_key`. Credentials belong in environment variables or secret managers. |
| `no_requests_without_timeout` | Disallow `requests.get()`, `requests.post()`, etc. without a `timeout` parameter. Requests without timeouts can hang indefinitely. |

??? example "Example profile"
    ```yaml
    primary:
      no_eval: true
      no_exec: true
      no_unsafe_deserialization: true
      no_unsafe_yaml: true
      no_shell_true: true
      no_hardcoded_secrets: true
      no_requests_without_timeout: true
    ```

---

## Style & Documentation

| Constraint | Description |
|---|---|
| `require_docstrings` | Require docstrings on all functions and classes. Functions with parameters must include an `Args:` section. Functions with return values must include a `Returns:` section. |
| `require_type_annotations` | Require type annotations on all function parameters and return values (excluding `self`/`cls`). |
| `no_print_statements` | Disallow `print()` calls. Production code should use a logging framework. |
| `no_star_imports` | Disallow `from module import *`. Pollutes the namespace and makes it impossible to trace where names come from. |
| `no_global_state` | Disallow module-level mutable variable assignments (excludes `UPPER_CASE` constants). |
| `no_debugger_statements` | Disallow `import pdb`, `import ipdb`, `import pudb`, `breakpoint()`, and `from pdb import ...`. |
| `no_nested_imports` | Disallow import statements inside functions. Usually a workaround for circular imports, indicating a design issue. |
| `no_magic_numbers` | Disallow numeric literals other than -1, 0, 1, 2 inside function bodies. Exempt: `UPPER_CASE` module-level assignments, `Field()` kwargs, subscripts, power exponents. |
| `max_string_literal_repeats` | Max number of times the same string literal can appear in the file. Exempt: docstrings, `UPPER_CASE` assignments, type annotations, decorator args, dict keys. |
| `allowed_imports` | Whitelist of allowed import module names. Any import not in this list is flagged. |

??? example "Example profile"
    ```yaml
    secondary:
      require_docstrings: true
      require_type_annotations: true
      no_print_statements: true
      no_debugger_statements: true
      allowed_imports: ["os", "sys", "json", "pathlib"]
    ```

---

## Quick-copy profiles

Ready-to-use profiles. Copy the one that fits your needs into `constraints/profiles.yaml`.

### Minimal

Just keep complexity in check:

```yaml
profiles:
  minimal:
    primary:
      max_cyclomatic_complexity: 15
```

### Recommended

Catches real bugs and common security issues:

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
      no_magic_numbers: true
    secondary:
      require_docstrings: true
      no_print_statements: true
      no_debugger_statements: true
```

### Strict

Everything on. For when you want the tightest possible output:

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
