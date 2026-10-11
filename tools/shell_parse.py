"""SHELL PARSE: the one reader of what a shell command runs, and where. Every command guard reads a
command through `read`; no guard splits, tokenizes or unquotes a command itself. No policy lives
here: it answers structural questions and refuses nothing.

`read` returns each statement the command runs, in order, with its words unquoted, reading the
command as bash or, for the PowerShell tool, as PowerShell:

  * statements end at ; & && || | ;; a line break, and the ( ) or { } of a group, outside quotes;
  * a statement behind a keyword (if, then, elif, else, do, while, until, !) or a wrapper (env,
    time, nice, nohup, sudo, stdbuf, xargs, timeout N, command, exec, call) is the command it
    wraps; leading VAR=val (PowerShell $env:VAR=val, $x = ) assignments are its `env`;
  * nested statements come before the statement that runs them: a command substitution $( ),
    `` (bash) and <( ), a ( ), @( ) or { } script block inside a statement, a shell's command
    string (bash/sh/zsh/dash/ksh -c, pwsh/powershell -Command, cmd /c or /k, eval, iex), a heredoc
    or <<< string fed to a shell, echo/printf/Write-Output text or a cat heredoc piped into one,
    and find's -exec command;
  * text in quotes is one word, never a statement; a heredoc body or a PowerShell here-string is
    data unless a shell reads it;
  * cd, pushd, chdir, Set-Location and sl set the `cwd` of the statements after them (a group or
    nested command keeps its own).

The lexer is written by hand, not on `shlex`: shlex (posix, punctuation_chars) glues a line break
into a word, splits `$(` into `$` and `(`, gives `"$(x)"` (runs x) and `'$(x)'` (text) the same
word, knows no backticks, heredocs or PowerShell, and drops the backslashes of a Windows path
(`C:\\Git\\cmd\\git.exe` becomes `C:Gitcmdgit.exe`). In bash a backslash escapes only a quote, `$`,
a backtick, a backslash, whitespace or a shell operator, and is a character before anything else;
in PowerShell the backtick is the escape and a backslash is always a character.

Not seen: a command built at run time (a variable expanded into a command, `$cmd`), a script file
a statement runs, a PowerShell -EncodedCommand, text piped into a shell from any other program, a
PowerShell here-string's $( ) and an alias or function defined earlier.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

_WINDOWS = os.name == "nt"
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[/\\]|[/\\])")
#: MSYS / Cygwin drive spellings: the Bash tool on this host is Git Bash, so `cd "/c/Users/..."` is
#: the ordinary form.
_MSYS_DRIVE_RE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def _msys_to_windows(path: str) -> str:
    if not _WINDOWS or not path:
        return path
    m = _MSYS_DRIVE_RE.match(path.replace("\\", "/"))
    if not m:
        return path
    rest = path.replace("\\", "/")[m.end():]
    return f"{m.group(1).upper()}:{rest or '/'}"


def normalize_repo(path) -> str:
    """Repository identity: absolute, forward slashes, case-folded on Windows (a drive letter
    spelled upper- or lower-case is one repository)."""
    try:
        p = Path(_msys_to_windows(str(path))).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return ""
    s = str(p).replace("\\", "/").rstrip("/")
    return s.casefold() if _WINDOWS else s


def repo_root_of(path) -> str:
    """Normalized root of the git repository containing `path`, or "" when there is none. Reads the
    filesystem only: a PreToolUse hook runs on every command, so no `git` subprocess here."""
    try:
        p = Path(_msys_to_windows(str(path))).expanduser()
        if not p.exists():
            return ""
        p = p.resolve()
        if p.is_file():
            p = p.parent
        for cand in (p, *p.parents):
            if (cand / ".git").exists():
                return normalize_repo(cand)
    except (OSError, ValueError, RuntimeError):
        return ""
    return ""


def _join_dir(base: str, path: str) -> str:
    """Resolve `path` against `base`; "" when it is relative and `base` is unknown."""
    path = _msys_to_windows(path)
    if _ABS_RE.match(path):
        return path
    if not base:
        return ""
    return os.path.join(_msys_to_windows(base), path)


def program_name(token: str) -> str:
    """The program a command word runs, however it is spelled, on every OS:
    `C:\\Git\\cmd\\git.exe`, `/usr/bin/git` and `Git.EXE` are all `git`."""
    return PureWindowsPath(token.strip("\"'")).name.lower().removesuffix(".exe")


@dataclass(frozen=True, eq=False)
class Statement:
    """One command the shell runs: its words unquoted, program first; the same words as written;
    its redirects as (operator, target); its heredoc body (None without one); its leading
    assignments; the directory it runs in ("" when unknown); the statement a pipe takes its input
    from (None when it is not piped)."""
    words: tuple[str, ...]
    raw: tuple[str, ...]
    redirects: tuple[tuple[str, str], ...] = ()
    heredoc: str | None = None
    env: tuple[str, ...] = ()
    cwd: str = ""
    upstream: Statement | None = None

    @property
    def program(self) -> str:
        return program_name(self.words[0]) if self.words else ""

    @property
    def text(self) -> str:
        return " ".join(self.raw)

    @property
    def stdin(self) -> str | None:
        """The text it reads on stdin when the command itself holds it: its heredoc or <<< string,
        or what a pipe hands it from echo/printf/Write-Output, a printed PowerShell string or a
        cat heredoc; None otherwise."""
        if self.heredoc is not None:
            return self.heredoc
        strings = [t for op, t in self.redirects if op.endswith("<<<")]
        up = self.upstream
        if strings or up is None:
            return strings[0] if strings else None
        if up.program in _PRINTERS:
            return " ".join(up.words[1:])
        if len(up.raw) == 1 and up.raw[0][:1] in "\"'@":          # a PowerShell string printed into the pipe
            return up.words[0]
        return up.heredoc if up.program == "cat" else None

    @property
    def writes(self) -> list[str]:
        """The files its redirects write: `>`, `>>`, `N>`, `>|`, `&>` (not an fd dup like `2>&1`)."""
        return [t for op, t in self.redirects if _WRITE_REDIRECT.fullmatch(op)]


def read(cmd: str, cwd: str = "", powershell: bool = False) -> list[Statement]:
    """Every statement `cmd` runs, in order; `cwd` is the directory it starts in; `powershell`
    reads it as PowerShell (the PowerShell tool), else as bash."""
    return _read(cmd or "", {"cwd": str(cwd or ""), "last": None, "ps": powershell}, None)


# ── lexing ───────────────────────────────────────────────────────────────────────────────────
_SPACE = " \t\r"
#: what ends an unquoted word
_WORD_END = _SPACE + "\n;&|<>)}"
#: what a backslash escapes outside quotes, in bash
_ESCAPED = set(_SPACE + "\"'\\$`;&|<>(){}#*?[]~!")
_SEPARATORS = (("&&", "&&"), ("||", "||"), (";;", ";"), ("|&", "|"), (";", ";"), ("|", "|"), ("&", "&"))
_REDIRECT = re.compile(r"\d*(?:<<<|<<-|<<|<>|<&|>>|>&|>\||<|>)|&>>|&>")
_WRITE_REDIRECT = re.compile(r"\d*>>?\|?|&>>?")
_HEREDOC_OP = re.compile(r"<<-?(?!<)\s*(['\"]?)\\?(?P<tag>[\w.-]+)\1")
_HERE_STRING = re.compile(r"@(['\"])\r?\n")


@dataclass
class _Word:
    value: str
    raw: str
    nested: list[str]


def _heredoc_body(s: str, i: int, tag: str) -> tuple[str, int]:
    """The body starting at `i` up to the line that is `tag`, and the index of that line's end."""
    lines = []
    while i <= len(s):
        k = s.find("\n", i)
        k = len(s) if k < 0 else k
        if s[i:k].strip() == tag:
            return "\n".join(lines), k
        lines.append(s[i:k])
        i = k + 1
    return "\n".join(lines), len(s)


