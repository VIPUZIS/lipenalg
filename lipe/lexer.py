"""Lipe Lang lexer — смесь Python и BAT/CMD."""
from dataclasses import dataclass, field

@dataclass
class Token:
    type: str
    value: object
    line: int
    col: int

KEYWORDS_BAT = {
    "echo", "set", "if", "else", "endif", "goto", "call", "pause",
    "for", "in", "do", "endfor", "exit", "rem", "cls",
}
KEYWORDS_PY = {"def", "enddef", "return", "while", "endwhile", "and", "or", "not", "true", "false"}
BUILTIN_NAMES = {"input", "print", "len", "str", "int", "float", "range", "abs", "min", "max", "system"}

OPERATORS3 = ["//=", "**"]
OPERATORS2 = ["==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "->"]
OPERATORS1 = "+-*/%=<>(),:.[]"

COMPARISON_OPS = {"==": "EQ", "!=": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE"}

class LipeSyntaxError(Exception):
    def __init__(self, msg, line=None):
        super().__init__(msg if line is None else f"{msg} (строка {line})")
        self.line = line

CPP_OPERATORS = set("+-*/%=<>!&|^~?:;,.()[]{}#")

def tokenize(source: str):
    CPPMODE = False
    toks = []
    i, line, col = 0, 1, 1
    n = len(source)

    def push(tp, val):
        toks.append(Token(tp, val, line, col))

    while i < n:
        ch = source[i]
        # --- режим C++: cpp ... endcpp (лексим дословно) ---
        if CPPMODE:
            if source.startswith("endcpp", i) and (i + 6 >= n or not (source[i+6].isalnum() or source[i+6] == "_")):
                before = "".join(source[k] for k in range(max(0, i-40), i))
                depth = before.count("{") - before.count("}")
                if depth <= 0:
                    CPPMODE = False
                    push("KW", "endcpp")
                    i += 6; col += 6
                    continue
            if ch == "\"":
                j = i + 1; buf = ['"']
                while j < n and source[j] != "\"":
                    if source[j] == "\\" and j + 1 < n:
                        buf.append(source[j]); buf.append(source[j+1]); j += 2
                    else:
                        if source[j] == "\n": line += 1
                        buf.append(source[j]); j += 1
                if j < n:
                    buf.append('"'); j += 1
                push("CPPSTR", "".join(buf))
                col += j - i; i = j; continue
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (source[j].isalnum() or source[j] == "_"):
                    j += 1
                push("ID", source[i:j])
                col += j - i; i = j; continue
            if ch.isdigit():
                j = i
                while j < n and (source[j].isdigit() or source[j] in ".xXabcdefABCDEF"):
                    j += 1
                push("NUMBER", source[i:j])
                col += j - i; i = j; continue
            if ch == "\n":
                push("NEWLINE", "\n"); i += 1; line += 1; col = 1; continue
            if ch in " \t\r":
                i += 1; col += 1; continue
            if ch in CPP_OPERATORS:
                push("OP", ch); i += 1; col += 1; continue
            raise LipeSyntaxError(f"Неизвестный символ '{ch}'", line)
        # --- перевод строки / перенос команд ---
        if ch == "\\":
            # экранирование в строках обрабатывается отдельно; здесь это перенос команды BAT (^-\стиль)
            if i + 1 < n and source[i+1] == "\n":
                i += 2; line += 1; col = 1; continue
            raise LipeSyntaxError("Символ '\\' вне переноса строки", line)
        if ch in " \t\r":
            i += 1; col += 1; continue
        if ch == "\n":
            push("NEWLINE", "\\n"); i += 1; line += 1; col = 1; continue
        # --- комментарии: rem / :: / # ---
        if source.startswith("rem", i) and (i + 3 >= n or not source[i+3].isalnum()):
            j = source.find("\n", i)
            i = n if j < 0 else j; continue
        if source.startswith("::", i):
            j = source.find("\n", i)
            i = n if j < 0 else j; continue
        if ch == "#":
            j = source.find("\n", i)
            i = n if j < 0 else j; continue
        # --- числа ---
        if ch.isdigit() or (ch == "." and i + 1 < n and source[i+1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (source[j].isdigit() or (source[j] == "." and not seen_dot)):
                if source[j] == ".": seen_dot = True
                j += 1
            text = source[i:j]
            push("NUMBER", float(text) if seen_dot else int(text))
            col += j - i; i = j; continue
        # --- строки ---
        if ch in "\"'":
            quote = ch; j = i + 1; buf = []
            while j < n and source[j] != quote:
                if source[j] == "\\" and j + 1 < n:
                    nxt = source[j+1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\"}.get(nxt, nxt))
                    j += 2
                else:
                    if source[j] == "\n": line += 1
                    buf.append(source[j]); j += 1
            if j >= n:
                raise LipeSyntaxError("Незакрытая строка", line)
            push("STRING", "".join(buf))
            col += (j + 1 - i); i = j + 1; continue
        # --- переменные BAT: %NAME% ---
        if ch == "%":
            j = source.find("%", i + 1)
            if j > 0:
                push("VAR", source[i+1:j])
                col += j + 1 - i; i = j + 1; continue
            raise LipeSyntaxError("Незакрытая переменная %...%", line)
        # --- операторы ---
        matched = False
        for op3 in OPERATORS3:
            if source.startswith(op3, i):
                push("OP", op3); i += 3; col += 3; matched = True; break
        if matched: continue
        for op2 in OPERATORS2:
            if source.startswith(op2, i):
                push("OP", op2); i += 2; col += 2; matched = True; break
        if matched: continue
        if ch == "&":
            push("AMP", "&"); i += 1; col += 1; continue
        if ch in OPERATORS1:
            push("OP", ch); i += 1; col += 1; continue
        # --- сырая строка после echo/cmd/title/set (BAT-стиль) ---
        if (toks and toks[-1].type in ("KW", "ID") and toks[-1].value in ("echo", "cmd", "title", "set")
                and ch not in "\r\n" and source[i-1] in " \t"):
            if toks[-1].value == "set":
                # set ИМЯ=значение — читаем имя переменной как обычный идентификатор
                if ch.isalpha() or ch == "_":
                    j = i
                    while j < n and (source[j].isalnum() or source[j] == "_"):
                        j += 1
                    push("ID", source[i:j])
                    col += j - i; i = j; continue
            elif ch.isalpha() or ch == "!":
                j = i
                while j < n and source[j] != "\n":
                    j += 1
                raw = source[i:j].rstrip(" \t\r")
                # спец-символы (кавычки, переменные, скобки) — не текст, их парсит parser
                if raw[:1] not in ("\"", "'", "%", "["):
                    push("RAWTEXT", raw)
                    col += j - i; i = j; continue
        # --- идентификаторы / ключевые слова (@ — префикс молчаливого echo из BAT) ---
        if ch == "@":
            i += 1; col += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            low = word.lower()
            if low == "echo" and i > 0 and source[i-1] == "@":   # @echo off -> выключение эха
                push("ECHO_OFF", low)
            elif low == "cpp":
                push("KW", "cpp")
                CPPMODE = True                      # дальше до endcpp — чистый C++
            elif low in BUILTIN_NAMES:
                push("BUILTIN", low)
            else:
                push("ID", word)
            col += j - i; i = j; continue
        # --- метки BAT: :label ---
        if ch == ":" and i + 1 < n and (source[i+1].isalnum() or source[i+1] == "_"):
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            push("LABEL", source[i+1:j])
            col += j - i; i = j; continue
        raise LipeSyntaxError(f"Неизвестный символ '{ch}'", line)
    push("EOF", None)
    return toks
