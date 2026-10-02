/**
 * The Python the tests run on: the project's .venv when it exists (the interpreter the console
 * and the capture daemon run on), else `python` on PATH (CI installs the requirements into it).
 */
import fs from "node:fs";
import path from "node:path";

export function projectPython(root) {
  const venv = process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
  return fs.existsSync(venv) ? venv : "python";
}