class _Lexer:
    """The tokens of one command text, read as bash or (`ps`) as PowerShell."""

    def __init__(self, s: str, ps: bool):
        self.s, self.ps = s, ps
        self.escape = "`" if ps else "\\"

    def close(self, i: int, opener: str = "(", closer: str = ")") -> int:
        """Index of the `closer` matching an `opener` just before `i`, past quotes and heredoc
        bodies; len(s) if none."""
        s, depth, tags = self.s, 1, []
        while i < len(s):
            c = s[i]
            if c == self.escape:
                i += 2
            elif c == "'":
                i = self.single(i + 1, [])
            elif c == '"':
                i = self.double(i + 1, [], [])
            elif c == "<" and not self.ps and (m := _HEREDOC_OP.match(s, i)):
                tags.append(m.group("tag"))
                i = m.end()
            elif c == "\n" and tags:
                for tag in tags:
                    _body, i = _heredoc_body(s, i + 1, tag)
                tags = []
            else:
                depth += (c == opener) - (c == closer)
                if depth == 0:
                    return i
                i += 1
        return len(s)

    def single(self, i: int, value: list[str]) -> int:
        """The inside of a single-quoted string opened before `i` (`''` is a quote in PowerShell);
        returns the index past its close."""
        s = self.s
        while True:
            j = s.find("'", i)
            if j < 0:
                value.append(s[i:])
                return len(s)
            value.append(s[i:j])
            if self.ps and s[j + 1:j + 2] == "'":
                value.append("'")
                i = j + 2
            else:
                return j + 1

    def double(self, i: int, value: list[str], nested: list[str]) -> int:
        """The inside of a double-quoted string opened before `i`; returns the index past its close."""
        s = self.s
        while i < len(s):
            c = s[i]
            if c == '"':
                if self.ps and s[i + 1:i + 2] == '"':
                    value.append('"')
                    i += 2
                    continue
                return i + 1
            if c == self.escape and (self.ps or s[i + 1:i + 2] in ('"', "\\", "$", "`", "\n")):
                value.append("" if s[i + 1:i + 2] == "\n" else s[i + 1:i + 2])
                i += 2
            elif s.startswith("$(", i):
                i = self.substitution(i, value, nested)
            elif c == "`":
                i = self.backtick(i, value, nested)
            else:
                value.append(c)
                i += 1
        return i

    def substitution(self, i: int, value: list[str], nested: list[str]) -> int:
        """At `$(` / `@(` (i on the sigil): the text joins the word and its command `nested`;
        `$(( ))` is arithmetic and runs nothing. Returns the index past it."""
        j = self.close(i + 2)
        inner = self.s[i + 2:j]
        if not (self.s[i] == "$" and inner.startswith("(")):
            nested.append(inner)
        value.append(self.s[i:j + 1])
        return j + 1

    def backtick(self, i: int, value: list[str], nested: list[str]) -> int:
        j = self.s.find("`", i + 1)
        if j < 0:
            value.append("`")
            return i + 1
        nested.append(self.s[i + 1:j])
        value.append(self.s[i:j + 1])
        return j + 1

    def substituted(self, text: str) -> list[str]:
        """The commands substituted inside `text`, a ( ) or ${ } within a word (`a=($(x))`)."""
        words = [t[1] if t[0] == "w" else t[2] for t in _Lexer(text, self.ps).tokens() if t[0] in ("w", "redir")]
        return [n for w in words for n in w.nested]

    def word(self, i: int) -> _Word:
        """The word starting at `i`: quotes removed, substitutions recorded in `nested`."""
        s, start, value, nested = self.s, i, [], []
        while i < len(s) and s[i] not in _WORD_END:
            c = s[i]
            if c == "'":
                i = self.single(i + 1, value)
            elif c == '"':
                i = self.double(i + 1, value, nested)
            elif not self.ps and s.startswith("$'", i):          # $'...': a backslash escapes in it
                i += 2
                while i < len(s) and s[i] != "'":
                    value.append(s[i + 1:i + 2] if s[i] == "\\" else s[i])
                    i += 2 if s[i] == "\\" else 1
                i += 1
            elif self.ps and (m := _HERE_STRING.match(s, i)):    # @' ... '@: data
                end = s.find("\n" + m.group(1) + "@", m.end() - 1)
                end = len(s) if end < 0 else end
                value.append(s[m.end():end])
                i = min(end + 3, len(s))
            elif c == self.escape:
                nxt = s[i + 1:i + 2]
                if nxt == "\n":
                    i += 2
                elif nxt and (self.ps or nxt in _ESCAPED):
                    value.append(nxt)
                    i += 2
                else:
                    value.append(c)
                    i += 1
            elif c == "`":
                i = self.backtick(i, value, nested)
            elif c in "$@" and s[i + 1:i + 2] == "(":
                i = self.substitution(i, value, nested)
            elif c in "$@" and s[i + 1:i + 2] == "{":           # ${var}, a PowerShell @{} table
                j = self.close(i + 2, "{", "}")
                nested += self.substituted(s[i + 2:j])
                value.append(s[i:j + 1])
                i = j + 1
            elif c in "({":                    # inside a word: `.Kill()`, `::Start('x')`, `a=(x y)`
                j = self.close(i + 1, c, ")" if c == "(" else "}")
                nested += [s[i + 1:j]] if self.ps else self.substituted(s[i + 1:j])   # PowerShell runs ( )
                value.append(s[i:j + 1])
                i = j + 1
            else:
                value.append(c)
                i += 1
        return _Word("".join(value), s[start:i], nested)

    def tokens(self) -> list[list]:
        """["w", _Word], ["op", separator], ["redir", operator, _Word, heredoc body], ["group", text]."""
        s, tokens, pending, fresh, called, i = self.s, [], [], True, False, 0
        while i < len(s):
            c = s[i]
            if c in _SPACE:
                i += 1
            elif c == self.escape and s[i + 1:i + 2] == "\n":     # a line continuation
                i += 2
            elif c == "#":                                       # a comment, to the end of the line
                j = s.find("\n", i)
                i = len(s) if j < 0 else j
            elif c == "\n":
                for tok in pending:                              # `<<\EOF` ends at EOF
                    tok[3], i = _heredoc_body(s, i + 1, tok[2].value.replace("\\", ""))
                pending = []
                if not (tokens and tokens[-1][0] == "op" and tokens[-1][1] in ("|", "&&", "||")):
                    tokens.append(["op", ";"])
                fresh = True
                i += 1
            elif c in ")}":                                      # unbalanced: a case pattern's end
                tokens.append(["op", ";"])
                fresh = True
                i += 1
            elif c in "({":
                j = self.close(i + 1, c, ")" if c == "(" else "}")
                inner, after = s[i + 1:j], s[j + 1:j + 2]
                if fresh and (not after or after in _WORD_END):  # a group: ( ) subshell, { } block
                    tokens.append(["group", inner])
                    i = j + 1
                    continue
                rest = self.word(j + 1)                          # a ( ) or { } inside a statement
                tokens.append(["w", _Word(s[i:j + 1] + rest.value, s[i:j + 1] + rest.raw, [inner, *rest.nested])])
                fresh = False
                i = j + 1 + len(rest.raw)
            elif self.ps and fresh and c == "&" and s[i + 1:i + 2] != "&":     # `& "C:\x y\gh" pr ...`
                called = True
                i += 1
            elif sep := next(((t, op) for t, op in _SEPARATORS if s.startswith(t, i)
                              and not (t == "&" and s.startswith("&>", i))), None):
                tokens.append(["op", sep[1]])
                fresh = True
                i += len(sep[0])
            elif m := _REDIRECT.match(s, i):
                op, j = m.group(0), m.end()
                if op in ("<", ">") and s[j:j + 1] == "(":       # process substitution <( )
                    k = self.close(j + 1)
                    tokens.append(["w", _Word(s[i:k + 1], s[i:k + 1], [s[j + 1:k]])])
                    fresh = False
                    i = k + 1
                    continue
                while j < len(s) and s[j] in _SPACE:
                    j += 1
                target = self.word(j)
                tok = ["redir", op, target, None]
                tokens.append(tok)
                if op in ("<<", "<<-"):
                    pending.append(tok)
                fresh = False
                i = j + len(target.raw)
            else:
                w = self.word(i)
                i += len(w.raw) or 1
                if called:                     # the called word is a program, not a printed string
                    w, called = _Word(w.value, w.value, w.nested), False
                tokens.append(["w", w])
                fresh = False
        return tokens


