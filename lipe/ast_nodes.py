"""AST-узлы Lipe Lang."""
from dataclasses import dataclass, field

# --- выражения ---
@dataclass
class Num: value: object; line: int = 0
@dataclass
class Str: value: str; line: int = 0
@dataclass
class Bool: value: bool; line: int = 0
@dataclass
class VarRef: name: str; line: int = 0            # %NAME%
@dataclass
class Name: name: str; line: int = 0              # голый идентификатор
@dataclass
class ListLit: items: list; line: int = 0
@dataclass
class BinOp: op: str; left: object; right: object; line: int = 0
@dataclass
class UnaryOp: op: str; operand: object; line: int = 0
@dataclass
class Call: func: str; args: list; line: int = 0  # func(...) или call func(...)
@dataclass
class Index: obj: object; index: object; line: int = 0
@dataclass
class RawCmd: text: str; line: int = 0            # "cmd ..." -> выполнить в оболочке

# --- операторы (statements) ---
@dataclass
class Echo: parts: list; no_newline: bool = False; silent: bool = False; line: int = 0
@dataclass
class SetVar: name: str; value: object; arith: bool = False; line: int = 0
@dataclass
class AppendVar: name: str; value: object; line: int = 0     # set NAME+==value
@dataclass
class PrependVar: name: str; value: object; line: int = 0    # set NAME-==value
@dataclass
class Assign: name: str; op: str; value: object; line: int = 0   # x += 1 (Python-стиль)
@dataclass
class IfStmt: cond: object; then_body: list; elif_branches: list; else_body: list; line: int = 0
@dataclass
class ForLoop: var: str; iterable: object; body: list; line: int = 0        # BAT: for X in ... do
@dataclass
class ForRange: var: str; start: object; end: object; step: object; body: list; line: int = 0  # Python: for i in range(...)
@dataclass
class WhileLoop: cond: object; body: list; line: int = 0
@dataclass
class FuncDef: name: str; params: list; defaults: list; body: list; line: int = 0
@dataclass
class Return: value: object; line: int = 0
@dataclass
class Goto: label: str; line: int = 0
@dataclass
class Label: name: str; line: int = 0
@dataclass
class Pause: line: int = 0
@dataclass
class Cls: line: int = 0
@dataclass
class Title: value: object; line: int = 0
@dataclass
class ExitStmt: code: object; line: int = 0
@dataclass
class ExprStmt: expr: object; line: int = 0
@dataclass
class WinlangSwitch: mode: str; line: int = 0      # winlang/bat | winlang/cmd | winlang/cpp
@dataclass
class CppBlock: code: str; line: int = 0           # cpp ... endcpp
