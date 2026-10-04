# tree-sitter-dart (vendored)

Canonical Dart grammar for tree-sitter, copied **unmodified** from:

- Repository: https://github.com/UserNobody14/tree-sitter-dart
- Commit: `be07cf7118d3dba06236a3f19541685a68209934` (2026-07-06)
- License: MIT (see `LICENSE`)

Why vendored (docs/PLAN.md 4.1, decision P7): Dart is the main language indexed,
the only PyPI wheel is published by an individual, and the upstream repository
cannot be installed as a git dependency (it has an SSH-only submodule). Only the
files needed to build the Python binding are kept; nothing is downloaded at build
or run time. `tests/unit/test_vendored_grammar.py` checks the hashes below, so
any change to these files must be a deliberate update of this record.

To update: copy the same files from a newer upstream commit, then regenerate the
table with `sha256sum` and update the commit above.

## SHA-256 of every vendored file

```
d270cb3a4985d75033bd77d875ccebff1d66e32788a3f727891e28d76132dd46  ./LICENSE
bec39635b3adac1f32d2f7a344b2f0464ed85aaff35c18785db23384e86ac86a  ./bindings/python/tree_sitter_dart/__init__.py
f317fb6d8d6cce00d8f47449ec5277dba4a8e121603224917c20782c00e44e95  ./bindings/python/tree_sitter_dart/__init__.pyi
48fa028a32613f9cfa0e403af8ef420c0c6e6c1c6788dabd10250638e64b3f9a  ./bindings/python/tree_sitter_dart/binding.c
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  ./bindings/python/tree_sitter_dart/py.typed
b196c3ca1ebd538e34ca617853816552d06dac7036f9d0af6cddc56766e1911e  ./pyproject.toml
669d716611acae5525a4a1dba2ee07e1071d05e92ac9f4daf0d80ecbf5d487cc  ./setup.py
af2c6d473ddd54f56603db77fa35e0bdbc8e4fb92d41c4bac69dc7e510eb9ca4  ./src/parser.c
07a7b7818b175e9460523e705dd88d20f7b5141bac95c593d4426e6d52284996  ./src/scanner.c
b29c1c9fb7cc82f58c84b376df1297d6e2737a1d655fd356db0859e3c29c2fea  ./src/tree_sitter/alloc.h
31e60a1bff6f715afacce03b5b70efe42b58371b4f9595dd4af52a577ff9608c  ./src/tree_sitter/array.h
180b893c8734778fd32f372dfbc27bd6ad1cd2221f26150b31256ff6716320d2  ./src/tree_sitter/parser.h
```