# ── statements ───────────────────────────────────────────────────────────────────────────────
_KEYWORDS = frozenset({"if", "then", "elif", "else", "do", "while", "until", "!", "fi", "done", "esac"})
_ASSIGNMENT = re.compile(r"^(?:\$env:)?[A-Za-z_]\w*\+?=", re.I)
#: programs that run the command they are given, and their options that take a separate value
_WRAPPERS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}, "time": set(),
    "nice": {"-n", "--adjustment"}, "nohup": set(), "stdbuf": {"-i", "-o", "-e"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-U", "-r", "-t"},
    "xargs": {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--max-args", "--max-procs", "--delimiter"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"}, "command": set(), "exec": {"-a"}, "call": set(),
    "wsl": {"-d", "--distribution", "-u", "--user", "--cd"},
}
#: project runners whose `run` runs the command after it (`uv run python ...`), and their options
#: that take a separate value
_RUNNERS = {
    "uv": {"--with", "--with-editable", "--with-requirements", "-p", "--python", "--project", "--directory",
           "--package", "--extra", "--group", "--only-group", "--no-group", "--env-file", "--index",
           "--default-index", "-i", "--index-url", "--extra-index-url", "-f", "--find-links", "--python-platform",
           "--config-file", "--cache-dir", "--color", "--exclude-newer", "--resolution", "--prerelease",
           "--link-mode", "-C", "--config-setting", "--keyring-provider", "--allow-insecure-host"},
    "poetry": {"-C", "--directory", "-P", "--project"}, "pipenv": set(), "pdm": {"-p", "--project"},
    "hatch": set(),
}
#: builtins whose VAR=val arguments set the environment
_EXPORTS = frozenset({"export", "declare", "typeset", "readonly", "local"})
#: what a python program can hand a shell: os.system / os.popen / subprocess's runners
_PY_SHELL_CALLS = frozenset({"system", "popen", "run", "call", "check_call", "check_output", "Popen",
                             "getoutput", "getstatusoutput"})
