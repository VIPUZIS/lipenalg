"""Lipe Lang parser — синтаксис смесь BAT/CMD и Python.

Пример:
    @echo off
    winlang/cmd
    title MyApp
    set NAME="Мир"
    echo Привет, %NAME%!
    def greet(who)
        echo Привет из функции, %who%
        return 0
    enddef
    call greet(%NAME%)
    for i in range(1, 4) do
        echo i = %i%
    endfor
    if %x% EQU 5 echo пять endif
    cpp
        int x = 2 + 2; printf("%d\n", x);
    endcpp
"""
from .lexer import tokenize, LipeSyntaxError, Token
from . import ast_nodes as A

BAT_CMP_MAP = {"EQU": "==", "NEQ": "!=", "LSS": "<", "LEQ": "<=", "GTR": ">", "GEQ": ">="}
BLOCK_ENDS = ("endif", "else", "endfor", "endwhile", "enddef", "endcpp")


class Parser:
    def __init__(self, source: str):
        self.src_lines = source.split("\n")
        self.toks = tokenize(source)
        self.pos = 0
        self._silent_next = False

    # ---------- помощники ----------
    def peek(self, off=0):
        return self.toks[min(self.pos + off, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def insert_token(self, tok):
        """Вернуть токен обратно в поток (используется для 'endif' внутри echo)."""
        self.toks.insert(self.pos, tok)

    def split_rawtext_tail(self, tk, word):
        """Если RAWTEXT заканчивается на '<word>' (endif/else), отщепить его."""
        txt = tk.value
        low = txt.lower()
        idx = -1
        for marker in (" " + word, "\t" + word):
            p = low.rfind(marker)
            if p != -1 and (p + len(marker) == len(low)):
                idx = p; break
        if idx == -1:
            return None
        head = txt[:idx].rstrip(" \t\r")
        self.toks[self.pos - 1] = Token("RAWTEXT", head, tk.line, tk.col)
        self.insert_token(Token("KW", word, tk.line, tk.col + idx))
        return head

    def at_kw(self, *words):
        t = self.peek()
        return t.type in ("KW", "ID", "BUILTIN") and t.value in words

    def expect_kw(self, word):
        t = self.next()
        if not (t.type in ("KW", "ID") and t.value == word):
            raise LipeSyntaxError(f"Ожидалось '{word}', найдено '{t.value}'", t.line)
        return t

    def skip_newlines(self):
        while self.peek().type == "NEWLINE":
            self.next()

    def end_stmt(self):
        t = self.peek()
        if t.type in ("NEWLINE", "EOF"):
            self.next()
            return True
        if t.type == "AMP":          # & — склейка команд как в BAT
            self.next()
            self.skip_newlines()
            return True
        if t.type == "KW" and t.value in BLOCK_ENDS:
            return True              # endif/else/call ... endif стоят на той же строке
        raise LipeSyntaxError(f"Неожиданный элемент '{t.value}' — ожидался конец строки", t.line)

    # ---------- выражения ----------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.at_kw("or"):
            self.next()
            node = A.BinOp("or", node, self.parse_and(), getattr(node, "line", 0))
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.at_kw("and"):
            self.next()
            node = A.BinOp("and", node, self.parse_not(), getattr(node, "line", 0))
        return node

    def parse_not(self):
        if self.at_kw("not"):
            t = self.next()
            return A.UnaryOp("not", self.parse_not(), t.line)
        return self.parse_compare()

    def parse_compare(self):
        left = self.parse_add()
        t = self.peek()
        op = None
        if t.type == "OP" and t.value in ("==", "!=", "<", ">", "<=", ">="):
            op = t.value; self.next()
        elif t.type == "KW" and t.value == "in":
            op = "in"; self.next()
        elif t.type in ("ID", "KW") and str(t.value).upper() in BAT_CMP_MAP:
            op = BAT_CMP_MAP[str(t.value).upper()]; self.next()
        if op:
            right = self.parse_add()
            left = A.BinOp(op, left, right, getattr(left, "line", t.line))
        return left

    def parse_add(self):
        node = self.parse_mul()
        while self.peek().type == "OP" and self.peek().value in ("+", "-"):
            op = self.next().value
            node = A.BinOp(op, node, self.parse_mul(), getattr(node, "line", 0))
        return node

    def parse_mul(self):
        node = self.parse_unary()
        while self.peek().type == "OP" and self.peek().value in ("*", "/", "//", "**"):
            op = self.next().value
            node = A.BinOp(op, node, self.parse_unary(), getattr(node, "line", 0))
        return node

    def parse_unary(self):
        t = self.peek()
        if t.type == "OP" and t.value in ("-", "+"):
            self.next()
            operand = self.parse_unary()
            if t.value == "-":
                if isinstance(operand, A.Num):
                    operand.value = -operand.value
                    return operand
                return A.UnaryOp("-", operand, t.line)
            return operand
        return self.parse_postfix()

    def parse_postfix(self):
        node = self.parse_atom()
        while self.peek().type == "OP" and self.peek().value == "[":
            t = self.next()
            idx = self.parse_expr()
            close = self.next()
            if close.type != "OP" or close.value != "]":
                raise LipeSyntaxError("Ожидался ']'", close.line)
            node = A.Index(node, idx, t.line)
        return node

    def parse_atom(self):
        t = self.peek()
        if t.type == "NUMBER":
            self.next(); return A.Num(t.value, t.line)
        if t.type == "STRING":
            self.next(); return A.Str(t.value, t.line)
        if t.type == "VAR":
            self.next(); return A.VarRef(t.value, t.line)
        if t.type == "KW" and t.value in ("true", "false"):
            self.next(); return A.Bool(t.value == "true", t.line)
        if t.type == "OP" and t.value == "(":
            self.next()
            e = self.parse_expr()
            c = self.next()
            if c.type != "OP" or c.value != ")":
                raise LipeSyntaxError("Ожидалась ')'", c.line)
            return e
        if t.type == "OP" and t.value == "[":
            self.next()
            items = []
            while True:
                if self.peek().type == "OP" and self.peek().value == "]":
                    self.next(); break
                if self.peek().type == "EOF":
                    raise LipeSyntaxError("Не хватает ']'", t.line)
                items.append(self.parse_expr())
                nt = self.next()
                if nt.type == "OP" and nt.value == ",":
                    continue
                if nt.type == "OP" and nt.value == "]":
                    break
                raise LipeSyntaxError("Ожидался ',' или ']'", nt.line)
            return A.ListLit(items, t.line)
        if t.type in ("ID", "BUILTIN", "KW"):
            self.next()
            name = str(t.value)
            if self.peek().type == "OP" and self.peek().value == "(":
                self.next()
                args = []
                if not (self.peek().type == "OP" and self.peek().value == ")"):
                    while True:
                        args.append(self.parse_expr())
                        nt = self.next()
                        if nt.type == "OP" and nt.value == ",":
                            continue
                        if nt.type == "OP" and nt.value == ")":
                            break
                        raise LipeSyntaxError("Ожидался ',' или ')'", nt.line)
                else:
                    self.next()
                return A.Call(name, args, t.line)
            return A.Name(name, t.line)
        raise LipeSyntaxError(f"Неожиданный элемент '{t.value}'", t.line)

    # ---------- операторы ----------
    def parse_program(self):
        body = []
        self.skip_newlines()
        while self.peek().type != "EOF":
            st = self.parse_statement()
            if st is not None:
                body.append(st)
            self.skip_newlines()
        return body

    def parse_statement(self):
        t = self.peek()
        if t.type == "KW" and t.value == "echo" and getattr(t, "silent", False):
            self._silent_next = True                 # @echo — молчаливый вывод
        if t.type == "KW":
            kw = t.value
            if kw == "echo":   return self.parse_echo()
            if kw == "set":    return self.parse_set()
            if kw == "if":     return self.parse_if()
            if kw == "for":    return self.parse_for()
            if kw == "while":  return self.parse_while()
            if kw == "def":    return self.parse_def()
            if kw == "call":   return self.parse_call()
            if kw == "return":
                self.next()
                val = None
                if not (self.peek().type in ("NEWLINE", "EOF") or
                        (self.peek().type == "KW" and self.peek().value in BLOCK_ENDS)):
                    val = self.parse_expr()
                self.end_stmt()
                return A.Return(val, t.line)
            if kw == "goto":
                self.next()
                lt = self.next()
                if lt.type not in ("ID", "LABEL", "STRING", "KW", "BUILTIN"):
                    raise LipeSyntaxError("Ожидалось имя метки после goto", lt.line)
                self.end_stmt()
                return A.Goto(str(lt.value), t.line)
            if kw == "pause":
                self.next(); self.end_stmt(); return A.Pause(t.line)
            if kw == "cls":
                self.next(); self.end_stmt(); return A.Cls(t.line)
            if kw == "title":
                self.next()
                if self.peek().type == "RAWTEXT":
                    rt = self.next()
                    v = A.Str(rt.value, rt.line)
                else:
                    v = self.parse_expr()
                self.end_stmt(); return A.Title(v, t.line)
            if kw == "exit":
                self.next()
                code = None
                if not (self.peek().type in ("NEWLINE", "EOF")):
                    code = self.parse_expr()
                self.end_stmt(); return A.ExitStmt(code, t.line)
            if kw in BLOCK_ENDS:
                raise LipeSyntaxError(f"Лишнее '{kw}'", t.line)
        if t.type == "LABEL":
            self.next(); self.end_stmt()
            return A.Label(t.value, t.line)
        if t.type == "KW" and t.value == "cpp":
            return self.parse_cpp_block()
        if t.type == "ID" and isinstance(t.value, str):
            low = t.value.lower()
            if low == "set":      return self.parse_set()
            if low == "winlang":  return self.parse_winlang()
            if low == "cmd":      return self.parse_raw_cmd()
            if low == "append":   return self.parse_appendvar()
            if low == "title":
                self.next()
                if self.peek().type == "RAWTEXT":
                    rt = self.next()
                    v = A.Str(rt.value, rt.line)
                else:
                    v = self.parse_expr()
                self.end_stmt(); return A.Title(v, t.line)
        # Python-стиль присваивания: x = expr / x += expr
        if t.type == "ID" and self.peek(1).type == "OP" and self.peek(1).value in ("=", "+=", "-=", "*=", "/="):
            self.next()
            op = self.next().value
            val = self.parse_expr()
            self.end_stmt()
            if op == "=":
                return A.SetVar(t.value, val, arith=False, line=t.line)
            return A.Assign(t.value, op, val, t.line)
        # остальное — выражение-оператор (print(...), greet(...) )
        e = self.parse_expr()
        self.end_stmt()
        return A.ExprStmt(e, getattr(e, "line", t.line))

    # echo текст/переменные/выражения [/n]
    def parse_echo(self):
        t = self.next()  # echo
        no_nl = False
        silent = getattr(self, "_silent_next", False)
        self._silent_next = False
        if self.peek().type == "OP" and self.peek().value == "/":
            save = self.pos
            self.next()
            nt = self.next()
            if nt.type in ("ID", "KW") and str(nt.value).lower() == "n":
                no_nl = True
            else:
                self.pos = save
        parts = []
        while True:
            tk = self.peek()
            if tk.type in ("NEWLINE", "EOF", "AMP"):
                break
            if tk.type == "KW" and tk.value in BLOCK_ENDS:
                break
            if tk.type == "RAWTEXT":
                self.next()
                # leftover " ... endif/else" в тексте — отщепляем ключевое слово
                for word in ("endif", "else"):
                    if self.split_rawtext_tail(tk, word) is not None:
                        if tk.value.strip():
                            parts.append(A.Str(tk.value.strip(), tk.line))
                        break
                else:
                    parts.append(A.Str(tk.value, tk.line))
                continue
            parts.append(self.parse_expr())
        if not parts:
            parts = [A.Str("", t.line)]
        self.end_stmt()
        return A.Echo(parts, no_newline=no_nl, silent=silent, line=t.line)

    # set X=..., set /a X=expr, set NAME+==..., set NAME-==...
    def parse_set(self):
        t = self.next()  # set
        arith = False
        if self.peek().type == "OP" and self.peek().value == "/":
            self.next()
            at = self.next()
            if at.type in ("ID", "KW") and str(at.value).lower() == "a":
                arith = True
        vt = self.next()
        if vt.type == "VAR":
            name = vt.value
        elif vt.type in ("ID", "KW", "BUILTIN", "STRING"):
            name = str(vt.value)
        else:
            raise LipeSyntaxError("Ожидалось имя переменной после set", vt.line)
        if self.peek().type == "OP" and self.peek().value in ("+=", "-="):
            kind = self.next().value
            eq = self.next()
            if not (eq.type == "OP" and eq.value == "="):
                raise LipeSyntaxError("Ожидался '==' в set", eq.line)
            val = self.parse_expr()
            self.end_stmt()
            return A.AppendVar(name, val, t.line) if kind == "+=" else A.PrependVar(name, val, t.line)
        eq = self.next()
        if not (eq.type == "OP" and eq.value == "="):
            raise LipeSyntaxError("Ожидался '=' в set", eq.line)
        val = self.parse_expr()
        self.end_stmt()
        return A.SetVar(name, val, arith=arith, line=t.line)

    def parse_appendvar(self):
        t = self.next()  # append
        vt = self.next()
        if vt.type == "VAR":
            name = vt.value
        elif vt.type in ("ID", "KW", "BUILTIN"):
            name = str(vt.value)
        else:
            raise LipeSyntaxError("Ожидалось имя переменной после append", vt.line)
        val = self.parse_expr()
        self.end_stmt()
        return A.AppendVar(name, val, t.line)

    # if COND ... endif (однострочная и блочная формы)
    def parse_if(self):
        t = self.expect_kw("if")
        cond = self.parse_if_cond()
        then_body, else_body = [], []
        if self.peek().type in ("NEWLINE", "AMP"):
            self.skip_newlines()
            then_body = self.parse_block(("endif", "else"))
            nxt = self.peek()
            if nxt.type == "KW" and nxt.value == "else":
                self.next()
                if self.peek().type in ("NEWLINE", "AMP"):
                    self.skip_newlines()
                    else_body = self.parse_block(("endif",))
                else:
                    while True:
                        tk = self.peek()
                        if tk.type == "KW" and tk.value == "endif":
                            break
                        if tk.type == "EOF":
                            raise LipeSyntaxError("Не хватает 'endif'", t.line)
                        st = self.parse_statement()
                        if st is not None:
                            else_body.append(st)
            self.expect_kw("endif")
            self.end_stmt()
            return A.IfStmt(cond, then_body, [], else_body, t.line)
        # inline: if cond echo hi [else echo yo] endif | if cond goto :lbl endif
        while True:
            tk = self.peek()
            if tk.type == "EOF":
                raise LipeSyntaxError("Не хватает 'endif'", t.line)
            if tk.type == "KW" and tk.value == "endif":
                break
            if tk.type == "KW" and tk.value == "else":
                self.next()
                while True:
                    tk2 = self.peek()
                    if tk2.type == "KW" and tk2.value == "endif":
                        break
                    if tk2.type == "EOF":
                        raise LipeSyntaxError("Не хватает 'endif'", t.line)
                    st = self.parse_statement()
                    if st is not None:
                        else_body.append(st)
                break
            st = self.parse_statement()
            if st is not None:
                then_body.append(st)
        self.expect_kw("endif")
        self.end_stmt()
        return A.IfStmt(cond, then_body, [], else_body, t.line)

    def parse_if_cond(self):
        left = self.parse_expr()
        # if exist "file" / if not exist ...
        if isinstance(left, A.Name) and left.name.lower() == "exist":
            path = self.parse_expr()
            return A.Call("_exists", [path], left.line)
        if isinstance(left, A.UnaryOp) and left.op == "not" and \
           isinstance(left.operand, A.Name) and left.operand.name.lower() == "exist":
            path = self.parse_expr()
            return A.UnaryOp("not", A.Call("_exists", [path], left.line), left.line)
        return left

    def parse_block(self, terminators):
        body = []
        self.skip_newlines()
        while True:
            t = self.peek()
            if t.type == "EOF":
                raise LipeSyntaxError(f"Не хватает закрывающего {terminators}", t.line)
            if t.type == "KW" and t.value in terminators:
                return body
            st = self.parse_statement()
            if st is not None:
                body.append(st)
            self.skip_newlines()

    def parse_for(self):
        t = self.expect_kw("for")
        vt = self.next()
        if vt.type == "VAR":
            var = vt.value
        elif vt.type in ("ID", "KW", "BUILTIN"):
            var = str(vt.value)
        else:
            raise LipeSyntaxError("Ожидалась переменная цикла", vt.line)
        self.expect_kw("in")
        iterable = self.parse_iterable()
        if self.at_kw("do"):
            self.next()
        self.skip_newlines()
        body = self.parse_block(("endfor",))
        self.expect_kw("endfor")
        self.end_stmt()
        if (isinstance(iterable, A.Call) and str(iterable.func).lower() == "range"):
            args = iterable.args
            start, end, step = None, None, None
            if len(args) == 1:
                end = args[0]
            elif len(args) >= 2:
                start, end = args[0], args[1]
            if len(args) >= 3:
                step = args[2]
            if start is None:
                start = A.Num(0, t.line)
            if step is None:
                step = A.Num(1, t.line)
            return A.ForRange(var, start, end, step, body, t.line)
        return A.ForLoop(var, iterable, body, t.line)

    def parse_iterable(self):
        t = self.peek()
        # for X in (a, b, c) do — BAT-список в скобках (слова без кавычек)
        if t.type == "OP" and t.value == "(":
            self.next()
            items = []
            while True:
                tk = self.peek()
                if tk.type == "OP" and tk.value == ")":
                    self.next(); break
                if tk.type == "EOF":
                    raise LipeSyntaxError("Не хватает ')'", t.line)
                items.append(self.parse_list_item())
                if self.peek().type == "OP" and self.peek().value == ",":
                    self.next()
            return A.ListLit(items, t.line)
        return self.parse_expr()

    def parse_list_item(self):
        t = self.peek()
        if t.type in ("ID", "KW", "BUILTIN") and not (self.peek(1).type == "OP" and self.peek(1).value == "("):
            self.next()
            return A.Str(str(t.value), t.line)
        return self.parse_expr()

    def parse_while(self):
        t = self.expect_kw("while")
        cond = self.parse_if_cond()
        self.skip_newlines()
        body = self.parse_block(("endwhile",))
        self.expect_kw("endwhile")
        self.end_stmt()
        return A.WhileLoop(cond, body, t.line)

    def parse_def(self):
        t = self.expect_kw("def")
        nt = self.next()
        if nt.type not in ("ID", "BUILTIN", "KW"):
            raise LipeSyntaxError("Ожидалось имя функции", nt.line)
        name = str(nt.value)
        params, defaults = [], []
        if self.peek().type == "OP" and self.peek().value == "(":
            self.next()
            while True:
                if self.peek().type == "OP" and self.peek().value == ")":
                    self.next(); break
                if self.peek().type == "EOF":
                    raise LipeSyntaxError("Не хватает ')' в def", nt.line)
                pt = self.next()
                if pt.type not in ("VAR", "ID", "KW", "BUILTIN"):
                    raise LipeSyntaxError("Ожидалось имя параметра", pt.line)
                pname = pt.value if pt.type == "VAR" else str(pt.value)
                default = None
                if self.peek().type == "OP" and self.peek().value == "=":
                    self.next()
                    default = self.parse_expr()
                params.append(pname)
                defaults.append(default)
                if self.peek().type == "OP" and self.peek().value == ",":
                    self.next()
        self.skip_newlines()
        body = self.parse_block(("enddef",))
        self.expect_kw("enddef")
        self.end_stmt()
        return A.FuncDef(name, params, defaults, body, t.line)

    def parse_call(self):
        t = self.expect_kw("call")
        nt = self.peek()
        if nt.type == "LABEL":                       # call :label — BAT-переход
            self.next(); self.end_stmt()
            return A.Goto(nt.value, t.line)
        if nt.type in ("ID", "BUILTIN", "KW") and self.peek(1).type == "OP" and self.peek(1).value == "(":
            expr = self.parse_expr()                 # call greet(a, b)
            self.end_stmt()
            return A.ExprStmt(expr, t.line)
        if nt.type in ("ID", "BUILTIN", "KW"):       # call greet a b — BAT-аргументы через пробел
            fname = str(self.next().value)
            args = []
            while True:
                tk = self.peek()
                if tk.type in ("NEWLINE", "EOF", "AMP"):
                    break
                if tk.type == "KW" and tk.value in BLOCK_ENDS:
                    break
                if tk.type == "RAWTEXT":
                    break
                args.append(self.parse_expr())
            self.end_stmt()
            return A.ExprStmt(A.Call(fname, args, t.line), t.line)
        raise LipeSyntaxError("После call ожидалось имя функции или :метка", nt.line)

    # winlang/bat | winlang/cmd | winlang/cpp
    def parse_winlang(self):
        t = self.next()  # winlang
        slash = self.next()
        if not (slash.type == "OP" and slash.value == "/"):
            raise LipeSyntaxError("Ожидался '/' после winlang (winlang/bat, winlang/cmd, winlang/cpp)", slash.line)
        mt = self.next()
        mode = str(mt.value).lower()
        # winlang/c++ -> cpp ("c" затем OP "**" или два "+")
        if mode == "c" and self.peek().type == "OP" and self.peek().value in ("+", "**"):
            opv = self.next().value
            if opv == "**":
                pass
            else:
                nt2 = self.next()   # второй '+'
                if not (nt2.type == "OP" and nt2.value == "+"):
                    raise LipeSyntaxError("Ожидался '+' в winlang/c++", nt2.line)
            mode = "cpp"
        if mode not in ("bat", "cmd", "cpp"):
            raise LipeSyntaxError(f"Неизвестный режим winlang/{mode}. Доступно: bat, cmd, cpp", mt.line)
        self.end_stmt()
        return A.WinlangSwitch(mode, t.line)

    # cpp ... endcpp — блок C++ (лексим дословно, потом реконструируем код)
    def parse_cpp_block(self):
        t = self.next()  # cpp
        stmt_lines = {}
        cur = t.line
        depth = 0
        parts = []
        while True:
            tk = self.peek()
            if tk.type == "EOF":
                raise LipeSyntaxError("Не хватает 'endcpp'", t.line)
            if tk.type == "KW" and tk.value == "endcpp" and depth <= 0:
                self.next(); break
            if tk.type == "NEWLINE":
                cur = tk.line + 1
                self.next(); continue
            if tk.type == "OP" and tk.value == "{":
                depth += 1
            elif tk.type == "OP" and tk.value == "}":
                depth -= 1
            stmt_lines.setdefault(cur, []).append(tk)
            parts.append(str(tk.value))
            self.next()
        # реконструкция по строкам исходника
        by_line = {}
        for ln, toks_ in stmt_lines.items():
            by_line[ln] = self.reconstruct_cpp_line(toks_)
        code = "\n".join(by_line[k] for k in sorted(by_line))
        self.end_stmt()
        return A.CppBlock(code, t.line)

    def reconstruct_cpp_line(self, toks):
        out = ""
        prev = None
        for tk in toks:
            val = str(tk.value)
            if prev is not None:
                need_space = False
                if prev.type == "NUMBER" or tk.type == "NUMBER":
                    need_space = True
                elif prev.type == "ID" and tk.type == "ID":
                    need_space = True
                elif prev.type == "OP" and prev.value == ";" and tk.type == "OP":
                    need_space = True
                elif prev.type == "OP" and prev.value == "#" and tk.type == "ID":
                    need_space = False   # #include
                elif tk.type == "OP" and tk.value in "()[]{},;.":
                    need_space = False
                elif prev.type == "OP" and prev.value in "([.":
                    need_space = False
                elif prev.type == "OP" and prev.value == "::":
                    need_space = False
                elif tk.type == "OP" and tk.value == "::":
                    need_space = False
                elif tk.type == "OP" and tk.value in "&*" and prev.type in ("OP", "ID"):
                    need_space = False
                elif prev.type == "OP" and tk.type == "OP":
                    need_space = True   # int x = ... ; два идентификатора через оператор
                else:
                    need_space = True
                out += (" " if need_space else "") + val
            else:
                out = val
            prev = tk
        return out

    # cmd "dir /b" — выполнить команду в системной оболочке
    def parse_raw_cmd(self):
        t = self.next()  # cmd
        parts = []
        while True:
            tk = self.peek()
            if tk.type in ("NEWLINE", "EOF", "AMP"):
                break
            if tk.type == "KW" and tk.value in BLOCK_ENDS:
                break
            if tk.type == "RAWTEXT":
                self.next()
                parts.append(A.Str(tk.value, tk.line))
                continue
            parts.append(self.parse_expr())
        self.end_stmt()
        text = " ".join(self.expr_to_cmd_text(p) for p in parts).strip()
        return A.RawCmd(text, t.line)

    def expr_to_cmd_text(self, e):
        if isinstance(e, A.Str):   return e.value
        if isinstance(e, A.Num):   return str(e.value)
        if isinstance(e, A.VarRef): return "${" + e.name + "}"
        if isinstance(e, A.Name):  return e.name
        return ""


def parse(source: str):
    return Parser(source).parse_program()