PYTHON = re.compile(r"python[\d.]*w?|py")
_CD = frozenset({"cd", "pushd", "chdir", "set-location", "sl"})
_SH = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_PWSH = frozenset({"pwsh", "powershell"})
_SH_COMMAND = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
_PRINTERS = frozenset({"echo", "printf", "write-output"})
_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


def _read(s: str, ctx: dict, upstream: Statement | None) -> list[Statement]:
    """The statements of `s`. `ctx` holds the directory in effect, the last statement read (the
    input of a pipe that follows a group) and whether `s` is PowerShell."""
    out: list[Statement] = []
    words: list[_Word] = []
    redirs: list[list] = []
    for tok in _Lexer(s, ctx["ps"]).tokens():
        if tok[0] == "w":
            words.append(tok[1])
        elif tok[0] == "redir":
            redirs.append(tok)
        elif tok[0] == "group":            # a subshell: a cd inside it stays inside it
            inner = _read(tok[1], {**ctx, "last": None}, upstream)
            out += inner
            ctx["last"] = inner[-1] if inner else ctx["last"]
        else:
            out += _statement(words, redirs, ctx, upstream)
            upstream = ctx["last"] if tok[1] == "|" else None
            words, redirs = [], []
    out += _statement(words, redirs, ctx, upstream)
    return out


def _nested(text: str, ctx: dict, ps: bool | None = None) -> list[Statement]:
    return _read(text, {"cwd": ctx["cwd"], "last": None, "ps": ctx["ps"] if ps is None else ps}, None)


def _statement(words: list[_Word], redirs: list[list], ctx: dict, upstream: Statement | None) -> list[Statement]:
    out: list[Statement] = []
    for w in [*words, *(r[2] for r in redirs)]:
        for text in w.nested:
            out += _nested(text, ctx)
    heredoc = next((r[3] or "" for r in redirs if r[1] in ("<<", "<<-")), None)
    redirects = tuple((r[1], r[2].value) for r in redirs if r[1] not in ("<<", "<<-"))
    return out + _command([w.value for w in words], [w.raw for w in words], redirects, heredoc, ctx, upstream)


def _skip_wrapper(vals: list[str], i: int) -> int:
    """The index past wrapper `vals[i]` (a runner with its `run`) and its options (and timeout's
    duration)."""
    name = program_name(vals[i])
    takes = _WRAPPERS.get(name) or _RUNNERS[name]
    i += 2 if name in _RUNNERS else 1
    while i < len(vals) and vals[i].startswith("-") and vals[i] != "-":
        if vals[i] == "--":
            i += 1
            break
        i += 2 if vals[i] in takes else 1
    return i + 1 if name == "timeout" else i


def _command(vals: list[str], raws: list[str], redirects: tuple, heredoc: str | None, ctx: dict,
             upstream: Statement | None) -> list[Statement]:
    env: list[str] = []
    i = 0
    while i < len(vals):
        if vals[i] in _KEYWORDS:
            i += 1
        elif _ASSIGNMENT.match(vals[i]):
            env.append(vals[i])
            i += 1
        elif vals[i].startswith("$") and vals[i + 1:i + 2] == ["="]:     # PowerShell `$x = <command>`
            env.append(vals[i] + "=")
            i += 2
        elif vals[i] in _EXPORTS:
            i += 1
            while i < len(vals) and vals[i].startswith("-"):
                i += 1
        elif program_name(vals[i]) in _RUNNERS and vals[i + 1:i + 2] == ["run"]:
            i = _skip_wrapper(vals, i)
        elif program_name(vals[i]) == "env" and (split := next(
                (j for j in range(i + 1, len(vals)) if vals[j] in ("-S", "--split-string")), None)) is not None:
            return _nested(" ".join(vals[split + 1:]), ctx)              # env -S 'cmd args'
        elif program_name(vals[i]) in _WRAPPERS:
            i = _skip_wrapper(vals, i)
        else:
            break
    vals, raws = vals[i:], raws[i:]
    if not (vals or env or redirects or heredoc is not None):
        return []
    if vals and program_name(vals[0]) in _CD:
        target = next((v for v in vals[1:] if v.lower() != "/d" and not v.startswith("-")), "")
        ctx["cwd"] = _join_dir(ctx["cwd"], target) if target else ctx["cwd"]
        return []
    st = Statement(tuple(vals), tuple(raws), redirects, heredoc, tuple(env), ctx["cwd"], upstream)
    out: list[Statement] = []
    for script, ps in _scripts(st):
        out += _nested(script, ctx, ps)
    out += _exec_commands(st, ctx)
    ctx["last"] = st
    return [*out, st]


def _scripts(st: Statement) -> list[tuple[str, bool]]:
    """The command strings `st` hands to a shell to run, each with whether it is PowerShell."""
    name, args = st.program, list(st.words[1:])
    if name == "eval":
        return [(" ".join(args), False)]
    if name in ("iex", "invoke-expression"):
        return [(" ".join(args) if args else st.stdin or "", True)]
    if PYTHON.fullmatch(name):
        code = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-c"] + ([st.stdin] if st.stdin else [])
        return [(script, False) for c in code for script in _python_shell_commands(c)]
    if name == "cmd":
        k = next((i for i, a in enumerate(args) if a.lower() in ("/c", "/k", "//c", "//k")), None)   # // in Git Bash
        return [(" ".join(args[k + 1:]), False)] if k is not None else []
    ps = name in _PWSH
    if name in _SH:
        k = next((i for i, a in enumerate(args) if _SH_COMMAND.fullmatch(a)), None)
        if k is not None:
            return [(a, False) for a in args[k + 1:k + 2]]
    elif ps:
        k = next((i for i, a in enumerate(args) if len(a) > 1 and "-command".startswith(a.lower())), None)
        if k is not None:
            return [(" ".join(args[k + 1:]), True)]
    else:
        return []
    if any(not a.startswith("-") for a in args) or st.stdin is None:     # a script file, or no known stdin
        return []
    return [(st.stdin, ps)]                               # it reads its commands from stdin


def _python_shell_commands(code: str) -> list[str]:
    """The literal commands a python program hands a shell (`os.system('git reset --hard')`,
    `subprocess.run(['git', 'reset', '--hard'])`); code that does not parse runs nothing."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out = []
    for n in ast.walk(tree):
        f = getattr(n, "func", None)
        if not (isinstance(n, ast.Call) and n.args
                and (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) in _PY_SHELL_CALLS):
            continue
        arg = n.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
        elif isinstance(arg, ast.List | ast.Tuple) and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                                          for e in arg.elts):
            out.append(" ".join(e.value for e in arg.elts))
    return out


def _exec_commands(st: Statement, ctx: dict) -> list[Statement]:
    """The commands find runs with -exec / -execdir / -ok / -okdir, each up to its `;` or `+`."""
    if st.program != "find":
        return []
    out: list[Statement] = []
    w, r = st.words, st.raw
    for i, a in enumerate(w):
        if a in _EXEC:
            j = next((k for k in range(i + 1, len(w)) if w[k] in (";", "+")), len(w))
            out += _command(list(w[i + 1:j]), list(r[i + 1:j]), (), None, {**ctx, "last": None}, None)
    return out


# ── git ──────────────────────────────────────────────────────────────────────────────────────
#: git's global options that take a separate value
_GIT_GLOBAL_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                                  "--exec-path", "--config-env"})


def git_parts(words) -> tuple[list[str], str, list[str]]:
    """(global options, subcommand, its arguments) of a git statement's words (`-C <path>` takes
    a separate value); ([], "", []) when the words run no git subcommand."""
    if not words or program_name(words[0]) != "git":
        return [], "", []
    rest = list(words[1:])
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in _GIT_GLOBAL_WITH_ARG else 1
    return (rest[:i], rest[i], rest[i + 1:]) if i < len(rest) else ([], "", [])


def git_subcommand(words) -> tuple[str, list[str]]:
    """(subcommand, its arguments) of a git statement's words; ("", []) when there is none."""
    _globals, sub, args = git_parts(words)
    return sub, args


def git_repo(st: Statement) -> str:
    """The repository a git statement acts on: its -C / --git-dir / --work-tree, else its cwd."""
    g, target = git_parts(st.words)[0], ""
    for i, a in enumerate(g):
        name, eq, val = a.partition("=")
        if name in ("-C", "--git-dir", "--work-tree") and not target:
            target = val if eq else (g[i + 1] if i + 1 < len(g) else "")
    return repo_root_of((target and _join_dir(st.cwd, target)) or st.cwd)
